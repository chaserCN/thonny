"""
Test scenarios for WITH STATEMENTS (context managers).
"""

# SCENARIO 1: With open( context
# TEST_POINT: line 13, col 10
# EXPECTED_TOP_3: filename, filepath, path
# NOTE: User-defined variables prioritized, then alphabetical

filename = "data.txt"
filepath = "output.txt"
path = "/tmp/file.txt"
with open(

