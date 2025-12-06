from config.params import DELTA_MIN, DELTA_MAX, DELTA_CALL_MAX, YIELD_MIN, YIELD_MAX, OPEN_INTEREST_MIN, SCORE_MIN
from alpaca.data.requests import StockBarsRequest
from config.credentials import ALPACA_API_KEY, ALPACA_SECRET_KEY, IS_PAPER
from datetime import *
from zoneinfo import ZoneInfo
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import yfinance as yf
import pandas_ta as ta
import pandas as pd

def filter_underlying(client, symbols, buying_power_limit):
	"""
	Filter underlying symbols based on buying power.  Can add custom logic such as volatility or ranging / support metrics.
	"""
	resp = client.get_stock_latest_trade(symbols)

	filtered_symbols = [symbol for symbol in resp if 100*resp[symbol].price <= buying_power_limit]

	return filtered_symbols

def testOption(contract, min_strike = 0):
	if contract.contract_type == 'call':
		max_delta = DELTA_CALL_MAX
	# print(contract)
	# if (contract.delta):
		# print(abs(contract.delta) > DELTA_MIN)
		# print(contract.delta < max_delta)
	# print('bid', contract.bid_price)
	# print('strike', contract.strike)
	# print('dte', contract.dte)
	# print(2 * '-')
	# print(contract.bid_price / contract.strike)
	# print(contract.dte + 1)
	# print(contract.oi)
	# print(contract.bid_price / contract.strike) * (365 / (contract.dte + 1))
	# print(contract.bid_price / contract.strike) * (365 / (contract.dte + 1))
	# print(contract.oi > OPEN_INTEREST_MIN)
	# print(contract.strike >= min_strike)

	valid = contract.delta and abs(contract.delta) > DELTA_MIN \
		and abs(contract.delta) < max_delta \
		and contract.oi \
		and contract.oi > OPEN_INTEREST_MIN \
		and contract.strike >= min_strike	
	if contract.contract_type != 'call':
		valid = valid and (contract.bid_price / contract.strike) * (365 / (contract.dte + 1)) > YIELD_MIN \
					and (contract.bid_price / contract.strike) * (365 / (contract.dte + 1)) < YIELD_MAX 
	# print('Valid', valid)
	# print(40* '-')
	return valid
	
def filter_options(options, min_strike = 0):
	"""
	Filter put options based on delta and open interest.
	"""
	filtered_contracts = list()
	for contract in options:
		max_delta = DELTA_MAX
		if contract.contract_type == 'call':
			max_delta = DELTA_CALL_MAX
		if testOption(contract, min_strike):
			filtered_contracts.append(contract)						  
						 
	# filtered_contracts = [contract 
						  # for contract in options:
						  # if contract.delta 
						  # and abs(contract.delta) > DELTA_MIN 
						  # and abs(contract.delta) < DELTA_MAX
						  # and (contract.bid_price / contract.strike) * (365 / (contract.dte + 1)) > YIELD_MIN
						  # and (contract.bid_price / contract.strike) * (365 / (contract.dte + 1)) < YIELD_MAX
						  # and contract.oi 
						  # and contract.oi > OPEN_INTEREST_MIN
						  # and contract.strike >= min_strike]
	
	return filtered_contracts

def score_options(options):
	"""
	Score options based on delta, days to expiration, and bid price.  
	The score is the annualized rate of return on selling the contract, discounted by the probability of assignment.
	"""
	scores = [(1 - abs(p.delta)) * (250 / (p.dte + 5)) * (p.bid_price / p.strike) for p in options]
	return scores

