import logging
from .strategy import filter_underlying, filter_options, score_options, select_options, getTechnicalIndicators
from models.contract import Contract

from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.data.historical.option import OptionHistoricalDataClient
import numpy as np

from core.clients import *

from alpaca.trading.enums import AssetClass

from config.params import IS_TEST, MINIMUM_PREMIUM, DELTA_MIN, DELTA_MAX, DELTA_CALL_MAX, YIELD_MIN, YIELD_MAX, OPEN_INTEREST_MIN, SCORE_MIN

logger = logging.getLogger(f"strategy.{__name__}")

def sell_puts(client, allowed_symbols, buying_power, ownedPositions, strat_logger = None, fireSettings = None):
	"""
	Scan allowed symbols and sell short puts up to the buying power limit.
	"""
	# buying_power=2500
	if not allowed_symbols or buying_power <= 0:
		return

	logger.info("Searching for put options...")
	filtered_symbols = filter_underlying(client, allowed_symbols, buying_power)
	strat_logger.set_filtered_symbols(filtered_symbols)
	if len(filtered_symbols) == 0:
		logger.info("No symbols found with sufficient buying power.")
		return
	option_contracts = client.get_options_contracts(filtered_symbols, 'put')
	
	recs = list()
	for option in option_contracts:
		if option.open_interest and int(option.open_interest) > OPEN_INTEREST_MIN:
			recs.append(option.symbol)
	snapshots = client.get_option_snapshot(recs)
	# print(len(snapshots))
	put_options = filter_options([Contract.from_contract_snapshot(contract, snapshots.get(contract.symbol, None)) for contract in option_contracts if snapshots.get(contract.symbol, None)])
	if strat_logger:
		strat_logger.log_put_options([p.to_dict() for p in put_options])
	
	if put_options:
		logger.info("Scoring put options...")
		scores = score_options(put_options)
		# logger.info(scores)
		put_options = select_options(put_options, scores)
		for p in put_options:
			print(p)
			if p.symbol in ownedPositions:
				logger.info(f"We already own {p.symbol}.  Skipping!")
				continue
				
			minimum_prem = MINIMUM_PREMIUM
			if fireSettings:
				if 'minimum_premium' in fireSettings.to_dict():
					minimum_prem = fireSettings.get("minimum_premium")
					logger.info(f'Firestore minimum premium is {minimum_prem}')
				
			if p.bid_price <= minimum_prem:
				logger.info(f"Put for {p.underlying}: {p.symbol} for premium ${p.bid_price * 100} with Strike {p.strike} has Premium lower or less than our target {minimum_prem * 100}")
				continue
				
			logger.info(f"Selling put for {p.underlying}: {p.symbol} for premium ${p.bid_price * 100}.  Strike {p.strike}")
			
			try:
				upperBollinger, lowerBollinger, rsi = getTechnicalIndicators(p.underlying, 50) #, stock_data_client)
			except:
				continue
			
			minimum_rsi = 30
			if fireSettings:
				if 'put_rsi' in fireSettings.to_dict():
					minimum_rsi = fireSettings.get("put_rsi")
					logger.info(f'Firestore minimum RSI is {minimum_rsi}')			
			
			bollingerVarianceLimimt = .985
			if fireSettings:
				if 'put_bollinger_variance' in fireSettings.to_dict():
					bollingerVarianceLimimt = fireSettings.get("put_bollinger_variance")
					logger.info(f'Firestore minimum bollingerVarianceLimimt is {bollingerVarianceLimimt}')			
			
			variance = lowerBollinger / p.strike

			if variance > bollingerVarianceLimimt:
				print(40 * '-')
				logger.info(f'Lower Bollinger of {lowerBollinger} for {p.underlying} is less than {p.strike}, but VARIANCE is {variance}.  Proceeding!')
				print(40 * '-')
			else:		
				if p.strike > lowerBollinger and lowerBollinger > 0:
					logger.info(f'Lower Bollinger of {lowerBollinger} for {p.underlying} is less than {p.strike}.  SKIPPING!')
					continue
				else:
					logger.info(f'{p.underlying} has a lower Bollinger of {lowerBollinger} and strike of {p.strike}.  Proceeding!')
				
			if rsi >= minimum_rsi:
				logger.info(f'RSI = {rsi}  Proceeding!')
				# continue
			else:
				logger.info(f'RSI for {p.symbol} = {rsi}.  SKIPPING')
				continue
				
			breakeven = p.strike - p.bid_price * 100
				
			buying_power -= 100 * p.strike 
			if buying_power < 0:
				break		
			
			# print(p)
			# IS_TEST = True
			try:	
				print(70 * '-')
				logger.info(f'PROCEEDING with {p.symbol}')
				print(70 * '-')
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
	
def sell_calls(client, stock_data_client, symbol, purchase_price, stock_qty, ownedPositions, strat_logger = None, fireSettings=None):
	"""
	Select and sell covered calls.
	"""
	if stock_qty < 100:
		msg = f"Not enough shares of {symbol} to cover short calls!  Only {stock_qty} shares are held and at least 100 are needed!"
		logger.error(msg)
		raise ValueError(msg)

	logger.info(f"Searching for call options on {symbol}...")
	potential = client.get_options_contracts([symbol], 'call')
	
	technicals = getTechnicalIndicators(symbol) #, stock_data_client)
	upperBollinger, lowerBollinger, rsi = technicals
	logger.info(f"BollingerBand for {symbol} is {upperBollinger}")
	logger.info(f"RSI for {symbol} is {rsi}")
	
	recs = list()
	for option in potential:
		# option.strike_price > upperBollinger and
		if  option.open_interest and int(option.open_interest) > OPEN_INTEREST_MIN:
			recs.append(option.symbol)
			# print(option)
	
	logger.info(f'Testing {len(recs)} options for {symbol}')
	snapshots = client.get_option_snapshot(recs)
	
	# print(ppp)
	call_options = filter_options([Contract.from_contract_snapshot(contract, snapshots.get(contract.symbol, None)) for contract in potential if snapshots.get(contract.symbol, None)])
	# call_options = filter_options([Contract.from_contract(option, client) for option in ppp], purchase_price)
	# print(call_options)
	if strat_logger:
		strat_logger.log_call_options([c.to_dict() for c in call_options])
	
	if call_options:
		scores = score_options(call_options)
		# print(scores)
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
		# if strike_price > upperBollinger:	
		logger.info(f"Strike {strike_price} is greater than UpperBollinger {upperBollinger} for symbol {contract.symbol}")
		# print(contract)
		# print(ownedPositions)
		
		continueWithContract = True
		
		minimum_prem = MINIMUM_PREMIUM
		if fireSettings:
			if 'minimum_premium' in fireSettings.to_dict():
				minimum_prem = fireSettings.get("minimum_premium")
				logger.info(f'Firestore minimum premium is {minimum_prem}')
			
		if option_price < minimum_prem:
			logger.info(f"Put for {contract.symbol}: {symbol} for premium ${option_price * 100} with Strike {strike_price} has Premium lower or less than our target {minimum_prem * 100}")
			continueWithContract = False
				
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
		# else:
			# logger.info(f"NO CALL SALE --Strike {strike_price} is less than UpperBollinger {upperBollinger} for symbol {contract.symbol}")
	else:
		logger.info(f"No viable call options found for {symbol}")
		


# message, short = roll_rinse_option(option_data=short_put, rolling=True)
# message, short

