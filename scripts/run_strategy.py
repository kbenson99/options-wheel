from config import *
from py_alpaca_api import PyAlpacaAPI

from pathlib import Path
from core.broker_client import BrokerClient
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockLatestTradeRequest
from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.trading.requests import GetOrdersRequest
import re


from core.execution import sell_puts, sell_calls
from core.state_manager import update_state, calculate_risk
from config.credentials import ALPACA_API_KEY, ALPACA_SECRET_KEY, IS_PAPER, ENVIRONMENT, getOptionsConfiguration
from config.params import MAX_RISK
from logging.strategy_logger import StrategyLogger
from logging.logger_setup import setup_logger
from core.cli_args import parse_args
from zoneinfo import ZoneInfo

from alpaca.trading.enums import ContractType, AssetStatus, AssetClass, QueryOrderStatus

from core.strategy import getTechnicalIndicators
from core.execution import find_first_non_alpha_loop

from core.clients import *

from configuration import *
from datetime import datetime, time
from scipy.stats import norm
from scipy.optimize import brentq
import numpy as np

import pandas as pd

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

pd.options.mode.chained_assignment = None

import pickle

from config.params import IS_TEST, TARGET_CLOSING_PERC

RISK_FREE_RATE = 0.01

pattern = r'\d+'

PRODUCTION = 'production'
PAPER = 'paper'

def getStrategyLogger():
	args = parse_args()
	filename = "logs/strategy_log.json"
	if not IS_PAPER:
		filename = "logs/strategy_log-prod.json"
	strat_logger = StrategyLogger(enabled=args.strat_log, log_path=filename)
	return strat_logger

def getLogger():
	args = parse_args()
	filename = "logs/run.log"
	if not IS_PAPER:
		filename = "logs/run-prod.log"
	logger = setup_logger(level=args.log_level, to_file=args.log_to_file, log_file=filename)
	return logger

def is_same_day(dt1, dt2):
	"""
	Compares two datetime objects to check if they represent the same calendar day.

	Args:
	dt1: The first datetime object.
	dt2: The second datetime object.

	Returns:
	True if both datetime objects fall on the same calendar day, False otherwise.
	"""
	return dt1.date() == dt2.date()
  
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
	client = AlpacaClientInstance().getClient(BrokerClient, ENVIRONMENT)
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

def getRuntimeSettingsOLD(environment):
	perc = TARGET_CLOSING_PERC
	
	sell_put_active = False
	sell_call_active = False
	close_put_active = False
	close_call_active = False
	
	df = OptionsDatabase.getDatabaseRecords(optionsRuntimeTable, False)
	if not df.empty:
		rec = df.loc[df[environmentColumn ] == environment, optionsTargetGainPercentage] 
		if not rec.empty:
			perc = float(rec.iloc[0])
		rec = df.loc[df[environmentColumn ] == environment, optionssell_put_active] 
		if not rec.empty:
			rec = rec.iloc[0]
			sell_put_active = rec.upper() == 'Y'
		rec = df.loc[df[environmentColumn ] == environment, optionssell_call_active] 
		if not rec.empty:
			rec = rec.iloc[0]
			sell_call_active = rec.upper() == 'Y'
		rec = df.loc[df[environmentColumn ] == environment, optionsclose_put_active] 
		if not rec.empty:
			rec = rec.iloc[0]
			close_put_active = rec.upper() == 'Y'
		rec = df.loc[df[environmentColumn ] == environment, optionsclose_call_active] 
		if not rec.empty:
			rec = rec.iloc[0]
			close_call_active = rec.upper() == 'Y'
	return sell_put_active, sell_call_active, close_put_active, close_call_active, perc
	
def getTargetClosingPercentage(environment):
	perc = TARGET_CLOSING_PERC
	df = OptionsDatabase.getDatabaseRecords(optionsRuntimeTable, False)
	if not df.empty:
		rec = df.loc[df[environmentColumn ] == environment, optionsTargetGainPercentage] 
		if not rec.empty:
			perc = float(rec.iloc[0])
	return perc
	
