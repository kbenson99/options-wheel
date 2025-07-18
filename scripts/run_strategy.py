import sys
import os

# Get the absolute path to our investment modules
module_path = os.path.abspath('C:/investment/apex') 

# Add the path to sys.path
sys.path.append(module_path)


from pathlib import Path
from core.broker_client import BrokerClient
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockLatestTradeRequest
from alpaca.data.requests import OptionLatestQuoteRequest

from core.execution import sell_puts, sell_calls
from core.state_manager import update_state, calculate_risk
from config.credentials import ALPACA_API_KEY, ALPACA_SECRET_KEY, IS_PAPER
from config.params import MAX_RISK
from logging.strategy_logger import StrategyLogger
from logging.logger_setup import setup_logger
from core.cli_args import parse_args

from alpaca.trading.enums import ContractType, AssetStatus, AssetClass

from core.strategy import getBollingerBands
from core.execution import find_first_non_alpha_loop

from core.clients import *

from configuration import *
from datetime import datetime, time
from scipy.stats import norm
from scipy.optimize import brentq
import numpy as np

from config.params import IS_TEST

RISK_FREE_RATE = 0.01

# class BrokerClientInstance:
	# _instance = None

	# def __new__(cls, *args, **kwargs):
		# if cls._instance is None:
			# cls._instance = super().__new__(cls)
		# return cls._instance

	# def __init__(self):
		# __init__ will be called every time, but on the same instance
		# if not hasattr(self, '_initialized'): # Prevent re-initialization
			# self.client = getBrokerClient()
			# self._initialized = True
			

# def getBrokerClient():
	# client = BrokerClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY, paper=IS_PAPER)
	# return client
	
# def getStockClient():
	# stock_data_client = StockHistoricalDataClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY)
	# return stock_data_client
	
# def getTradingClient():
	# BASE_URL = None
	# trade_client = TradingClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY, paper=IS_PAPER, url_override=BASE_URL)
	# return trade_client

def getStrategyLogger():
	args = parse_args()
	strat_logger = StrategyLogger(enabled=args.strat_log)
	return strat_logger

def getLogger():
	args = parse_args()
	logger = setup_logger(level=args.log_level, to_file=args.log_to_file)
	return logger

def is_time_in_range(start_time, end_time, current_time):
    """
    Checks if a given current_time falls within a specified time range.

    Args:
        start_time (datetime.time): The start time of the range.
        end_time (datetime.time): The end time of the range.
        current_time (datetime.time): The time to check.

    Returns:
        bool: True if current_time is within the range, False otherwise.
    """
    if start_time <= end_time:
        # Case 1: Time range within the same day (e.g., 09:00 - 17:00)
        return start_time <= current_time < end_time
    else:
        # Case 2: Time range spans across midnight (e.g., 22:00 - 06:00)
        return start_time <= current_time or current_time < end_time
		
def getCurrentPositions(optionsOnly=False, rawOnly=False):
	client = AlpacaClientInstance().getClient(BrokerClient)
	positions = client.get_positions()
	
	data = dict()
	if rawOnly:
		return positions
	else:
		for p in positions:
			# print(p.asset_class)
			if p.asset_class == AssetClass.US_EQUITY:
				if not optionsOnly:
					data[p.symbol] = p
			else:
				data[p.symbol] = p
		return data

