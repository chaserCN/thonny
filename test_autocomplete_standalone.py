"""
Standalone tests for autocomplete logic - imports and tests production functions.
"""

import sys
import os
from pathlib import Path

# Add thonny to path
sys.path.insert(0, str(Path(__file__).parent))

# Import production code to test
from thonny.plugins.autocomplete import _infer_variable_types_with_parso

# OLD INLINE CODE REMOVED - now using production code from autocomplete.py!


def test_parso_inference():
    """Test Parso type inference with 50+ different code patterns"""
    
    print("=" * 80)
    print("TESTING PARSO TYPE INFERENCE")
    print("=" * 80)
    
    test_cases = [
        # List assignments (15 tests)
        ("nums = [1, 2, 3]", {"nums": "list"}),
        ("data = []", {"data": "list"}),
        ("items = [x for x in range(10)]", {"items": "list"}),
        ("values = list()", {"values": "list"}),
        ("mas = list(map(int, input().split()))", {"mas": "list"}),
        ("result = list(range(5))", {"result": "list"}),
        ("words = list('abc')", {"words": "list"}),
        ("filtered = list(filter(lambda x: x > 0, nums))", {"filtered": "list"}),
        ("mapped = list(map(str, nums))", {"mapped": "list"}),
        ("numbers = [1, 2, 3, 4, 5]", {"numbers": "list"}),
        ("empty = []", {"empty": "list"}),
        ("nested = [[1, 2], [3, 4]]", {"nested": "list"}),
        ("mixed = [1, 'a', True]", {"mixed": "list"}),
        ("comprehension = [i*2 for i in range(5)]", {"comprehension": "list"}),
        ("from_tuple = list((1, 2, 3))", {"from_tuple": "list"}),
        
        # Dict assignments (10 tests)
        ("grades = {'math': 5}", {"grades": "dict"}),
        ("data = {}", {"data": "dict"}),
        ("mapping = dict()", {"mapping": "dict"}),
        ("info = dict(name='John', age=20)", {"info": "dict"}),
        ("config = {'a': 1, 'b': 2}", {"config": "dict"}),
        ("nested_dict = {'key': {'inner': 1}}", {"nested_dict": "dict"}),
        ("mixed_keys = {1: 'one', 'two': 2}", {"mixed_keys": "dict"}),
        ("from_pairs = dict([('a', 1), ('b', 2)])", {"from_pairs": "dict"}),
        ("with_numbers = {1: 100, 2: 200}", {"with_numbers": "dict"}),
        ("empty_dict = {}", {"empty_dict": "dict"}),
        
        # Set assignments (6 tests)
        ("unique = {1, 2, 3}", {"unique": "set"}),
        ("items = set()", {"items": "set"}),
        ("s = set([1, 2, 3])", {"s": "set"}),
        ("from_str = set('abc')", {"from_str": "set"}),
        ("uniq_nums = {1, 1, 2, 2, 3}", {"uniq_nums": "set"}),
        ("empty_set = set()", {"empty_set": "set"}),
        
        # Tuple assignments (6 tests)
        ("point = (10, 20)", {"point": "tuple"}),
        ("coords = tuple([1, 2])", {"coords": "tuple"}),
        ("pos = (5,)", {"pos": "tuple"}),
        ("triple = (1, 2, 3)", {"triple": "tuple"}),
        ("from_list = tuple([4, 5, 6])", {"from_list": "tuple"}),
        ("mixed_tuple = (1, 'a', True)", {"mixed_tuple": "tuple"}),
        
        # Range (4 tests)
        ("nums = range(10)", {"nums": "range"}),
        ("r = range(1, 100, 2)", {"r": "range"}),
        ("backwards = range(10, 0, -1)", {"backwards": "range"}),
        ("one_to_five = range(1, 6)", {"one_to_five": "range"}),
        
        # Enumerate (3 tests)
        ("indexed = enumerate([1, 2, 3])", {"indexed": "enumerate"}),
        ("pairs = enumerate('abc')", {"pairs": "enumerate"}),
        ("with_start = enumerate(items, start=1)", {"with_start": "enumerate"}),
        
        # Zip (4 tests)
        ("combined = zip([1, 2], [3, 4])", {"combined": "zip"}),
        ("pairs = zip(a, b, c)", {"pairs": "zip"}),
        ("three_lists = zip(x, y, z)", {"three_lists": "zip"}),
        ("zipped = zip(names, ages)", {"zipped": "zip"}),
        
        # Map (4 tests)
        ("doubled = map(lambda x: x*2, nums)", {"doubled": "map"}),
        ("strings = map(str, numbers)", {"strings": "map"}),
        ("squared = map(lambda n: n**2, data)", {"squared": "map"}),
        ("upper = map(str.upper, words)", {"upper": "map"}),
        
        # Filter (4 tests)
        ("evens = filter(lambda x: x % 2 == 0, nums)", {"evens": "filter"}),
        ("positive = filter(lambda x: x > 0, data)", {"positive": "filter"}),
        ("non_empty = filter(bool, items)", {"non_empty": "filter"}),
        ("adults = filter(lambda p: p.age >= 18, people)", {"adults": "filter"}),
        
        # Reversed (3 tests)
        ("rev = reversed([1, 2, 3])", {"rev": "reversed"}),
        ("back = reversed(nums)", {"back": "reversed"}),
        ("reverse_str = reversed('hello')", {"reverse_str": "reversed"}),
        
        # Sorted (4 tests)
        ("ordered = sorted([3, 1, 2])", {"ordered": "sorted"}),
        ("s = sorted(items, reverse=True)", {"s": "sorted"}),
        ("by_key = sorted(data, key=lambda x: x.value)", {"by_key": "sorted"}),
        ("alphabetical = sorted(names)", {"alphabetical": "sorted"}),
        
        # Multiple assignments (5 tests)
        ("nums = [1, 2, 3]\ntext = 'hello'\ndata = {'a': 1}", 
         {"nums": "list", "data": "dict"}),
        
        ("a = []\nb = {}\nc = ()", 
         {"a": "list", "b": "dict", "c": "tuple"}),
        
        ("items = range(10)\nfiltered = filter(bool, items)", 
         {"items": "range", "filtered": "filter"}),
        
        ("x = list([1, 2])\ny = set([3, 4])\nz = dict(a=1)", 
         {"x": "list", "y": "set", "z": "dict"}),
        
        ("data = [1, 2, 3]\nsquared = map(lambda x: x**2, data)\nevens = list(filter(lambda x: x % 2 == 0, squared))", 
         {"data": "list", "squared": "map", "evens": "list"}),
        
        # Nested function calls (5 tests)
        ("result = list(map(int, filter(bool, data)))", {"result": "list"}),
        ("items = set(map(str, range(10)))", {"items": "set"}),
        ("pairs = list(zip(a, b))", {"pairs": "list"}),
        ("unique = set(filter(lambda x: x > 0, nums))", {"unique": "set"}),
        ("sorted_list = list(sorted(items, reverse=True))", {"sorted_list": "list"}),
        
        # Complex real-world examples (5 tests)
        ("""
import random
mas = list(map(int, input("=").split()))
x = random.randint(1, 5)
filtered = list(filter(lambda n: n > x, mas))
""", {"mas": "list", "filtered": "list"}),
        
        ("""
numbers = [1, 2, 3, 4, 5]
squared = list(map(lambda x: x**2, numbers))
evens = list(filter(lambda x: x % 2 == 0, squared))
""", {"numbers": "list", "squared": "list", "evens": "list"}),
        
        ("""
names = ['Alice', 'Bob', 'Charlie']
ages = [25, 30, 35]
people = list(zip(names, ages))
adults = list(filter(lambda p: p[1] >= 18, people))
""", {"names": "list", "ages": "list", "people": "list", "adults": "list"}),
        
        ("""
data = [5, 2, 8, 1, 9]
sorted_data = sorted(data)
reversed_data = list(reversed(sorted_data))
""", {"data": "list", "sorted_data": "sorted", "reversed_data": "list"}),
        
        ("""
coords = [(1, 2), (3, 4), (5, 6)]
x_coords = list(map(lambda p: p[0], coords))
y_coords = list(map(lambda p: p[1], coords))
""", {"coords": "list", "x_coords": "list", "y_coords": "list"}),
        
        # Edge cases that should NOT be inferred (10 tests)
        ("x = 5", {}),
        ("name = 'John'", {}),
        ("result = some_function()", {}),
        ("data = MyClass()", {}),
        ("value = x + y", {}),
        ("total = sum(nums)", {}),
        ("length = len(items)", {}),
        ("text = str(number)", {}),
        ("flag = bool(value)", {}),
        ("num = int('42')", {}),
    ]
    
    passed = 0
    failed = 0
    
    for i, (code, expected) in enumerate(test_cases, 1):
        # Production function now returns (var_types, user_defined_vars)
        var_types, user_defined_vars = _infer_variable_types_with_parso(code)
        
        # Filter to only expected keys for comparison
        if expected:
            result_filtered = {k: v for k, v in var_types.items() if k in expected}
        else:
            result_filtered = var_types
        
        if result_filtered == expected:
            passed += 1
            status = "✅"
        else:
            failed += 1
            status = "❌"
        
        if status == "❌":  # Only print failures
            print(f"\n[Test {i:3d}] {status}")
            if len(code) < 60:
                print(f"  Code: {code}")
            else:
                print(f"  Code: {code[:57]}...")
            print(f"  Expected: {expected}")
            print(f"  Got:      {result_filtered}")
    
    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(test_cases)}")
    if passed == len(test_cases):
        print("🎉 ALL TESTS PASSED!")
    print("=" * 80)
    
    return passed, failed