def isEnabled(environment):
	active = False
	df = OptionsDatabase.getDatabaseRecords(optionsRuntimeTable, False)
	# print(df)
	
	if not df.empty:
		rec = df.loc[df[environmentColumn ] == environment, isActiveColumn.lower()] 
		if not rec.empty:
			rec = rec.iloc[0]
			active = rec.upper() == 'Y'
	return active

def getSymbolSource():
	file = Path(__file__).parent.parent / "config" / "symbol_list.txt"
	return file
	
def getSymbols(fromLocal=False):
	df = None
	if not fromLocal:
		df = OptionsDatabase.getDatabaseRecords(optionsSymbolsTable, False)
	else:
		df = OptionsDatabase.getDatabaseRecords(optionsSymbolsTable, False, db=DbVariables.MariaDbOptions)
	# symbols = df[symbolColumn.lower()].unique().tolist()
	return df

def syncSymbols(df, service=DbVariables.MariaDbOptions):
	OptionsDatabase.deleteAllTableRecords(table=DbVariables.OPTIONS_SYMBOLS_TABLE, service=service)
	df_renamed = df.rename(columns={symbolColumn.lower(): symbolColumn, creationTimestampColumn.lower(): creationTimestampColumn})
	# print(df_renamed)
	df_new = df_renamed.drop(creationTimestampColumn, axis=1)
	# print(df_new)
	OptionsDatabase.insertDatabaseRecords(df_new, optionsSymbolsTable, db=service)
	
def loadSymbolsFromCsv():
	df = pd.read_csv(getSymbolSource())
	# print(optionsSymbolsTable)
	OptionsDatabase.insertDatabaseRecords(df, optionsSymbolsTable, DbVariables.PostgreSqlNeonOptionTech)

def getPyAlpacaClient(environment: str = PAPER):
	valid_env = [PAPER, PRODUCTION]
	if environment not in valid_env:
		raise ValidationError(
			f"Invalid environment '{environment}'. Must be one of: {', '.join(valid_env)}"
		)

	key, secret = getOptionsConfiguration(environment)
	# Initialize with your API credentials
	api = PyAlpacaAPI(
		api_key=key,
		api_secret=secret,
		api_paper=environment==PAPER  # Use paper trading for testing
	)
	return api
	
def checkAccount(environment: str = PAPER):
	logger = getLogger()
	api = getPyAlpacaClient(environment)
	
	account = api.trading.account.get()
	logger.info(f"Account Balance: ${account.cash}")
	logger.info(f"Buying Power: ${account.buying_power}")
	logger.info(f"Options Buying Power: ${account.options_buying_power}")
	
	config = api.trading.account.get_configuration()
	logger.info(f"PDT Check: {config.pdt_check}")
	logger.info(f"Trade Confirm Email: {config.trade_confirm_email}")
	logger.info(f"Suspend Trade: {config.suspend_trade}")
	logger.info(f"No Shorting: {config.no_shorting}")	
	
	logger.info(30 * '=')
	logger.info(account)
	logger.info(30 * '=')
	logger.info(config)
	return account

# Get the latest price of the underlying stock
def get_underlying_price(symbol, stock_data_client=None):
	if type(symbol) == str:
		symbol = symbol.split(",")
		x = set(symbol)
		symbol = list(x)
	else:
		x = set(symbol)
		symbol = list(x)
		symbol = ",".join(symbol)
		# print(symbol)

	# Set the timezone
	timezone = ZoneInfo("America/New_York")
	# Get current date in US/Eastern timezone
	today = datetime.now(timezone).date()
	# Get the latest trade for the underlying stock
	underlying_trade_request = StockLatestTradeRequest(symbol_or_symbols=symbol)
	if not stock_data_client:
		stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient, ENVIRONMENT)
	underlying_trade_response = stock_data_client.get_stock_latest_trade(underlying_trade_request)
	return underlying_trade_response	
  
def getUnderlyingSymbol(symbol):
	match = re.search(pattern, symbol)
	underlying_symbol = symbol[0:match.start()]
	return underlying_symbol

def getSymbolStrikeAndType(symbol):
	match = re.search(pattern, symbol)
	strike = symbol[match.end()+1:]
	optionType = symbol[match.end():match.end()+1]
	# print(strike)
	return optionType, float(strike)/1000