def main():
	args = parse_args()
	
	# Initialize two separate loggers
	strat_logger = getStrategyLogger()  # custom JSON logger used to persist strategy-specific state (e.g. trades, symbols, PnL).
	logger = getLogger() # standard Python logger used for general runtime messages, debugging, and error reporting.

	strat_logger.set_fresh_start(args.fresh_start)

	SYMBOLS_FILE = Path(__file__).parent.parent / "config" / "symbol_list.txt"
	with open(SYMBOLS_FILE, 'r') as file:
		SYMBOLS = [line.strip() for line in file.readlines()]

	client = AlpacaClientInstance().getClient(BrokerClient)
	tradingClient = AlpacaClientInstance().getClient(TradingClient)
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient)


	portNumber = 7050
	s = None
	connected = False
	try:    
		s = getSocketPort(portNumber)
		connected = True
	
		logger.info("Received a lock on local port {}".format(portNumber))
		now = datetime.now()
		marketOpen = market_is_open(now)
		if marketOpen:
			start_time_day = time(9, 30)  # 9:30 AM
			end_time_day = time(16, 0) # 4:00 PM
			opened = is_time_in_range(start_time_day, end_time_day, now.time())
			if not opened:
				marketOpen = False
		
		if not marketOpen:
			logger.info("Market is not open")
			if IS_TEST:
				logger.info("Running TESTS even though market is not open")
		
		if marketOpen or IS_TEST:
			if args.fresh_start:
				logger.info("Running in fresh start mode — liquidating all positions.")
				client.liquidate_all_positions()
				allowed_symbols = SYMBOLS
				buying_power = MAX_RISK
			else:
				positions = client.get_positions()
				# print(positions)
				available = list()
				for position in positions:
					if int(position.qty) >= 100:
						available.append(position)
						
				positions = available
				strat_logger.add_current_positions(positions)

				current_risk = calculate_risk(positions)
				
				states = update_state(positions)
				strat_logger.add_state_dict(states)

				ownedPositions = getCurrentPositions()
				
				# Run the close Options that are now rollable
				optionPositions = getCurrentPositions(optionsOnly=True)
				for h in optionPositions:
					try:
						rec = optionPositions[h]
						shouldClose = roll_rinse_option(rec)
						if shouldClose and marketOpen:
							tradingClient.close_position(rec.symbol)
					except Exception as re:
						logger.exception(str(re))
						logger.exception(re)

				for symbol, state in states.items():
					if state["type"] == "long_shares":
						sell_calls(client, stock_data_client, symbol, state["price"], state["qty"], ownedPositions, strat_logger)

				allowed_symbols = list(set(SYMBOLS).difference(states.keys()))
				
				buying_power = float(tradingClient.get_account().buying_power)
				
				# buying_power = MAX_RISK - current_risk
			
			strat_logger.set_buying_power(buying_power)
			strat_logger.set_allowed_symbols(allowed_symbols)

			logger.info(f"Current buying power is ${buying_power}")
			
			ownedPositions = getCurrentPositions(True)
			sell_puts(client, allowed_symbols, buying_power, ownedPositions, strat_logger)

			strat_logger.save()    
	
	except Exception as ex:
		logger.exception(str(ex))
		logger.exception(ex)
	finally:
		if connected:			
			s.close()
			logger.info("Released port {}".format(portNumber))



def testSellCall(symbol):
	underlying_trade_request = StockLatestTradeRequest(symbol_or_symbols=symbol)
	
	client = AlpacaClientInstance().getClient(TradingClient)
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient)
	
	upperBollinger = getBollingerBands(symbol, stock_data_client)
	
	underlying_trade_response = stock_data_client.get_stock_latest_trade(underlying_trade_request)
	print(f"Current price for {symbol} is {underlying_trade_response[symbol].price}")
	
	strat_logger = getStrategyLogger()
	logger = getLogger()
	# sell_calls(client, stock_data_client, symbol, underlying_trade_response[symbol].price, 100, strat_logger)
	
	
	print(underlying_trade_response)

# Calculate implied volatility
def calculate_implied_volatility(option_price, S, K, T, r, option_type):

    # Define a reasonable range for sigma
    sigma_lower = 1e-6
    sigma_upper = 5.0  # Adjust upper limit if necessary

    # Check if the option is out-of-the-money and price is close to zero
    intrinsic_value = max(0, (S - K) if option_type == 'call' else (K - S))
    if option_price <= intrinsic_value + 1e-6:

        # print("Option price is close to intrinsic value; implied volatility is near zero.") # Uncomment for checking the status
        return 0.0

    # Define the function to find the root
    def option_price_diff(sigma):
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        if option_type == 'call':
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        elif option_type == 'put':
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        return price - option_price

    try:
        return brentq(option_price_diff, sigma_lower, sigma_upper)
    except ValueError as e:
        print(f"Failed to find implied volatility: {e}")
        return None
		
# Calculate option Delta
def calculate_delta(option_price, strike_price, expiry, underlying_price, risk_free_rate, option_type):
    T = (expiry - pd.Timestamp.now()).days / 365
    T = max(T, 1e-6)  # Set minimum T to avoid zero

    if T == 1e-6:
        print("Option has expired or is expiring now; setting delta based on intrinsic value.")
        if option_type == 'put':
            return -1.0 if underlying_price < strike_price else 0.0
        else:
            return 1.0 if underlying_price > strike_price else 0.0

    implied_volatility = calculate_implied_volatility(option_price, underlying_price, strike_price, T, risk_free_rate, option_type)
    print(f"implied volatility is {implied_volatility}")
    if implied_volatility is None or implied_volatility == 0.0:
        print("Implied volatility could not be determined, skipping delta calculation.")
        return None

    d1 = (np.log(underlying_price / strike_price) + (risk_free_rate + 0.5 * implied_volatility ** 2) * T) / (implied_volatility * np.sqrt(T))
    delta = norm.cdf(d1) if option_type == 'call' else -norm.cdf(-d1)
    return delta
	