def main():
    """Run all tests"""
    print("\n" + "🧪" * 40)
    print(" " * 10 + "PARSO TYPE INFERENCE TESTS (100+ cases)")
    print("🧪" * 40 + "\n")
    
    # Test Parso inference
    parso_passed, parso_failed = test_parso_inference()
    
    # Exit with error code if any tests failed
    sys.exit(0 if parso_failed == 0 else 1)


def test_parso_latest_assignment_wins():
    """Test that latest assignment wins (e.g., x=int then x=list)"""
    print("\n" + "="*60)
    print("Testing Parso: Latest Assignment Wins")
    print("="*60)
    
    tests = [
        # Latest assignment wins
        ("x = 5\nx = [1, 2, 3]", {'x': 'list'}),
        ("x = []\nx = dict()", {'x': 'dict'}),
        ("x = {}\nx = (1, 2)", {'x': 'tuple'}),
        
        # With function scope (global x shadowed) - Parso takes LATEST
        ("x = 5\ndef foo():\n    x = [1, 2, 3]", {'x': 'list'}),  # Latest x is list
    ]
    
    passed = 0
    failed = 0
    
    for i, (code, expected) in enumerate(tests, 1):
        result = _infer_variable_types_with_parso(code)
        # Handle both old (dict only) and new (tuple) return formats
        var_types = result[0] if isinstance(result, tuple) else result
        
        # Only check variables that we expect to have types
        success = True
        for var, expected_type in expected.items():
            if var_types.get(var) != expected_type:
                success = False
                print(f"❌ Test {i} FAILED:")
                print(f"   Code: {code[:50]!r}...")
                print(f"   Expected: {expected}")
                print(f"   Got: {var_types}")
                failed += 1
                break
        
        if success:
            passed += 1
            print(f"✓ Test {i}")
    
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed == 0:
        print("✅ All tests PASSED!")
    else:
        print(f"❌ {failed} tests FAILED")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    test_parso_latest_assignment_wins()
    main()