def getExpiration(symbol):
	match = re.search(pattern, symbol)
	expireStr = symbol[match.start():match.end()]
	year = 2000 + int(expireStr[0:2])
	month = int(expireStr[2:4])
	day = int(expireStr[4:6])

	expires = datetime(year, month, day)
	return expires

def getOrders(environment, direction='asc'):
	request_params = GetOrdersRequest(
					limit=500,
					status=QueryOrderStatus.ALL
					,direction=direction
					# ,side=OrderSide.SELL
				 )	
	tradingClient = AlpacaClientInstance().getClient(TradingClient, environment)
	orders = tradingClient.get_orders(filter=request_params) 
	return orders


def wasTradedToday(symbol, orders):
	tradedToday = False
	now = datetime.now()
	for order in orders:
		if order.symbol == symbol:
			filled = order.filled_at
			if is_same_day(now, filled):
				tradedToday = True
				break
	return tradedToday

def send_option_positions_email(sender_email, sender_password, recipient_email, df, environment, messages=list(), smtp_server='smtp.gmail.com', smtp_port=587):
	"""
	Sends an HTML email with stock positions.

	Parameters:
	- sender_email: str, your email address
	- sender_password: str, your email password or app-specific password
	- recipient_email: str, recipient's email address
	- stock_positions: list of dicts, each with keys like 'Ticker', 'Shares', 'Price', 'Value'
	- smtp_server: str, SMTP server address
	- smtp_port: int, SMTP server port
	"""


	html = f"""
		<html>
		<body>
			<h2>Options Portfolio for {environment.upper()}</h2>
			<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
				<tr>
					<th>Symbol</th>
					<th>Type</th>
					<th>Underlyprice</th>
					<th>Strike</th>
					<th>Breakeven</th>
					<th>At Risk</th>
				</tr>
		"""

	for _, row in df.iterrows():
		row_bg = "background-color:#ffcccc;" if row['Risk'] == 'Y' else ""
		# <td style="color:{change_color};">{row['Change']:+.2f}</td>
		# change_color = "green" if row['Change'] >= 0 else "red"
		html += f"""
			<tr style="{row_bg}">
				<td><b>{row['Symbol']}</b></td>
				<td>{row['Type']}</td>
				<td>${row['Price']:.2f}</td>
				<td>${row['Strike']:.2f}</td>
				<td>${row['Breakeven']:.2f}</td>
				<td>{row['Risk']}</td>
			</tr>
		"""

	html += """
		</table>	
		"""
		
	if messages:
		html += """
			<h2>Notes</h2>
			<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
				<tr>
					<th>Message</th>
				</tr>
			"""
		
		for message in messages:
			html += f"""
			<tr>
				<td><b>{message}</b></td>
			</tr>
		"""	
		
		html += """
			</table>	
		"""
			
	html += """	
		</body>
		</html>
		"""

	# Create email message
	msg = MIMEMultipart("alternative")
	msg["Subject"] = f"Current Option Positions -{environment.upper()}"
	msg["From"] = sender_email
	msg["To"] = recipient_email
	msg.attach(MIMEText(html, "html"))

	# Send email
	try:
		with smtplib.SMTP(smtp_server, smtp_port) as server:
			server.starttls()
			server.login(sender_email, sender_password)
			server.sendmail(sender_email, recipient_email, msg.as_string())
		print("Email sent successfully.")
	except Exception as e:
		print(f"Failed to send email: {e}")
 
