"""
Test scenarios for FOR LOOP completions.
Each marker indicates where to test autocomplete and what to expect.
"""

# SCENARIO 1: Simple list variable
# EXPECTED_TOP_6: mas, nums, range, sorted, enumerate, reversed
# EXPECTED_NOT_IN_TOP_6: True, False, if, class, def, x

mas = [1, 2, 3]
nums = [4, 5, 6]
y = 5
for x in 📍

# SCENARIO 2: List from map/filter
# EXPECTED_FIRST: filtered
# EXPECTED_TOP_6: filtered, mas, range, sorted, enumerate, reversed

mas = list(map(int, input().split()))
filtered = list(filter(lambda x: x > 0, mas))
for item in 📍

# SCENARIO 3: Multiple iterables
# EXPECTED_TOP_8: ages, coords, names, numbers, range, sorted, enumerate, reversed
# EXPECTED_NOT_IN_TOP_8: count, True, False

names = ["Alice", "Bob"]
ages = [25, 30]
coords = [(1, 2), (3, 4)]
numbers = range(10)
count = 5  # not iterable
for x in 📍

# SCENARIO 4: Dict iteration (methods)
# EXPECTED_TOP_3: items, keys, values
# EXPECTED_NOT_IN_TOP_3: get, pop, update

data = {"name": "John", "age": 25}
for key in data.📍

# SCENARIO 5: Nested for loops
# EXPECTED_FIRST: row
# EXPECTED_TOP_3: row, matrix, range

matrix = [[1, 2], [3, 4], [5, 6]]
for row in matrix:
    for item in 📍

# SCENARIO 6: String iteration  
# EXPECTED_TOP_3: names, text, words
# NOTE: All three variables are iterable (lists and str), alphabetically sorted

text = "Hello World"
words = ["one", "two"]
names = ["Alice", "Bob"]
for char in 📍

# SCENARIO 7: User-defined functions that return iterables  
# EXPECTED_TOP_6: nums, range, get_data, get_numbers, sorted, enumerate
# EXPECTED_NOT_IN_TOP_6: x
# NOTE: user vars (lists) highest, then range, then user funcs, then built-in iterators. Non-iterable vars (x=5) demoted.

def get_numbers():
    return [1, 2, 3, 4, 5]

def get_data():
    return {"key": "value"}

nums = [10, 20, 30]
x = 5
for item in 📍

