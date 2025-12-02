import argparse

# The max dollar risk allowed by the strategy.  
MAX_RISK = 3_000

# The range of allowed Delta (absolute value) when choosing puts or calls to sell.  
# The goal is to balance low assignment risk (lower Delta) with high premiums (higher Delta).
DELTA_MIN = 0.15
DELTA_MAX = 0.25
DELTA_CALL_MAX = 0.3

# The range of allowed yield when choosing puts or calls to sell.
YIELD_MIN = 0.04
YIELD_MAX = 1.00

# The minimum amount of premium we are willing to consider
MINIMUM_PREMIUM = .07

# The range of allowed days till expiry when choosing puts or calls to sell.
# The goal is to balance shorter expiry for consistent income generation with longer expiry for time value premium.
EXPIRATION_MIN = 0
EXPIRATION_MAX = 45

# Only trade contracts with at least this much open interest.
OPEN_INTEREST_MIN = 75

# The minimum score passed to core.strategy.select_options().
SCORE_MIN = 0.05

# The target percentage of remaining premium that remains when we will roll/close the option position
TARGET_CLOSING_PERC = .25


IS_TEST = False

# Create an ArgumentParser object
parser = argparse.ArgumentParser(description="Control if to run tests")

# Add arguments
parser.add_argument("-t", "--test", action="store_true")

# Parse the arguments
known_args, unknown_args = parser.parse_known_args()

# Access the parsed arguments
if known_args.test:
	IS_TEST = True
	print("running TESTS")
	