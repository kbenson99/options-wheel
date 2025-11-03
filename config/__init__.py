import sys
import os

# Get the absolute path to our investment modules
# module_path = os.path.abspath('C:/investment/apex') 

module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'apex'))

# Add the module_path to sys.path
sys.path.append(module_path)

# Get the absolute path to the directory containing your package
# For example, if your package is in 'parent_directory/my_package'
# and your current script is in 'current_directory', you might do:
package_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add the directory to sys.path
sys.path.append(package_dir)
# sys.path.insert(0, package_dir) # Insert at the beginning for higher priority
# print(sys.path)

from database import *

