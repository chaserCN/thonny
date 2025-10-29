"""
Test scenarios for MISCELLANEOUS contexts (return, range/len, f-strings, etc).
"""

# SCENARIO 1: F-string with user variables and calculations
# EXPECTED_TOP_5: attempts, count, result, message, len
# EXPECTED_NOT_IN_TOP_5: print, input, open
# NOTE: user vars sorted alphabetically, then formatting functions

result = 42
attempts = 5
count = 10
message = f"Result: {📍}"

# SCENARIO 2: Return statement in function
# EXPECTED_TOP_5: result, x, y, len, max
# EXPECTED_NOT_IN_TOP_5: print, input, return, if
# NOTE: user vars sorted alphabetically, then functions that return values

def calculate():
    x = 5
    y = 10
    result = x + y
    return 📍

# SCENARIO 3: range(len(...)) pattern
# EXPECTED_FIRST: len
# EXPECTED_TOP_5: len, x, max, min, sum
# EXPECTED_NOT_IN_TOP_5: students
# NOTE: len is top priority, int variables OK, math functions, but list variables should be demoted

students = ["Alice", "Bob", "Charlie"]
x = 5
for i in range(📍

# SCENARIO 4: Function call arguments (print context)
# EXPECTED_TOP_5: message, name, get_name, len, int
# EXPECTED_NOT_IN_TOP_5: input, print, and, for
# NOTE: user vars first (alphabetical), then user functions, then converters (len, int, str), input/print demoted, keywords demoted

def get_name():
    return "John"

name = "Alice"
message = "Hello"
print(📍

# SCENARIO 5: Using UPPER_CASE constants
# EXPECTED_TOP_5: current, value, MAX_VALUE, MIN_VALUE, THRESHOLD
# NOTE: locals first (alphabetical), then CONSTANTS (alphabetical)

MIN_VALUE = 1
MAX_VALUE = 100
THRESHOLD = 50
current = 45
value = 75
if current > 📍

# SCENARIO 6: len() arguments - avoid nested len
# EXPECTED_TOP_5: items, numbers, students, text, max
# EXPECTED_NOT_IN_TOP_5: len, x, y
# NOTE: sequences first (alphabetical), int/float vars should be demoted, then math functions

numbers = [1, 2, 3]
text = "hello"
students = ["A", "B"]
x = 5
y = 3.14
items = range(10)
total = len(📍

# SCENARIO 7: Return with recursion detection
# EXPECTED_TOP_5: n, result, x, len, max
# EXPECTED_NOT_IN_TOP_5: return, if, print, input
# NOTE: function parameters + local vars (alphabetical), then functions that return values

def factorial(n):
    if n <= 1:
        return 1
    result = n * factorial(n - 1)
    x = 10
    return 📍

# SCENARIO 8: After 'and' operator - no keywords
# EXPECTED_TOP_5: is_valid, x, y, len, isinstance
# EXPECTED_NOT_IN_TOP_5: if, for, while, def, return
# NOTE: boolean expressions context, keywords demoted

x = 5
y = 10
is_valid = True
if x > 3 and 📍

# SCENARIO 9: List comprehension filter (if clause)
# EXPECTED_TOP_5: numbers, text, sorted, len, isinstance
# EXPECTED_NOT_IN_TOP_5: print, input, for
# NOTE: boolean context in comprehension, I/O functions demoted
# TODO: Extract comprehension loop vars (x) in Parso

numbers = [1, 2, 3, 4, 5]
text = "hello"
result = [x for x in numbers if 📍]

# SCENARIO 10: Dictionary subscript - LSP returns literal keys
# EXPECTED_TOP_2: "age", "name"
# NOTE: LSP is smart - returns actual dict keys as literals!

data = {"name": "John", "age": 30}
key = "name"
name_key = "name"
age_key = "age"
value = data[📍]

# SCENARIO 11: While condition - boolean context
# EXPECTED_TOP_5: count, is_ready, x, len, isinstance
# EXPECTED_NOT_IN_TOP_5: for, if, while, def, return
# NOTE: boolean context, keywords demoted, isinstance > bool

count = 10
is_ready = True
x = 5
while 📍:
