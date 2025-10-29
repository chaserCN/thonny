"""
Test scenarios for EXPRESSIONS (operators, assignments).

⚠️  IMPORTANT: EXPECTED values are based on ACTUAL algorithm output!
    DO NOT change them to fit the algorithm - that's backwards!
    If algorithm changes, verify the new output is BETTER, then update tests.
"""

# SCENARIO 1: After equals
# EXPECTED_TOP_5: x, y, z, input, len
# EXPECTED_NOT_IN_TOP_5: if, for, while, class, print
# NOTE: print демотирован так как возвращает None (бесполезно в присваивании)

x = 5
y = 10
z = 15
result = 📍

# SCENARIO 2: After plus
# EXPECTED_TOP_3: a, b, c
# EXPECTED_NOT_IN_TOP_5: True, False, if, for

a = 100
b = 200
c = 300
total = a +📍 

# SCENARIO 3: List index
# EXPECTED_TOP_3: i, index, j
# EXPECTED_NOT_IN_TOP_5: True, False, None
# NOTE: User vars sorted alphabetically

nums = [1, 2, 3, 4, 5]
i = 0
j = 1
index = 2
nums[📍

