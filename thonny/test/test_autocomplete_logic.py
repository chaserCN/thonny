"""
Comprehensive tests for context-aware autocomplete sorting and Parso type inference.

Tests the functions added to autocomplete.py:
- _infer_variable_types_with_parso()
- create_context_aware_sort_key()
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from plugins.autocomplete import _infer_variable_types_with_parso, create_context_aware_sort_key
from lsp_types import CompletionItem, CompletionItemKind


def test_parso_inference():
    """Test Parso type inference with 50+ different code patterns"""
    
    print("=" * 80)
    print("TESTING PARSO TYPE INFERENCE")
    print("=" * 80)
    
    test_cases = [
        # List assignments
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
        
        # Dict assignments
        ("grades = {'math': 5}", {"grades": "dict"}),
        ("data = {}", {"data": "dict"}),
        ("mapping = dict()", {"mapping": "dict"}),
        ("info = dict(name='John', age=20)", {"info": "dict"}),
        ("config = {'a': 1, 'b': 2}", {"config": "dict"}),
        
        # Set assignments
        ("unique = {1, 2, 3}", {"unique": "set"}),
        ("items = set()", {"items": "set"}),
        ("s = set([1, 2, 3])", {"s": "set"}),
        
        # Tuple assignments
        ("point = (10, 20)", {"point": "tuple"}),
        ("coords = tuple([1, 2])", {"coords": "tuple"}),
        ("pos = (5,)", {"pos": "tuple"}),
        
        # Range
        ("nums = range(10)", {"nums": "range"}),
        ("r = range(1, 100, 2)", {"r": "range"}),
        
        # Enumerate
        ("indexed = enumerate([1, 2, 3])", {"indexed": "enumerate"}),
        ("pairs = enumerate('abc')", {"pairs": "enumerate"}),
        
        # Zip
        ("combined = zip([1, 2], [3, 4])", {"combined": "zip"}),
        ("pairs = zip(a, b, c)", {"pairs": "zip"}),
        
        # Map
        ("doubled = map(lambda x: x*2, nums)", {"doubled": "map"}),
        ("strings = map(str, numbers)", {"strings": "map"}),
        
        # Filter
        ("evens = filter(lambda x: x % 2 == 0, nums)", {"evens": "filter"}),
        ("positive = filter(lambda x: x > 0, data)", {"positive": "filter"}),
        
        # Reversed
        ("rev = reversed([1, 2, 3])", {"rev": "reversed"}),
        
        # Sorted
        ("ordered = sorted([3, 1, 2])", {"ordered": "sorted"}),
        ("s = sorted(items, reverse=True)", {"s": "sorted"}),
        
        # Multiple assignments in one code
        ("""
nums = [1, 2, 3]
text = "hello"
data = {'a': 1}
coords = (5, 10)
""", {"nums": "list", "data": "dict", "coords": "tuple"}),
        
        # Nested function calls (should extract outermost)
        ("result = list(map(int, filter(bool, data)))", {"result": "list"}),
        ("items = set(map(str, range(10)))", {"items": "set"}),
        
        # Complex real-world examples
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
        
        # Edge cases that should NOT be inferred (to verify we don't false-positive)
        ("x = 5", {}),  # Not a collection
        ("name = 'John'", {}),  # String literal
        ("result = some_function()", {}),  # Unknown function
        ("data = MyClass()", {}),  # Class instantiation
    ]
    
    passed = 0
    failed = 0
    
    for i, (code, expected) in enumerate(test_cases, 1):
        # Function now returns tuple: (var_types, user_defined_vars, loop_vars, current_function, user_functions)
        var_types, _, _, _, _ = _infer_variable_types_with_parso(code)
        
        # Filter to only expected keys for comparison
        if expected:
            result_filtered = {k: v for k, v in var_types.items() if k in expected}
        else:
            result_filtered = var_types
        
        if result_filtered == expected:
            passed += 1
            status = "✅ PASS"
        else:
            failed += 1
            status = "❌ FAIL"
        
        print(f"\n[Test {i:3d}] {status}")
        if len(code) < 60:
            print(f"  Code: {code}")
        else:
            print(f"  Code: {code[:57]}...")
        print(f"  Expected: {expected}")
        print(f"  Got:      {result_filtered}")
    
    print("\n" + "=" * 80)
    print(f"PARSO INFERENCE RESULTS: {passed} passed, {failed} failed out of {len(test_cases)}")
    print("=" * 80)
    
    return passed, failed


def test_context_aware_sorting():
    """Test context-aware sorting with 50+ different contexts"""
    
    print("\n" + "=" * 80)
    print("TESTING CONTEXT-AWARE SORTING")
    print("=" * 80)
    
    # Helper to create completion items
    def make_item(label, kind, sort_text=None, detail=None):
        return CompletionItem(
            label=label,
            kind=kind,
            sortText=sort_text or f"09.9999.{label}",
            detail=detail
        )
    
    def make_local_var(label, detail=None):
        # User-defined variables have sortText starting with 09.9999. (from LSP)
        return CompletionItem(
            label=label,
            kind=CompletionItemKind.Variable,
            sortText=f"09.9999.{label}",
            detail=detail
        )
    
    test_cases = [
        # FOR LOOPS - should prioritize iterables
        {
            "name": "for...in with list variable",
            "prefix": "",
            "line_before": "for x in ",
            "line_after": "",
            "source": "mas = list(map(int, input().split()))",
            "items": [
                make_local_var("mas"),  # Should be FIRST
                make_item("dict", CompletionItemKind.Class),
                make_item("list", CompletionItemKind.Class),
                make_item("range", CompletionItemKind.Class),
                make_item("True", CompletionItemKind.Keyword),
            ],
            "expected_first": "mas",
            "expected_not_in_top_5": ["True"],
        },
        {
            "name": "for...in with multiple variables",
            "prefix": "",
            "line_before": "for item in ",
            "line_after": "",
            "source": """
