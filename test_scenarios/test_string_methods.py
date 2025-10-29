"""
Test scenarios for STRING METHOD completions (dot access).
"""

# SCENARIO 1: String methods (alphabetical order)
# TEST_POINT: line 11, col 5
# EXPECTED_TOP_5: capitalize, casefold, center, count, encode
# EXPECTED_NOT_IN_TOP_5: len, print, str, list

text = "Hello World"
text.

# SCENARIO 2: List methods (alphabetical order)
# TEST_POINT: line 19, col 5
# EXPECTED_TOP_5: append, clear, copy, count, extend
# EXPECTED_NOT_IN_TOP_5: len, range, list

nums = [1, 2, 3]
nums.

# SCENARIO 3: Dict methods in for loop context (with boost!)
# TEST_POINT: line 28, col 16
# EXPECTED_TOP_3: items, keys, values
# NOTE: items/keys/values получают boost -800 в контексте for..in obj.
# EXPECTED_NOT_IN_TOP_5: get, pop, update

data = {"a": 1, "b": 2}
for key in data.

# SCENARIO 4: Set methods (alphabetical order)
# TEST_POINT: line 35, col 7
# EXPECTED_TOP_5: add, clear, copy, difference, difference_update

unique = {1, 2, 3}
unique.

