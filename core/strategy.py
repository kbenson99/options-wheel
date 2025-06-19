from config.params import DELTA_MIN, DELTA_MAX, YIELD_MIN, YIELD_MAX, OPEN_INTEREST_MIN, SCORE_MIN
from alpaca.data.requests import StockBarsRequest
from config.credentials import ALPACA_API_KEY, ALPACA_SECRET_KEY, IS_PAPER
from datetime import *
from zoneinfo import ZoneInfo
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

def filter_underlying(client, symbols, buying_power_limit):
    """
    Filter underlying symbols based on buying power.  Can add custom logic such as volatility or ranging / support metrics.
    """
    resp = client.get_stock_latest_trade(symbols)

    filtered_symbols = [symbol for symbol in resp if 100*resp[symbol].price <= buying_power_limit]

    return filtered_symbols

def filter_options(options, min_strike = 0):
    """
    Filter put options based on delta and open interest.
    """
    filtered_contracts = [contract for contract in options 
                          if contract.delta 
                          and abs(contract.delta) > DELTA_MIN 
                          and abs(contract.delta) < DELTA_MAX
                          and (contract.bid_price / contract.strike) * (365 / (contract.dte + 1)) > YIELD_MIN
                          and (contract.bid_price / contract.strike) * (365 / (contract.dte + 1)) < YIELD_MAX
                          and contract.oi 
                          and contract.oi > OPEN_INTEREST_MIN
                          and contract.strike >= min_strike]
    
    return filtered_contracts

def score_options(options):
    """
    Score options based on delta, days to expiration, and bid price.  
    The score is the annualized rate of return on selling the contract, discounted by the probability of assignment.
    """
    scores = [(1 - abs(p.delta)) * (250 / (p.dte + 5)) * (p.bid_price / p.strike) for p in options]
    return scores

def getUpperBollingerBand(underlying_symbol, stock_data_client=None):
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

	# Get the most recent Upper Band value
	latest_upper_bollinger_band = stock_data['Upper_Band'].iloc[-1]

	print(f"Latest Upper Bollinger Band is: {latest_upper_bollinger_band}")
	return latest_upper_bollinger_band
	

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