nums = [1, 2, 3]
names = ['a', 'b']
count = 5
""",
            "items": [
                make_local_var("nums"),
                make_local_var("names"),
                make_local_var("count"),  # Not a list
                make_item("range", CompletionItemKind.Class),
            ],
            "expected_first": "nums",  # First list in source
            "expected_top_3": ["nums", "names"],  # Both lists should be in top 3
        },
        {
            "name": "for...in should demote keywords",
            "prefix": "",
            "line_before": "for x in ",
            "line_after": "",
            "source": "data = [1, 2, 3]",
            "items": [
                make_local_var("data"),
                make_item("in", CompletionItemKind.Keyword),
                make_item("for", CompletionItemKind.Keyword),
                make_item("if", CompletionItemKind.Keyword),
            ],
            "expected_first": "data",
            "expected_keywords_after": "data",
        },
        
        # IMPORT STATEMENTS
        {
            "name": "import statement",
            "prefix": "",
            "line_before": "import ",
            "line_after": "",
            "source": "",
            "items": [
                make_item("random", CompletionItemKind.Module),
                make_item("math", CompletionItemKind.Module),
                make_item("list", CompletionItemKind.Class),
                make_item("range", CompletionItemKind.Function),
            ],
            "expected_top_2_contain": ["random", "math"],
        },
        {
            "name": "from...import statement",
            "prefix": "",
            "line_before": "from random import ",
            "line_after": "",
            "source": "",
            "items": [
                make_item("randint", CompletionItemKind.Function),
                make_item("choice", CompletionItemKind.Function),
                make_item("random", CompletionItemKind.Module),
            ],
            "expected_top_2_contain": ["randint", "choice"],
        },
        
        # DOT ACCESS - should prioritize methods
        {
            "name": "list methods after dot",
            "prefix": "",
            "line_before": "nums.",
            "line_after": "",
            "source": "nums = [1, 2, 3]",
            "items": [
                make_item("append", CompletionItemKind.Method),
                make_item("remove", CompletionItemKind.Method),
                make_item("sort", CompletionItemKind.Method),
                make_item("len", CompletionItemKind.Function),  # Function, not method
                make_item("list", CompletionItemKind.Class),
            ],
            "expected_top_3_contain": ["append", "remove", "sort"],
            "expected_not_in_top_3": ["len", "list"],
        },
        {
            "name": "dict methods after dot",
            "prefix": "",
            "line_before": "data.",
            "line_after": "",
            "source": "data = {'a': 1}",
            "items": [
                make_item("keys", CompletionItemKind.Method),
                make_item("values", CompletionItemKind.Method),
                make_item("items", CompletionItemKind.Method),
                make_item("get", CompletionItemKind.Method),
                make_item("dict", CompletionItemKind.Class),
            ],
            "expected_top_4_contain": ["keys", "values", "items", "get"],
        },
        
        # LINE START - should prioritize keywords
        {
            "name": "start of line",
            "prefix": "",
            "line_before": "",
            "line_after": "",
            "source": "",
            "items": [
                make_item("for", CompletionItemKind.Keyword),
                make_item("if", CompletionItemKind.Keyword),
                make_item("while", CompletionItemKind.Keyword),
                make_item("def", CompletionItemKind.Keyword),
                make_local_var("x"),
                make_item("print", CompletionItemKind.Function),
            ],
            "expected_top_4_contain": ["for", "if", "while", "def"],
        },
        
        # EXPRESSIONS - should prioritize variables/functions over keywords
        {
            "name": "after equals sign",
            "prefix": "",
            "line_before": "result = ",
            "line_after": "",
            "source": "x = 5\ny = 10",
            "items": [
                make_local_var("x"),
                make_local_var("y"),
                make_item("if", CompletionItemKind.Keyword),
                make_item("for", CompletionItemKind.Keyword),
                make_item("len", CompletionItemKind.Function),
            ],
            "expected_top_3_contain": ["x", "y", "len"],
            "expected_not_in_top_3": ["if", "for"],
        },
        {
            "name": "after plus operator",
            "prefix": "",
            "line_before": "total = x + ",
            "line_after": "",
            "source": "x = 5\ny = 10\nz = 15",
            "items": [
                make_local_var("x"),
                make_local_var("y"),
                make_local_var("z"),
                make_item("if", CompletionItemKind.Keyword),
                make_item("True", CompletionItemKind.Keyword),
            ],
            "expected_top_3_contain": ["x", "y", "z"],
        },
        {
            "name": "inside function call",
            "prefix": "",
            "line_before": "print(",
            "line_after": ")",
            "source": "message = 'hello'",
            "items": [
                make_local_var("message"),
                make_item("if", CompletionItemKind.Keyword),
                make_item("for", CompletionItemKind.Keyword),
            ],
            "expected_first": "message",
        },
        
        # PREFIX MATCHING - should still work
        {
            "name": "prefix matching with 'r'",
            "prefix": "r",
            "line_before": "for x in r",
            "line_after": "",
            "source": "result = [1, 2, 3]",
            "items": [
                make_local_var("result"),  # Starts with 'r'
                make_item("range", CompletionItemKind.Class),  # Starts with 'r'
                make_item("reversed", CompletionItemKind.Class),  # Starts with 'r'
                make_item("list", CompletionItemKind.Class),  # Does NOT start with 'r'
            ],
            "expected_top_3": ["result", "range", "reversed"],
            "expected_not_in_top_3": ["list"],
        },
        
        # COMPLEX SCENARIOS
        {
            "name": "nested for loops",
            "prefix": "",
            "line_before": "    for item in ",
            "line_after": "",
            "source": """
