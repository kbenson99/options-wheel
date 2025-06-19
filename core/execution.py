import logging
from .strategy import filter_underlying, filter_options, score_options, select_options, getUpperBollingerBand
from models.contract import Contract
import numpy as np

from config.params import IS_TEST

logger = logging.getLogger(f"strategy.{__name__}")

def sell_puts(client, allowed_symbols, buying_power, strat_logger = None):
	"""
	Scan allowed symbols and sell short puts up to the buying power limit.
	"""
	if not allowed_symbols or buying_power <= 0:
		return

	logger.info("Searching for put options...")
	filtered_symbols = filter_underlying(client, allowed_symbols, buying_power)
	strat_logger.set_filtered_symbols(filtered_symbols)
	if len(filtered_symbols) == 0:
		logger.info("No symbols found with sufficient buying power.")
		return
	option_contracts = client.get_options_contracts(filtered_symbols, 'put')
	snapshots = client.get_option_snapshot([c.symbol for c in option_contracts])
	put_options = filter_options([Contract.from_contract_snapshot(contract, snapshots.get(contract.symbol, None)) for contract in option_contracts if snapshots.get(contract.symbol, None)])
	if strat_logger:
		strat_logger.log_put_options([p.to_dict() for p in put_options])
	
	if put_options:
		logger.info("Scoring put options...")
		scores = score_options(put_options)
		put_options = select_options(put_options, scores)
		for p in put_options:
			buying_power -= 100 * p.strike 
			if buying_power < 0:
				break
			logger.info(f"Selling put for {p.underlying}: {p.symbol} for premium ${p.bid_price * 100}.  Strike {p.strike}")
			print(p)
			if not IS_TEST:
				client.market_sell(p.symbol)
			else:
				logger.info("TESTING ONLY")
			if strat_logger:
				strat_logger.log_sold_puts([p.to_dict()])
	else:
		logger.info("No put options found with sufficient delta and open interest.")

def sell_calls(client, stock_data_client, symbol, purchase_price, stock_qty, strat_logger = None):
	"""
	Select and sell covered calls.
	"""
	if stock_qty < 100:
		msg = f"Not enough shares of {symbol} to cover short calls!  Only {stock_qty} shares are held and at least 100 are needed!"
		logger.error(msg)
		raise ValueError(msg)

	logger.info(f"Searching for call options on {symbol}...")
	call_options = filter_options([Contract.from_contract(option, client) for option in client.get_options_contracts([symbol], 'call')], purchase_price)
	if strat_logger:
		strat_logger.log_call_options([c.to_dict() for c in call_options])

	upperBollinger = getUpperBollingerBand(symbol, stock_data_client)
	logger.info(f"BollingerBand for {symbol} is {upperBollinger}")
	
	if call_options:
		scores = score_options(call_options)
		contract = call_options[np.argmax(scores)]
		logger.info(contract)
		
		
		option_price = (contract.bid_price + contract.ask_price) / 2
		open_interest = float(contract.oi)
		strike_price = float(contract.strike)

		logger.info(f"option_symbol is {contract.symbol}")
		logger.info(f"option_price is {option_price}")
		logger.info(f"strike price is {strike_price}")
		logger.info(f"open_interest is {open_interest}")
		logger.info(f"delta is {contract.delta}")

		# Check if delta is between 0.42 and 0.18 and if the strike price is greater than the latest upper boiler band
		if strike_price > upperBollinger:	
			logger.info(f"Strike {strike_price} is greater than UpperBollinger {upperBollinger} for symbol {contract.symbol}")
		
			logger.info(f"Selling call option: {contract.symbol}")
			if not IS_TEST:
				client.market_sell(contract.symbol)
			else:
				logger.info("TESTING ONLY")
			if strat_logger:
				strat_logger.log_sold_calls(contract.to_dict())
		else:
			logger.info(f"NO CALL SALE --Strike {strike_price} is less than UpperBollinger {upperBollinger} for symbol {contract.symbol}")
	else:
		logger.info(f"No viable call options found for {symbol}")