def checkTrades(environment: str = PAPER):
	valid_env = [PAPER, PRODUCTION]
	if environment not in valid_env:
		raise ValidationError(
			f"Invalid environment '{environment}'. Must be one of: {', '.join(valid_env)}"
		)
	logger = getLogger() # standard Python logger used for general runtime messages, debugging, and error reporting.
	
	column_names = [environmentColumn, optionsKeyColumn, optionsActivityBlobColumn]
	shouldEmail = False
	
	df = pd.DataFrame(columns=column_names)

	orders = getOrders(environment)
	# print(orders)
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient, environment)
	
	testing = dict()
	losers = 0
	closedTotalPremium = 0
	cnt = 0
	pattern = r'\d+'
	# print(orders)
	print(len(orders))
	for order in orders:
		# print(order)
		# print(type(order.id))
		if order.asset_class.value == 'us_option':
			# print(order)
			pickled_instance = pickle.dumps(order)
				
			df.loc[len(df)] = [environment, str(order.id), pickled_instance]

			if order.filled_avg_price:
				amount = float(order.filled_qty) * float(order.filled_avg_price) * 100

				# if order.symbol == 'SMR250711P00036000':
					# print(order)
				if order.side == 'sell':
					# print(order.symbol)
					expires = getExpiration(order.symbol)
					# if order.symbol == 'SNAP251031P00008000':
						# print(order)
						# print(expires)
					testing[order.symbol] = (order.symbol, float(order.filled_qty),  float(order.filled_avg_price), amount, expires, order)
				if order.side == 'buy':
					if order.symbol in testing:
						# get corresponding sell
						symbol, quantity, filled_avg_price, premium, expires, order = testing.pop(order.symbol)
						# print(symbol)
						
						amount = amount * -1
						net = amount + premium
						if net < 0:
							losers += 1
						logger.info(f'Closed {symbol} position for a net amount of {round(amount + premium, 2)}')
						closedTotalPremium += amount + premium
						cnt += 1

	# print(testing)
	# print(len(testing))
	currentDbRecords = OptionsDatabase.getDatabaseRecords(optionsOrdersTable, db=DbVariables.MariaDbOptions)
	alreadyCaptured = currentDbRecords[optionsKeyColumn].unique().tolist()
	# print(alreadyCaptured)
	transDf = df[~df[optionsKeyColumn].isin(alreadyCaptured)]
	# print(transDf)
	if not transDf.empty:
		print(transDf)
		# print(df)
		shouldEmail = True
		OptionsDatabase.insertDatabaseRecords(transDf, optionsOrdersTable, DbVariables.MariaDbOptions)

	now = datetime.now()
	expired = 0
	nonExpiredCnt = 0
	nonExpired = dict()
	expiredPremium = 0
	nonExpiredPremium = 0
	for symbol in testing:
		symbol, quantity, filled_avg_price, premium, expires, order = testing[symbol]
		if expires.date() < now.date():
			expiredPremium += premium
			expired += 1
			logger.info(f'Expired: {symbol} {premium} {expires}')
		else:
			logger.info(f'NOT Expired: {symbol} {premium} {expires}')
			stock = getUnderlyingSymbol(symbol)
			nonExpired[symbol] = stock

			nonExpiredPremium += premium
			nonExpiredCnt += 1

	email_data = list()
	
	logger.info(40 * '-')
	currentPrice = get_underlying_price(nonExpired.values(), stock_data_client)
	for symbol in nonExpired:
		contractType, strike = getSymbolStrikeAndType(symbol)
		breakeven = strike - float(order.filled_avg_price)
		stock = getUnderlyingSymbol(symbol)
		risk = "N"
		breakeven = '0'
		
		if contractType == 'P':
			breakeven = strike - float(order.filled_avg_price)
			
			if currentPrice[stock].price < strike:
				logger.info(f'Put ASSIGNMENT RISK: {symbol}, CurrentPrice = {currentPrice[stock].price} Strike = {strike} Breakeven = {breakeven}')
				risk = "Y"
			else:
				logger.info(f'Put: {symbol}, CurrentPrice = {currentPrice[stock].price} Strike = {strike} Breakeven = {breakeven}')
		if contractType == 'C':
			breakeven = strike + float(order.filled_avg_price)
			if currentPrice[stock].price > strike:
				logger.info(f'Call ASSIGNMENT RISK: {symbol}, CurrentPrice = {currentPrice[stock].price} Strike = {strike} Breakeven = {breakeven}')
				risk = "Y"
			else:
				logger.info(f'Call: {symbol}, CurrentPrice = {currentPrice[stock].price} Strike = {strike}')
				
		rec = {"Symbol": symbol, "Type": contractType, "Price": currentPrice[stock].price, "Strike": strike, 'Breakeven': breakeven, "Risk": risk}
		email_data.append(rec)
		
	api = getPyAlpacaClient(environment)
	assigned = api.trading.account.activities('OPASN')
	
	logger.info(40 * '-')	
	messages = list()
	msg = f'Premium from {cnt} closed option positions: ${closedTotalPremium}'
	messages.append(msg)
	logger.info(msg)
	
	msg = f'Count of losers:  {losers}'
	messages.append(msg)
	logger.info(msg)
	
	msg = f'Count of assignments:  {len(assigned)}'
	messages.append(msg)
	logger.info(msg)	

	msg = f'Premium from {expired} expired options: {expiredPremium}'
	messages.append(msg)
	logger.info(msg)

	msg = f'Premium from {nonExpiredCnt} NonExpired options: ${nonExpiredPremium}'
	messages.append(msg)
	logger.info(msg)
	
	account = api.trading.account.get()
	msg = f"Account Balance: ${account.cash}"
	messages.append(msg)
	logger.info(msg)
	
	msg = f"Buying Power: ${account.buying_power}"
	messages.append(msg)
	logger.info(msg)
	
	msg = f"Options Buying Power: ${account.options_buying_power}"
	messages.append(msg)
	logger.info(msg)	

	df = pd.DataFrame(email_data)
	configs = getConfiguration()
	pwd = decodeEncryptedValue(configs.get("EMAIL_PWD").data, SECURITY_KEY)
	if shouldEmail:
		send_option_positions_email(
			sender_email=configs.get("EMAIL_SENDER").data,
			sender_password=pwd,
			recipient_email=configs.get("EMAIL_SENDER").data,
			df=df, 
			environment=environment,
			messages=messages
		)

