#!/usr/bin/env python3
"""
Run all tests from a single test file and save summary to test_summary.txt

Usage:
    python3 tests/run_file_tests.py tests/test_scenarios/test_boolean_context.py
"""

import sys
from pathlib import Path

# Add parent directory to path to import thonny modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.test_scenarios_runner import parse_scenario_file, run_scenario_test


def run_file_tests(filepath: str):
    """Run all tests from a file and save summary."""
    filepath = Path(filepath)
    
    if not filepath.exists():
        print(f"❌ File not found: {filepath}")
        sys.exit(1)
    
    # Parse all scenarios
    scenarios = parse_scenario_file(filepath)
    
    if not scenarios:
        print(f"❌ No test scenarios found in {filepath}")
        sys.exit(1)
    
    print(f"\n{'='*70}")
    print(f"🧪 Running {len(scenarios)} tests from {filepath.name}")
    print(f"{'='*70}\n")
    
    # Run all tests and collect results
    results = []
    passed = 0
    failed = 0
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"Running TEST {i}/{len(scenarios)}...", end=" ")
        
        # No delay needed - each test gets its own clean workspace
        
        test_passed = run_scenario_test(scenario)
        
        # Extract results
        sorted_labels = scenario.get('sorted_labels', [])
        expected_top = scenario.get('expected_top', [])
        expected_first = scenario.get('expected_first', [])
        
        # Get cursor position from parsed scenario
        source_code = scenario.get('source_code', '')
        cursor_line_in_code = scenario.get('actual_line', 0) + 1  # +1 for human-readable (1-indexed)
        
        result = {
            'test_num': i,
            'passed': test_passed,
            'code': source_code,
            'cursor_line': cursor_line_in_code,
            'cursor_col': scenario.get('col_num', 0),
            'expected': expected_top or expected_first,
            'actual': sorted_labels[:10] if sorted_labels else []
        }
        results.append(result)
        
        if test_passed:
            passed += 1
            print("✅")
        else:
            failed += 1
            print("❌")
    
    # Print summary to console
    print(f"\n{'='*70}")
    print(f"📊 RESULTS: {passed}/{len(scenarios)} passed, {failed}/{len(scenarios)} failed")
    print(f"{'='*70}\n")
    
    # Save summary to file
    with open('test_summary.txt', 'w', encoding='utf-8') as f:
        f.write(f"{'='*70}\n")
        f.write(f"TEST RESULTS: {filepath.name}\n")
        f.write(f"{'='*70}\n")
        f.write(f"Total: {len(scenarios)} tests\n")
        f.write(f"Passed: {passed}\n")
        f.write(f"Failed: {failed}\n")
        f.write(f"{'='*70}\n\n")
        
        # Write individual test results
        for result in results:
            status = "✅ PASSED" if result['passed'] else "❌ FAILED"
            f.write(f"\n{'='*70}\n")
            f.write(f"TEST {result['test_num']}: {status}\n")
            f.write(f"{'='*70}\n\n")
            
            # Code
            f.write("CODE:\n")
            code_lines = result['code'].strip().split('\n')
            for j, line in enumerate(code_lines, 1):
                marker = " <-- CURSOR" if j == result['cursor_line'] else ""
                f.write(f"  {j:3d}: {line}{marker}\n")
            f.write("\n")
            
            # Cursor position (show line in cleaned code, not original file)
            f.write(f"CURSOR: Line {result['cursor_line']}, Column {result['cursor_col']}\n\n")
            
            # Expected
            f.write(f"EXPECTED: {result['expected']}\n\n")
            
            # Actual (top 10)
            f.write(f"GOT (Top-10): {result['actual']}\n\n")
            
            if not result['passed']:
                f.write("❌ Mismatch!\n")
        
        f.write(f"\n{'='*70}\n")
        f.write(f"FINAL: {passed}/{len(scenarios)} passed\n")
        f.write(f"{'='*70}\n")
    
    print(f"📄 Summary saved to: test_summary.txt\n")
    
    # Exit with error code if any tests failed
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 run_file_tests.py <test_file>")
        print("Example: python3 run_file_tests.py test_scenarios/test_boolean_context.py")
        sys.exit(1)
    
    run_file_tests(sys.argv[1])

