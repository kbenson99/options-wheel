import sys
import os

# Get the absolute path to our investment modules
module_path = os.path.abspath('C:/investment/apex') 


# Add the path to sys.path
sys.path.append(module_path)

from database import *

