#!/usr/bin/env python3
"""Run a single test and output detailed results + compact summary."""

import sys
from pathlib import Path
from test_scenarios_runner import parse_scenario_file, run_scenario_test

def main():
    if len(sys.argv) < 3:
        print("Usage: python run_single_test.py <test_file> <test_number>")
        print("Example: python run_single_test.py test_scenarios/test_for_loops.py 1")
        sys.exit(1)
    
    test_file = sys.argv[1]
    test_num = int(sys.argv[2])
    
    filepath = Path(test_file)
    if not filepath.exists():
        print(f"❌ File not found: {test_file}")
        sys.exit(1)
    
    scenarios = parse_scenario_file(filepath)
    
    if test_num < 1 or test_num > len(scenarios):
        print(f"❌ Test number {test_num} out of range (1-{len(scenarios)})")
        sys.exit(1)
    
    scenario = scenarios[test_num - 1]  # 0-indexed
    
    print(f"\n{'='*80}")
    print(f"🧪 Running TEST {test_num}/{len(scenarios)} from {filepath.name}")
    print(f"{'='*80}\n")
    
    # Run the test (this will print detailed output to console)
    passed = run_scenario_test(scenario)
    
    # Extract compact info for summary file (AFTER test runs!)
    status = "✅ PASSED" if passed else "❌ FAILED"
    
    # Get sorted completions from scenario (populated by run_scenario_test)
    top10 = scenario.get('sorted_labels', [])[:10]
    
    # Get expected values
    expected = []
    if 'expected_top' in scenario:
        expected = scenario['expected_top']
    elif 'expected_first' in scenario:
        expected = scenario['expected_first']
    
    # Write compact summary to file
    summary_file = Path('test_summary.txt')
    with summary_file.open('w') as f:
        f.write(f"{'='*60}\n")
        f.write(f"TEST {test_num}/{len(scenarios)}: {filepath.name}\n")
        f.write(f"{'='*60}\n\n")
        
        f.write(f"Status: {status}\n\n")
        
        # Write the code
        if 'source_code' in scenario:
            f.write(f"Code:\n")
            lines = scenario['source_code'].splitlines()
            cursor_line = scenario.get('actual_line', -1)
            for i, line in enumerate(lines):
                marker = " <-- CURSOR" if i == cursor_line else ""
                f.write(f"  {i+1}: {line}{marker}\n")
            f.write(f"\n")
        
        f.write(f"Expected top-{len(expected)}: {expected}\n")
        f.write(f"Got UI top-10: {top10}\n\n")
        
        if not passed and expected:
            missing = [x for x in expected if x not in top10[:len(expected)]]
            if missing:
                f.write(f"Missing: {missing}\n")
        
        f.write(f"\n{'='*60}\n")
    
    print(f"\n{'='*80}")
    print(f"📄 Summary saved to: {summary_file}")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    main()

