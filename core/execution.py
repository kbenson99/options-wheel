import logging
from .strategy import filter_underlying, filter_options, score_options, select_options, getBollingerBands
from models.contract import Contract

from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.data.historical.option import OptionHistoricalDataClient
import numpy as np

from core.clients import *

from alpaca.trading.enums import AssetClass

from config.params import IS_TEST

logger = logging.getLogger(f"strategy.{__name__}")

def sell_puts(client, allowed_symbols, buying_power, ownedPositions, strat_logger = None):
	"""
	Scan allowed symbols and sell short puts up to the buying power limit.
	"""
	# buying_power=20000
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
			print(p)
			if p.symbol in ownedPositions:
				logger.info(f"We alread own {p.symbol}.  Skipping!")
				continue
			
			buying_power -= 100 * p.strike 
			if buying_power < 0:
				break
			logger.info(f"Selling put for {p.underlying}: {p.symbol} for premium ${p.bid_price * 100}.  Strike {p.strike}")
			# print(p)
			try:				
				if not IS_TEST:
					client.market_sell(p.symbol)
				else:
					logger.info("TESTING ONLY")
				if strat_logger:
					strat_logger.log_sold_puts([p.to_dict()])
			except Exception as ex:
				buying_power += 100 * p.strike
				logger.exception(str(ex))
				logger.exception(ex) 
	else:
		logger.info("No put options found with sufficient delta and open interest.")

def find_first_non_alpha_loop(s):
    for index, char in enumerate(s):
        if not char.isalpha():
            return char, index
    return None, -1 # No non-alpha character found
	
def sell_calls(client, stock_data_client, symbol, purchase_price, stock_qty, ownedPositions, strat_logger = None):
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

	bollingerBands = getBollingerBands(symbol, stock_data_client)
	upperBollinger, lowerBollinger = bollingerBands
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

		# Check if delta is between 0.42 and 0.18 and if the strike price is greater than the latest upper Bollinger band
		if strike_price > upperBollinger:	
			logger.info(f"Strike {strike_price} is greater than UpperBollinger {upperBollinger} for symbol {contract.symbol}")
			# print(contract)
			# print(ownedPositions)
			
			continueWithContract = True
			if contract.symbol in ownedPositions:
				logger.info(f"We already own {contract.symbol}.  Skipping!")
				continueWithContract = False						
			else:
				if symbol in ownedPositions:
					ownedSymbolQty = ownedPositions[symbol]
					# print(ownedSymbolQty)
					
					howManyContractsAlreadyOwned = 0
					for position in ownedPositions:
						# print(position)
						owned = ownedPositions[position]
						# print(owned)
						if owned.asset_class == AssetClass.US_OPTION:
							pos = find_first_non_alpha_loop(position)[1]
							# print(pos)
							# print(position, symbol, position[0: pos])

							if position[0: pos] == symbol and position[pos+6] =='C':
								# print(position[pos+6])
								thisPositionContract = ownedPositions[position]
								# print(thisPositionContract)
								howManyContractsAlreadyOwned += abs( int(thisPositionContract.qty))
					# print(howManyContractsAlreadyOwned, int(ownedSymbolQty.qty))
					if howManyContractsAlreadyOwned:
						if (howManyContractsAlreadyOwned +1) * 100 > int(ownedSymbolQty.qty):
							logger.info(f"Stop!  Selling this contract will put us out of synch with the number of shares of {symbol}!")
							continueWithContract = False				
			if continueWithContract:
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
		


# message, short = roll_rinse_option(option_data=short_put, rolling=True)
# message, short

