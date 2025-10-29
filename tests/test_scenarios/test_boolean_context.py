"""
Test scenarios for BOOLEAN CONTEXT (if, while conditions).

⚠️  IMPORTANT: EXPECTED values are based on ACTUAL algorithm output!
    DO NOT change them to fit the algorithm - that's backwards!
    If algorithm changes, verify the new output is BETTER, then update tests.
"""

# SCENARIO 1: If statement with user functions
# EXPECTED_TOP_10: count, flag, x, y, calculate, is_valid, len, isinstance, any, all
# EXPECTED_NOT_IN_TOP_10: list, dict, tuple
# ⚠️ НЕ ЗМІНЮВАТИ ОЧІКУВАНИЙ РЕЗУЛЬТАТ

def is_valid(value):
    return value > 0

def calculate(a, b):
    return a + b

x = 5
y = 10
count = 0
flag = True
if 📍

# SCENARIO 2: While loop
# EXPECTED_TOP_3: i, max_value, n
# EXPECTED_NOT_IN_TOP_3: range, enumerate, zip

i = 0
n = 100
max_value = 50
while 📍

# SCENARIO 3: Elif statement
# EXPECTED_TOP_3: grade, result, score
# EXPECTED_NOT_IN_TOP_5: class, def, import

score = 85
grade = "B"
result = True
if score > 90:
    print("A")
elif 📍

# SCENARIO 4: And/Or conditions
# EXPECTED_TOP_5: enabled, x, y, z, len
# EXPECTED_NOT_IN_TOP_5: for, while, def

x = 5
y = 10
z = 15
enabled = True
if x > 0 and 📍