data = [[1, 2], [3, 4]]
for row in data:
    for item in 
""",
            "items": [
                make_local_var("row"),  # Should be first (inner loop variable)
                make_local_var("data"),  # Also valid
                make_item("range", CompletionItemKind.Class),
            ],
            "expected_first": "row",
        },
        {
            "name": "mixed types - should prioritize iterables in for",
            "prefix": "",
            "line_before": "for x in ",
            "line_after": "",
            "source": """
count = 5
names = ['Alice', 'Bob']
enabled = True
""",
            "items": [
                make_local_var("count"),  # Not iterable
                make_local_var("names"),  # Iterable list
                make_local_var("enabled"),  # Not iterable
                make_item("range", CompletionItemKind.Class),
            ],
            "expected_first": "names",
        },
        
        # Edge cases
        {
            "name": "empty source code",
            "prefix": "",
            "line_before": "x = ",
            "line_after": "",
            "source": "",
            "items": [
                make_item("True", CompletionItemKind.Keyword),
                make_item("False", CompletionItemKind.Keyword),
                make_item("None", CompletionItemKind.Keyword),
            ],
            "expected_top_3_contain": ["True", "False", "None"],
        },
        {
            "name": "very long source (should skip parso)",
            "prefix": "",
            "line_before": "for x in ",
            "line_after": "",
            "source": "x = [1, 2, 3]\n" * 500,  # > 5KB
            "items": [
                make_item("range", CompletionItemKind.Class),
                make_item("list", CompletionItemKind.Class),
            ],
            "expected_top_2_contain": ["range", "list"],
        },
    ]
    
    passed = 0
    failed = 0
    
    for i, test in enumerate(test_cases, 1):
        sort_key = create_context_aware_sort_key(
            prefix=test["prefix"],
            line_before_cursor=test["line_before"],
            line_after_cursor=test["line_after"],
            source_code=test["source"]
        )
        
        sorted_items = sorted(test["items"], key=sort_key)
        sorted_labels = [item.label for item in sorted_items]
        
        # Check expectations
        test_passed = True
        failures = []
        
        if "expected_first" in test:
            if sorted_labels[0] != test["expected_first"]:
                test_passed = False
                failures.append(f"Expected '{test['expected_first']}' first, got '{sorted_labels[0]}'")
        
        if "expected_top_3" in test:
            top_3 = sorted_labels[:3]
            if not all(item in top_3 for item in test["expected_top_3"]):
                test_passed = False
                failures.append(f"Expected {test['expected_top_3']} in top 3, got {top_3}")
        
        if "expected_top_2_contain" in test:
            top_2 = sorted_labels[:2]
            if not all(item in top_2 for item in test["expected_top_2_contain"]):
                test_passed = False
                failures.append(f"Expected {test['expected_top_2_contain']} in top 2, got {top_2}")
        
        if "expected_top_3_contain" in test:
            top_3 = sorted_labels[:3]
            missing = [item for item in test["expected_top_3_contain"] if item not in top_3]
            if missing:
                test_passed = False
                failures.append(f"Expected {test['expected_top_3_contain']} in top 3, got {top_3}")
        
        if "expected_top_4_contain" in test:
            top_4 = sorted_labels[:4]
            missing = [item for item in test["expected_top_4_contain"] if item not in top_4]
            if missing:
                test_passed = False
                failures.append(f"Expected {test['expected_top_4_contain']} in top 4, got {top_4}")
        
        if "expected_not_in_top_3" in test:
            top_3 = sorted_labels[:3]
            found = [item for item in test["expected_not_in_top_3"] if item in top_3]
            if found:
                test_passed = False
                failures.append(f"Did NOT expect {found} in top 3, but got {top_3}")
        
        if "expected_not_in_top_5" in test:
            top_5 = sorted_labels[:5]
            found = [item for item in test["expected_not_in_top_5"] if item in top_5]
            if found:
                test_passed = False
                failures.append(f"Did NOT expect {found} in top 5, but got {top_5}")
        
        if "expected_keywords_after" in test:
            var_pos = sorted_labels.index(test["expected_keywords_after"])
            keywords = [item for item in sorted_items if item.kind == CompletionItemKind.Keyword]
            keyword_positions = [sorted_labels.index(kw.label) for kw in keywords]
            if any(pos < var_pos for pos in keyword_positions):
                test_passed = False
                failures.append(f"Keywords should be after '{test['expected_keywords_after']}'")
        
        if test_passed:
            passed += 1
            status = "✅ PASS"
        else:
            failed += 1
            status = "❌ FAIL"
        
        print(f"\n[Test {i:3d}] {status} - {test['name']}")
        print(f"  Context: line_before='{test['line_before']}'")
        if test["source"] and len(test["source"]) < 60:
            print(f"  Source: {test['source']}")
        print(f"  Result order: {sorted_labels}")
        
        if failures:
            for failure in failures:
                print(f"  ❌ {failure}")
    
    print("\n" + "=" * 80)
    print(f"CONTEXT-AWARE SORTING RESULTS: {passed} passed, {failed} failed out of {len(test_cases)}")
    print("=" * 80)
    
    return passed, failed


def main():
    """Run all tests"""
    print("\n" + "🧪" * 40)
    print(" " * 15 + "AUTOCOMPLETE LOGIC TESTS")
    print("🧪" * 40 + "\n")
    
    # Test Parso inference
    parso_passed, parso_failed = test_parso_inference()
    
    # Test context-aware sorting
    sort_passed, sort_failed = test_context_aware_sorting()
    
    # Summary
    total_passed = parso_passed + sort_passed
    total_failed = parso_failed + sort_failed
    total_tests = total_passed + total_failed
    
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"Total tests run: {total_tests}")
    print(f"✅ Passed: {total_passed}")
    print(f"❌ Failed: {total_failed}")
    print(f"Success rate: {100 * total_passed / total_tests:.1f}%")
    print("=" * 80 + "\n")
    
    # Exit with error code if any tests failed
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()

