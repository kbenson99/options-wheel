from dotenv import load_dotenv
from config import *

import argparse

import pandas as pd

ALPACA_API_KEY = None
ALPACA_SECRET_KEY = None
IS_PAPER = True

environment = 'paper'

def getConfiguration(environment):
	df = OptionsDatabase.getDatabaseRecords(optionsConfigurationTable, False, DbVariables.MariaDB)
	filtered_df = df.loc[df[environmentColumn] == environment]	
	return filtered_df

# Create an ArgumentParser object
parser = argparse.ArgumentParser(description="Control if to run test or live")

# Add arguments
parser.add_argument("-l", "--live", action="store_true")

# Parse the arguments
known_args, unknown_args = parser.parse_known_args()

# Access the parsed arguments
if known_args.live:
	environment = 'production'
	IS_PAPER = False
	# dotenv_path = '.env-prod'
	# load_dotenv(dotenv_path=dotenv_path, override=True)
	print("running LIVE")
# else:
	# load_dotenv(override=True)  # Load from .env file in root

configDf = getConfiguration(environment)
ALPACA_API_KEY = configDf[optionsKeyColumn].values[0]
ALPACA_SECRET_KEY = configDf[optionsSecretColumn].values[0]

# ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
# ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
# IS_PAPER = os.getenv("IS_PAPER", "true").lower() == "true"

# print(ALPACA_API_KEY)