def isMarketOpen():
	# returns if market is open and where SYMBOLS should be loaded
	now = datetime.now()
	loadSymbolsFromLocal = False
	marketOpen = market_is_open(now)
	if marketOpen:
		start_time_day = time(9, 30)  # 9:30 AM
		end_time_day = time(16, 0) # 4:00 PM
		opened = is_time_in_range(start_time_day, end_time_day, now.time())
		if not opened:
			marketOpen = False
			
		lastLoadFromCloud = time(10, 0)
		if now.time() > lastLoadFromCloud:
			loadSymbolsFromLocal = True
	return marketOpen, loadSymbolsFromLocal
	
def getTradingSymbols(loadSymbolsFromLocal):
	df = getSymbols(loadSymbolsFromLocal)
	if not loadSymbolsFromLocal:
		syncSymbols(df)
		
	column = symbolColumn.lower()
	if loadSymbolsFromLocal:
		column = symbolColumn
	symbols = df[column].unique().tolist()
	return symbols
		
	
def getExcludedTickersForPut():
	recs = Fire.getCollection()
	excludes = list()
	for rec in recs.get():
		# print(rec.get("tickers"))
		excludes.extend(rec.get("tickers"))
	return excludes

def main():
	args = parse_args()
	
	# Initialize two separate loggers
	strat_logger = getStrategyLogger()  # custom JSON logger used to persist strategy-specific state (e.g. trades, symbols, PnL).
	logger = getLogger() # standard Python logger used for general runtime messages, debugging, and error reporting.

	strat_logger.set_fresh_start(args.fresh_start)
	
	client = AlpacaClientInstance().getClient(BrokerClient, ENVIRONMENT)
	tradingClient = AlpacaClientInstance().getClient(TradingClient, ENVIRONMENT)
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient, ENVIRONMENT)

	portNumber = 7050
	if not IS_PAPER:
		portNumber = 7060
	s = None
	connected = False
	try:    
		s = getSocketPort(portNumber)
		connected = True

		# SYMBOLS_FILE = Path(__file__).parent.parent / "config" / "symbol_list.txt"
		# with open(SYMBOLS_FILE, 'r') as file:
			# SYMBOLS = [line.strip() for line in file.readlines()]
		
		logger.info("Running a paper account? {}".format(IS_PAPER))
		
		logger.info("Received a lock on local port {}".format(portNumber))
		marketOpen, loadSymbolsFromLocal = isMarketOpen()

		if not marketOpen:
			logger.info("Market is not open")
			if IS_TEST:
				logger.info("Running TESTS even though market is not open")
		
		# enabled, target = getRuntimeSettings(ENVIRONMENT)
		sell_put_active, sell_call_active, close_put_active, close_call_active, target, fireSettings = Fire.getRuntimeSettings(ENVIRONMENT)
		enabled = (sell_put_active or sell_call_active or close_put_active or close_call_active)
		if not enabled:
			logger.info(f"NEON Sql flag set to NOT ENABLED for {ENVIRONMENT} environment!!!")
			if not IS_TEST:
				return		
		
		logger.info("Getting symbols")
		SYMBOLS = getTradingSymbols(loadSymbolsFromLocal)
		logger.info("Received {} symbols".format(len(SYMBOLS)))
		
		logger.info(f"NEON Sql flag set to ENABLED for {ENVIRONMENT} environment!!!")
		
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
				
				# Run the close Options logic for positions that are now rollable
				ordersSubmitted = getOrders(ENVIRONMENT, direction='desc')
				
				optionPositions = getCurrentPositions(optionsOnly=True)

				logger.info(f"Target percentage for rolling options for {ENVIRONMENT} environment is {target * 100}%")
				for h in optionPositions:
					try:
						rec = optionPositions[h]
						# print(rec)
						contractType, strike = getSymbolStrikeAndType(rec.symbol)
						pdtCheck = wasTradedToday(rec.symbol, ordersSubmitted)
						if not pdtCheck:
				
							shouldClose = roll_rinse_option(rec, target=target)
							if shouldClose and marketOpen:
								expires = getExpiration(rec.symbol)
								if is_same_day(datetime.now(), expires):
									logger.info(f'{rec.symbol} expires today and we flagged it to close since the premium is low....but we will hold it to close to keep the remainder premium!')
								else:
									logger.info(f'{rec.symbol} expires on {expires}.  Continuing on to closing the position')
									close = False
									
									if contractType == 'P':
										if close_put_active:
											close = True
									if contractType == 'C':
										if close_call_active:
											close = True
									if close:		
										tradingClient.close_position(rec.symbol)
									else:
										logger.info(f'Closing contract type of {contractType} is set to inactive')
						else:
							logger.info(f'Symbol {rec.symbol} cannot be closed since it was already traded today and PDT would be violated!')
					except Exception as re:
						logger.exception(str(re))
						logger.exception(re)

				logger.info("Running sell calls!")
				for symbol, state in states.items():
					if state["type"] == "long_shares":
						if sell_call_active or IS_TEST:
							sell_calls(client, stock_data_client, symbol, state["price"], state["qty"], ownedPositions, strat_logger)

				allowed_symbols = list(set(SYMBOLS).difference(states.keys()))
				# print(allowed_symbols)
				
				buying_power = float(tradingClient.get_account().options_buying_power)
				
				# buying_power = MAX_RISK - current_risk
			
			strat_logger.set_buying_power(buying_power)
			strat_logger.set_allowed_symbols(allowed_symbols)

			reduction = 500
			if 'reserve' in fireSettings.to_dict():
				reduction = fireSettings.get("reserve")
				logger.info(f'Firestore RESERVE is {reduction}')
			buying_power -= reduction
			logger.info(f"Current buying power is ${buying_power}")
						
			ownedPositions = getCurrentPositions(True)
			
			excludedPut = getExcludedTickersForPut()
			logger.info(f'Exluding tickers {excludedPut} from put sales')			
			put_allowed_symbols = list(filter(lambda item: item not in excludedPut, allowed_symbols))
			
			if sell_put_active or IS_TEST:
				sell_puts(client, put_allowed_symbols, buying_power, ownedPositions, strat_logger, fireSettings)

			strat_logger.save() 
			
			checkTrades(ENVIRONMENT)
	
	except Exception as ex:
		logger.exception(str(ex))
		logger.exception(ex)
	finally:
		if connected:			
			s.close()
			logger.info("Released port {}".format(portNumber))