def getTechnicalIndicators(ticker, window=20, num_std=2):
	"""
	Calculates Bollinger Bands for a given price series.
	
	Args:
		data (pd.Series): The historical stock price data (usually 'Close' prices).
		window (int): The lookback period for the moving average and standard deviation.
		num_std (int): The number of standard deviations for the bands.
		
	Returns:
		pd.DataFrame: DataFrame with the original price, middle, upper, and lower bands.
	"""
	
	# Step 1: Fetch stock data
	start = datetime.now()
	days = 60 + window
	end = start - timedelta(days=days)
	
	data = yf.download(ticker, start=end.strftime('%Y-%m-%d'), end=start.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
	
	# Calculate the rolling mean (middle band)
	data['SMA'] = data['Close'].rolling(window=window).mean()
	
	# Calculate the rolling standard deviation (use ddof=0 for population standard deviation)
	data['STD'] = data['Close'].rolling(window=window).std(ddof=0)
	
	# Calculate the upper and lower bands
	data['Upper'] = data['SMA'] + (data['STD'] * num_std)
	data['Lower'] = data['SMA'] - (data['STD'] * num_std)
 

	# Get the most recent Upper and Lower Band values
	upper_bollinger_band = data['Upper'].iloc[-1]
	lower_bollinger_band = data['Lower'].iloc[-1]

	rsi = ta.rsi(data["Close"][ticker], length=14)
	# print(f"Latest Upper Bollinger Band is: {upper_bollinger_band}")
	# print(f"Latest Lower Bollinger Band is: {lower_bollinger_band}")
	return upper_bollinger_band, lower_bollinger_band, float(rsi.iloc[-1])

	
def getBollingerBandsOld(underlying_symbol, stock_data_client=None):
	# setup stock historical data client
	timezone = ZoneInfo("America/New_York")

	# Get current date in US/Eastern timezone
	today = datetime.now(timezone).date()

	now = datetime.now(ZoneInfo("America/New_York"))
	req = StockBarsRequest(
		symbol_or_symbols=[underlying_symbol],
		timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Day),  # specify timeframe
		start=today-timedelta(days=60),                       # specify start datetime, default=the beginning of the current day.
		end=today,                                                  # specify end datetime, default=now
	)
	
	if not stock_data_client:
		stock_data_client = StockHistoricalDataClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY)

	stock_data = stock_data_client.get_stock_bars(req).df

	# Define the window period for the Bollinger Bands
	window = 20

	# Calculate the Simple Moving Average (SMA)
	stock_data['SMA'] = stock_data['close'].rolling(window=window).mean()

	# Calculate the rolling standard deviation
	stock_data['StdDev'] = stock_data['close'].rolling(window=window).std()

	# Set the multiplier (commonly 2)
	multiplier = 2

	# Calculate the Upper Bollinger Band
	stock_data['Upper_Band'] = stock_data['SMA'] + (multiplier * stock_data['StdDev'])
	
	# Calculate the Lower Bollinger Band
	stock_data['Lower_Band'] = stock_data['SMA'] - (multiplier * stock_data['StdDev'])

	# Get the most recent Upper Band value
	upper_bollinger_band = stock_data['Upper_Band'].iloc[-1]
	lower_bollinger_band = stock_data['Lower_Band'].iloc[-1]

	print(f"Latest Upper Bollinger Band is: {upper_bollinger_band}")
	print(f"Latest Lower Bollinger Band is: {lower_bollinger_band}")
	return upper_bollinger_band, lower_bollinger_band
	

def select_options(options, scores, n=None):
	"""
	Select the top n options, keeping only the highest-scoring option per underlying symbol.
	"""
	# Filter out low scores
	filtered = [(option, score) for option, score in zip(options, scores) if score > SCORE_MIN]

	# Pick the best option per underlying
	best_per_underlying = {}
	for option, score in filtered:
		underlying = option.underlying
		if (underlying not in best_per_underlying) or (score > best_per_underlying[underlying][1]):
			best_per_underlying[underlying] = (option, score)

	# Sort the best options by score
	sorted_best = sorted(best_per_underlying.values(), key=lambda x: x[1], reverse=True)
	# print(sorted_best)

	# Return top n (or all if n not specified)
	return [option for option, _ in sorted_best[:n]] if n else [option for option, _ in sorted_best]


# Exit the market order
def roll_rinse_execution(option_data, rolling=True):

	# if rolling the option, close the short put and re-enter the market with a new cash secured put or close the long call and re-enter the market with a new long call
	if rolling:
		# Deternine if the option is a call or put
		option_type = option_data['type'].value

		# If the option is a put, close the short put by buying it back
		if option_type == 'put':

			# Close the short put by buying it back
			req = MarketOrderRequest(
				symbol=option_data['symbol'],
				qty=1,
				side='buy',
				type='market',
				time_in_force='day'
			)

			# Submit the order to close the short put
			trade_client.submit_order(req)
			print(f"Closed short {option_type} option: {option_data['symbol']} bought")

			# Re-enter the market with a new cash secured put
			rolling_message, short = execute_cash_secured_put(underlying_symbol, RISK_FREE_RATE, buying_power_limit)

			if short:
				# You can add the `rolling_message` from the `execute_cash_secured_put` function below to check if the short put or call is not sccessfully placed
				return f"Re-entering market with new cash secured put on {option_data['underlying_symbol']}", short
			else:
				return f"Failed to re-enter market with new cash secured put on {option_data['underlying_symbol']}", None

		# If the option is a call, close the short call by buying it back
		else:
			# Close the short call by buying it back
			req = MarketOrderRequest(
				symbol=option_data['symbol'],
				qty=1,
				side='buy',
				type='market',
				time_in_force='day'
			)

			# Submit the order to close the covered call (short call)
			trade_client.submit_order(req)
			print(f"Closing short {option_type} option: {option_data['symbol']} sold")

			# Re-enter the market with a new covered call
			rolling_message, short = execute_covered_call(underlying_symbol, RISK_FREE_RATE, buying_power_limit)

			if short:
				return f"Re-entering market with new covered call on {option_data['underlying_symbol']}", short
			else:
				return f"Failed to re-enter market with new covered call on {option_data['underlying_symbol']}", None

	else:
		# If the option is a put, close the short put by buying it back
		if option_type == 'put':

			# Close the short put by buying it back
			req = MarketOrderRequest(
				symbol=option_data['symbol'],
				qty=1,
				side='buy',
				type='market',
				time_in_force='day'
			)
			trade_client.submit_order(req)
			return f"Closed short {option_type} option: {option_data['symbol']} bought", None

		 # If the option is a call, close the short call by buying it back
		else:
			# Close the short call by buying it back
			req = MarketOrderRequest(
				symbol=option_data['symbol'],
				qty=1,
				side='buy',
				type='market',
				time_in_force='day'
			)

			# Submit the order to close the covered call (short call)
			trade_client.submit_order(req)
			return f"Closing short {option_type} option: {option_data['symbol']} sold", None


