from enum import Enum

from core.broker_client import BrokerClient
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient, StockLatestTradeRequest
from alpaca.data.historical.option import OptionHistoricalDataClient

from config.credentials import ALPACA_API_KEY, ALPACA_SECRET_KEY, IS_PAPER, getOptionsConfiguration

def _getProductionConfig():
	key, secret = getOptionsConfiguration('production')
	return key, secret

class CLIENT(Enum):
	STOCKDATACLIENT = StockHistoricalDataClient
	TRADINGCLIENT = TradingClient
	BROKERCLIENT = BrokerClient
	OPTIONCLIENT = OptionHistoricalDataClient

class AlpacaClientInstance:
	_instance = None
	clients = dict()

	def __new__(cls, *args, **kwargs):
		if cls._instance is None:
			cls._instance = super().__new__(cls)
		return cls._instance

	# def __init__(self, clienttype):
		# if clienttype not in self.clients:
		# __init__ will be called every time, but on the same instance
		# if not hasattr(self, '_initialized'): # Prevent re-initialization
			
			# self.clients[clienttype] = clienttype(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY)
			# self.stockDataClient = clienttype(api_key=ALPACA_API_KEY, secret_key=ALPACA_SECRET_KEY)
			# self._initialized = True
	def getClient(self, clienttype, environment: str = "paper"):
		IS_PAPER = environment == 'paper'
		key = ALPACA_API_KEY
		secret = ALPACA_SECRET_KEY
		
		if not IS_PAPER:
			key, secret = _getProductionConfig()
		
		if clienttype not in self.clients:
			# clienttype == CLIENT.BROKERCLIENT
			# print(clienttype)
			# print(BrokerClient)

			kwargs = {'api_key': key, 'secret_key': secret}
			if clienttype in [ BrokerClient, TradingClient ]:
				# print(ALPACA_API_KEY)
				# print(ALPACA_SECRET_KEY)
				kwargs['paper'] = IS_PAPER
			self.clients[clienttype] = clienttype(**kwargs)
		return self.clients[clienttype]