def getPutOption(owned_option):
	client = AlpacaClientInstance().getClient(BrokerClient)

	stock = owned_option.symbol[0: find_first_non_alpha_loop(owned_option.symbol)[1]]
	
	option_contracts = client.get_options_contracts([stock], 'put')
	for option in option_contracts:
		if option.symbol == owned_option.symbol:
			break
	return option

# calculate the current delta of the option (rolling or rinsing)
def roll_rinse_option(option_data, rolling=True):
	logger = getLogger()
	shouldSell = False

    # Get the latest quote for the option price
	option_symbol = option_data.symbol
	option_quote_request = 	OptionLatestQuoteRequest(symbol_or_symbols=option_symbol)
	option_historical_data_client = AlpacaClientInstance().getClient(OptionHistoricalDataClient)

	option_quote = option_historical_data_client.get_option_latest_quote(option_quote_request)[option_symbol]
	# print(option_quote)
	
	currentOptionContract = getPutOption(option_quote)
	# print(currentOptionContract)

    # Extract option details
	current_option_price = (option_quote.bid_price + option_quote.ask_price) / 2
	strike_price = float(currentOptionContract.strike_price)
	expiry = pd.Timestamp(currentOptionContract.expiration_date)

	print(f"option_symbol is {option_symbol}")
	print(f"current option_price is {current_option_price}")
	print(f"Original option price is {option_data.avg_entry_price}")
	print(f"current strike price is {strike_price}")
	
	remainingPerc = current_option_price / float(option_data.avg_entry_price)
	
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient)
	
	underlying_trade_request = StockLatestTradeRequest(symbol_or_symbols=currentOptionContract.root_symbol)
	underlying_trade_response = stock_data_client.get_stock_latest_trade(underlying_trade_request)
	
	underlying_price = underlying_trade_response[currentOptionContract.root_symbol].price
	print(f"Current price for {currentOptionContract.root_symbol} is {underlying_price}")
	

	# Deternine if the option is a call or put
	option_type = currentOptionContract.type.value
	# If the option is a put, calculate the delta for the put option
	if option_type == 'put':

        # Calculate delta for each option
		current_delta = calculate_delta(
			option_price=current_option_price,
			strike_price=strike_price,
			expiry=expiry,
			underlying_price=underlying_price,
			risk_free_rate=RISK_FREE_RATE,
			option_type='put'
		)

    # If the option is a call, calculate the delta for the call option
	else:
		current_delta = calculate_delta(
			option_price=current_option_price,
			strike_price=strike_price,
			expiry=expiry,
			underlying_price=underlying_price,
			risk_free_rate=RISK_FREE_RATE,
			option_type='call'
		)

	# Set target profit levels in two ways: 1) 50% of the initial credit received, 2) 2x the initial delta of the short put
	# print(option_data)
	targetPercentageLeft = .45
	target_profit_price = float(option_data.avg_entry_price) * targetPercentageLeft  # x% of credit received
	print(current_delta)
	# initial_delta = option_data['initial_delta'] * 2  # Set target delta level at 2x the initial delta of the short put

	# roll or rinse the option if the absoluete value of the current delta is greater than or equal to the initial delta
	# if abs(current_delta) >= abs(initial_delta) or current_option_price <= target_profit_price:

	# targetPercentageLeft = 1-targetPercentageLeft
	# if current_option_price <= target_profit_price and abs(current_delta) > .5:
	if (remainingPerc <= targetPercentageLeft and abs(current_delta) > .5):  #or remainingPerc > 1.0 :
		# Roll or rinse the option
		# rinsing_message, short = roll_rinse_execution(option_data, rolling=rolling)
		shouldSell = True

		# you can add the `rinsing_message` from the `roll_rinse_execution` function below to check if the short put or call is not sccessfully placed
		targetPercentageLeft *= 100
		msg = f"The option price {current_option_price} for {option_symbol} is less than {targetPercentageLeft}% of the initial credit received of {option_data.avg_entry_price}. Delta {current_delta}.  Current {underlying_price}. Remaining {remainingPerc}.  Executing roll/rinse." #, short
		# msg = f"The option price {current_option_price} for {option_symbol} is less than {targetPercentageLeft}% of the initial credit received of {option_data.avg_entry_price}. Executing roll/rinse." #, short
		logger.info(msg)

	else:
		targetPercentageLeft *= 100
		msg = f"The option price is greater than {targetPercentageLeft}% of the initial credit received. Remaining {remainingPerc}. Delta {current_delta}. Holding the position.", None
		logger.info(msg)
	return shouldSell

if __name__ == "__main__":
	main()



