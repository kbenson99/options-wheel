import re
import pytz
from datetime import *

def parse_option_symbol(symbol):
    """
    Parses OCC-style option symbol.

    Example:
        'AAPL250516P00207500' -> ('AAPL', 'P', 207.5)
    """
    match = re.match(r'^([A-Za-z]+)(\d{6})([PC])(\d{8})$', symbol)
    
    if match:
        underlying = match.group(1)
        option_type = match.group(3)
        strike_raw = match.group(4)
        strike_price = int(strike_raw) / 1000.0
        return underlying, option_type, strike_price
    else:
        raise ValueError(f"Invalid option symbol format: {symbol}")

def get_ny_timestamp():
    ny_tz = pytz.timezone("America/New_York")
    ny_time = datetime.now(ny_tz)
    return ny_time.isoformat()
	
	
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
	

