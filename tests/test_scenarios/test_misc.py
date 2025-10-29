"""
Test scenarios for MISCELLANEOUS contexts (return, range/len, f-strings, etc).
"""

# SCENARIO 1: F-string with user variables and calculations
# TEST_POINT: line 14, col 21
# EXPECTED_TOP_5: attempts, count, result, message, len
# EXPECTED_NOT_IN_TOP_5: print, input, open
# NOTE: user vars sorted alphabetically, then formatting functions

result = 42
attempts = 5
count = 10
message = f"Result: {}"

# SCENARIO 2: Return statement in function
# TEST_POINT: line 24, col 11
# EXPECTED_TOP_5: x, y, result, sum, max
# EXPECTED_NOT_IN_TOP_5: return, if, for, def

def calculate():
    x = 5
    y = 10
    result = x + y
    return 

# SCENARIO 3: range(len(...)) pattern
# TEST_POINT: line 33, col 15
# EXPECTED_FIRST: len
# EXPECTED_TOP_3: len, max, min

students = ["Alice", "Bob", "Charlie"]
numbers = [1, 2, 3, 4, 5]
for i in range(

# SCENARIO 4: Function call arguments (avoid nested same function)
# TEST_POINT: line 45, col 6
# EXPECTED_TOP_5: get_name, name, message, str, len
# EXPECTED_NOT_IN_TOP_5: print

def get_name():
    return "John"

name = "Alice"
message = "Hello"
print(

# SCENARIO 5: Using UPPER_CASE constants
# TEST_POINT: line 58, col 13
# EXPECTED_TOP_5: current, value, MIN_VALUE, MAX_VALUE, THRESHOLD
# NOTE: locals first, then CONSTANTS

MIN_VALUE = 1
MAX_VALUE = 100
THRESHOLD = 50
current = 45
value = 75
if current > 

# SCENARIO 6: len() arguments - avoid nested len
# TEST_POINT: line 68, col 12
# EXPECTED_TOP_5: numbers, text, students, items, str
# EXPECTED_NOT_IN_TOP_5: len

numbers = [1, 2, 3]
text = "hello"
students = ["A", "B"]
items = range(10)
total = len(

# SCENARIO 7: Return with recursion detection
# TEST_POINT: line 82, col 11
# EXPECTED_TOP_5: n, result, x, factorial, abs
# EXPECTED_NOT_IN_TOP_5: return, if
# NOTE: factorial should be lower (recursion), user vars first

def factorial(n):
    if n <= 1:
        return 1
    result = n * factorial(n - 1)
    x = 10
    return 

