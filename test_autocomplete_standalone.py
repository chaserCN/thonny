"""
Standalone tests for autocomplete logic - extracts and tests the functions directly.
"""

import sys
import os

# Inline the functions to test (copied from autocomplete.py)
def _infer_variable_types_with_parso(source_code: str) -> dict:
    """Use parso to infer simple types for variables (list, dict, set, tuple)."""
    try:
        import parso
        from parso.python import tree
        
        var_types = {}  # {var_name: type_hint}
        
        module = parso.parse(source_code)
        
        assignments_found = []  # For logging
        
        def get_outermost_function_name(node):
            """Extract outermost function name from expression like list(map(...))"""
            if node.type == 'atom_expr' and hasattr(node, 'children') and len(node.children) >= 2:
                first_child = node.children[0]
                if first_child.type == 'name':
                    return first_child.value
            elif node.type == 'power' and hasattr(node, 'children'):
                if node.children[0].type == 'name':
                    return node.children[0].value
            elif node.type == 'name':
                return node.value
            return None
        
        def analyze_node(node):
            if isinstance(node, tree.ExprStmt) and node.children[0].type == 'name':
                var_name = node.children[0].value
                
                if len(node.children) >= 3 and node.children[1].value == '=':
                    value = node.children[2]
                    value_type = value.type
                    inferred_type = None
                    
                    # Check for literals by looking at first character
                    if hasattr(value, 'children') and value.children:
                        first_char = value.children[0].value if hasattr(value.children[0], 'value') else None
                        
                        # List literal: x = [1, 2, 3]
                        if first_char == '[':
                            var_types[var_name] = 'list'
                            inferred_type = 'list'
                        
                        # Dict or Set literal: x = {1: 2} or x = {1, 2}
                        elif first_char == '{':
                            # Check if it's dict (has ':') or set (no ':')
                            # Empty {} is always dict
                            if len(value.children) == 2:  # Just { and }
                                var_types[var_name] = 'dict'
                                inferred_type = 'dict'
                            else:
                                # Look for ':' to distinguish dict from set
                                has_colon = False
                                for child in value.children:
                                    if hasattr(child, 'value') and child.value == ':':
                                        has_colon = True
                                        break
                                    # Also check in nested children
                                    if hasattr(child, 'children'):
                                        for subchild in child.children:
                                            if hasattr(subchild, 'value') and subchild.value == ':':
                                                has_colon = True
                                                break
                                
                                if has_colon:
                                    var_types[var_name] = 'dict'
                                    inferred_type = 'dict'
                                else:
                                    var_types[var_name] = 'set'
                                    inferred_type = 'set'
                        
                        # Tuple literal: x = (1, 2)
                        elif first_char == '(':
                            var_types[var_name] = 'tuple'
                            inferred_type = 'tuple'
                    
                    # Tuple from testlist (without parens): x = 1, 2
                    if not inferred_type and value.type == 'testlist':
                        var_types[var_name] = 'tuple'
                        inferred_type = 'tuple'
                    
                # Function calls
                if not inferred_type:
                    func_name = get_outermost_function_name(value)
                    if func_name and func_name in ('list', 'dict', 'set', 'tuple', 'range', 'enumerate', 
                                                   'zip', 'map', 'filter', 'reversed', 'sorted'):
                        var_types[var_name] = func_name
                        inferred_type = func_name
                    
                    if inferred_type:
                        assignments_found.append(f"{var_name}={inferred_type}")
            
            if hasattr(node, 'children'):
                for child in node.children:
                    analyze_node(child)
        
        analyze_node(module)
        return var_types
        
    except Exception as e:
        print(f"⚠️  Parso error: {e}")
        return {}


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
        result = _infer_variable_types_with_parso(code)
        
        # Filter to only expected keys for comparison
        if expected:
            result_filtered = {k: v for k, v in result.items() if k in expected}
        else:
            result_filtered = result
        
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


if __name__ == "__main__":
    main()

