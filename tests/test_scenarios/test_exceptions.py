"""
Test scenarios for EXCEPTION HANDLING (try/except).
"""

# SCENARIO 1: Exception with prefix (typing)
# EXPECTED_TOP_3: ValueError (typing "V" should filter)
# EXPECTED_NOT_IN_TOP_5: TypeError, KeyError, Exception

try:
    data = {"key": "value"}
    result = data["key"]
except V📍