def testSellCall(symbol):
	underlying_trade_request = StockLatestTradeRequest(symbol_or_symbols=symbol)
	
	client = AlpacaClientInstance().getClient(TradingClient, ENVIRONMENT)
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient, ENVIRONMENT)
	
	upperBollinger = getBollingerBands(symbol)
	
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
	client = AlpacaClientInstance().getClient(BrokerClient, ENVIRONMENT)

	stock = owned_option.symbol[0: find_first_non_alpha_loop(owned_option.symbol)[1]]
	
	option_contracts = client.get_options_contracts([stock], 'put')
	for option in option_contracts:
		if option.symbol == owned_option.symbol:
			break
	return option

# calculate the current delta of the option (rolling or rinsing)
def roll_rinse_option(option_data, target=TARGET_CLOSING_PERC, rolling=True):
	logger = getLogger()
	shouldSell = False

	# Get the latest quote for the option price
	option_symbol = option_data.symbol
	option_quote_request = 	OptionLatestQuoteRequest(symbol_or_symbols=option_symbol)
	option_historical_data_client = AlpacaClientInstance().getClient(OptionHistoricalDataClient, ENVIRONMENT)

	option_quote = option_historical_data_client.get_option_latest_quote(option_quote_request)[option_symbol]
	# print(option_quote)
	
	currentOptionContract = getPutOption(option_quote)
	# print(currentOptionContract)

	# Extract option details
	current_option_price = (option_quote.bid_price + option_quote.ask_price) / 2
	strike_price = float(currentOptionContract.strike_price)
	expiry = pd.Timestamp(currentOptionContract.expiration_date)

	logger.info(f"option_symbol is {option_symbol}")
	logger.info(f"current option_price is {current_option_price}")
	logger.info(f"Original option price is {option_data.avg_entry_price}")
	logger.info(f"current strike price is {strike_price}")
	
	remainingPerc = current_option_price / float(option_data.avg_entry_price)
	
	stock_data_client = AlpacaClientInstance().getClient(StockHistoricalDataClient, ENVIRONMENT)
	
	underlying_trade_request = StockLatestTradeRequest(symbol_or_symbols=currentOptionContract.root_symbol)
	underlying_trade_response = stock_data_client.get_stock_latest_trade(underlying_trade_request)
	
	underlying_price = underlying_trade_response[currentOptionContract.root_symbol].price
	logger.info(f"Current price for {currentOptionContract.root_symbol} is {underlying_price}")
	

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
	targetPercentageLeft = target
	target_profit_price = float(option_data.avg_entry_price) * targetPercentageLeft  # x% of credit received
	# print(current_delta)
	# initial_delta = option_data.initial_delta * 2  # Set target delta level at 2x the initial delta of the short put

	# roll or rinse the option if the absoluete value of the current delta is greater than or equal to the initial delta
	# if abs(current_delta) >= abs(initial_delta) or current_option_price <= target_profit_price:

	# targetPercentageLeft = 1-targetPercentageLeft
	
	targetPercent = target
	targetTest = targetPercent * float(option_data.avg_entry_price)
	# if current_option_price <= target_profit_price and abs(current_delta) > .5:
	# if (remainingPerc <= targetPercentageLeft and abs(current_delta) > .5):  #or remainingPerc > 1.0:
	if current_option_price < targetTest: # or abs(current_delta) > .75:
		# Roll or rinse the option
		# rinsing_message, short = roll_rinse_execution(option_data, rolling=rolling)
		shouldSell = True

		# you can add the `rinsing_message` from the `roll_rinse_execution` function below to check if the short put or call is not sccessfully placed
		targetPercentageLeft *= 100
		msg = f"CLOSING!  The option price {current_option_price} for {option_symbol} is less than {targetPercent* 100}% of the initial credit received of {option_data.avg_entry_price}. Delta {current_delta}.  Current {underlying_price}. Remaining {remainingPerc}.  Executing roll/rinse." #, short
		# msg = f"The option price {current_option_price} for {option_symbol} is less than {targetPercentageLeft}% of the initial credit received of {option_data.avg_entry_price}. Executing roll/rinse." #, short
		logger.info(msg)

	else:
		targetPercentageLeft *= 100
		msg = f"The option price for {option_symbol} is greater than {targetPercent* 100}% of the initial credit received. Remaining {remainingPerc}, Original {float(option_data.avg_entry_price)}. Delta {current_delta}. Holding the position.", None
		logger.info(msg)
	return shouldSell

if __name__ == "__main__":
	main()



