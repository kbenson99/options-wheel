from dotenv import load_dotenv
import os

import argparse

# Create an ArgumentParser object
parser = argparse.ArgumentParser(description="Control if to run test or live")

# Add arguments
parser.add_argument("-l", "--live", action="store_true")

# Parse the arguments
known_args, unknown_args = parser.parse_known_args()

# Access the parsed arguments
if known_args.live:
	dotenv_path = '.env-prod'
	load_dotenv(dotenv_path=dotenv_path, override=True)
	print("running LIVE")
else:
	load_dotenv(override=True)  # Load from .env file in root

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
IS_PAPER = os.getenv("IS_PAPER", "true").lower() == "true"
