import sys
import os

# Get the absolute path to our investment modules
module_path = os.path.abspath('C:/investment/apex') 

# Add the path to sys.path
sys.path.append(module_path)


from pathlib import Path
from core.broker_client import BrokerClient
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient, StockLatestTradeRequest

from core.execution import sell_puts, sell_calls
from core.state_manager import update_state, calculate_risk
from config.credentials import ALPACA_API_KEY, ALPACA_SECRET_KEY, IS_PAPER
from config.params import MAX_RISK
from logging.strategy_logger import StrategyLogger
from logging.logger_setup import setup_logger
from core.cli_args import parse_args

from core.strategy import getUpperBollingerBand

from configuration import *
from datetime import datetime, time
from config.params import IS_TEST


def getBrokerClient():
	client = BrokerClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY, paper=IS_PAPER)
	return client
	
def getStockClient():
	stock_data_client = StockHistoricalDataClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY)
	return stock_data_client
	
def getTradingClient():
	BASE_URL = None
	trade_client = TradingClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY, paper=IS_PAPER, url_override=BASE_URL)
	return trade_client

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

def main():
	args = parse_args()
	
	# Initialize two separate loggers
	strat_logger = getStrategyLogger()  # custom JSON logger used to persist strategy-specific state (e.g. trades, symbols, PnL).
	logger = getLogger() # standard Python logger used for general runtime messages, debugging, and error reporting.

	strat_logger.set_fresh_start(args.fresh_start)

	SYMBOLS_FILE = Path(__file__).parent.parent / "config" / "symbol_list.txt"
	with open(SYMBOLS_FILE, 'r') as file:
		SYMBOLS = [line.strip() for line in file.readlines()]

	client = getBrokerClient()
	tradingClient = getTradingClient()
	stock_data_client = getStockClient()


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
				print(positions)
				available = list()
				for position in positions:
					if int(position.qty) >= 100:
						available.append(position)
						
				positions = available
				strat_logger.add_current_positions(positions)

				current_risk = calculate_risk(positions)
				
				states = update_state(positions)
				strat_logger.add_state_dict(states)

				for symbol, state in states.items():
					if state["type"] == "long_shares":
						sell_calls(client, stock_data_client, symbol, state["price"], state["qty"], strat_logger)

				allowed_symbols = list(set(SYMBOLS).difference(states.keys()))
				
				buying_power = float(tradingClient.get_account().buying_power)
				
				# buying_power = MAX_RISK - current_risk
			
			strat_logger.set_buying_power(buying_power)
			strat_logger.set_allowed_symbols(allowed_symbols)

			logger.info(f"Current buying power is ${buying_power}")
			sell_puts(client, allowed_symbols, buying_power, strat_logger)

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
	
	client = getTradingClient()
	stock_data_client = getStockClient()
	
	upperBollinger = getUpperBollingerBand(symbol, stock_data_client)
	
	underlying_trade_response = stock_data_client.get_stock_latest_trade(underlying_trade_request)
	print(underlying_trade_response[symbol].price)
	
	strat_logger = getStrategyLogger()
	logger = getLogger()
	sell_calls(client, stock_data_client, symbol, underlying_trade_response[symbol].price, 100, strat_logger)
	
	
	print(underlying_trade_response)


if __name__ == "__main__":
	main()



