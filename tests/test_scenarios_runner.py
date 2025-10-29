#!/usr/bin/env python3
"""
Automatic test runner for test_scenarios/*.py files.
Parses TEST_POINT markers and validates autocomplete behavior.
Uses REAL LSP completions from Pyright.
"""

import os
import re
import sys
import logging
from pathlib import Path

# Configure logging to show all info messages
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stdout
)

# Add thonny to path
sys.path.insert(0, str(Path(__file__).parent))

from thonny.plugins.autocomplete import (
    create_context_aware_sort_key, 
    _infer_variable_types_with_parso,
    filter_garbage_completions
)
from thonny import lsp_types

# Import LSP client
from simple_lsp_client import get_completions_from_pyright


def parse_scenario_file(filepath):
    """
    Parse a scenario file and extract test cases.
    
    Returns list of dicts with:
    - scenario_name: str
    - line_num: int (0-based line where cursor should be)
    - col_num: int
    - source_code: str (full code up to test point)
    - expected_top: list of str (expected items in top N)
    - expected_not_in_top: list of str (items that should NOT be in top N)
    """
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    scenarios = []
    current_scenario = {}
    
    for i, line in enumerate(lines):
        # Match SCENARIO comment
        if line.strip().startswith("# SCENARIO"):
            if current_scenario:
                scenarios.append(current_scenario)
            current_scenario = {
                'scenario_name': line.strip(),
                'filepath': filepath,
            }
        
        # Match TEST_POINT comment
        elif "# TEST_POINT:" in line and current_scenario:
            # Extract line and col numbers
            match = re.search(r'line\s+(\d+),\s+col\s+(\d+)', line)
            if match:
                test_line = int(match.group(1)) - 1  # Convert to 0-based
                test_col = int(match.group(2))
                current_scenario['line_num'] = test_line
                current_scenario['col_num'] = test_col
        
        # Match EXPECTED_FIRST
        elif "# EXPECTED_FIRST:" in line and current_scenario:
            items = line.split(":", 1)[1].strip().split(",")
            # Clean up items - remove explanations in parentheses
            current_scenario['expected_first'] = [re.sub(r'\s*\(.*?\)', '', item.strip()) for item in items]
        
        # Match EXPECTED_TOP_N
        elif re.search(r'# EXPECTED_TOP_\d+:', line) and current_scenario:
            items = line.split(":", 1)[1].strip().split(",")
            # Clean up items - remove explanations in parentheses
            current_scenario['expected_top'] = [re.sub(r'\s*\(.*?\)', '', item.strip()) for item in items]
            # Extract N from EXPECTED_TOP_N
            match = re.search(r'EXPECTED_TOP_(\d+)', line)
            if match:
                current_scenario['top_n'] = int(match.group(1))
        
        # Match EXPECTED_NOT_IN_TOP_N
        elif re.search(r'# EXPECTED_NOT_IN_TOP_\d+:', line) and current_scenario:
            items = line.split(":", 1)[1].strip().split(",")
            # Clean up items - remove explanations in parentheses
            current_scenario['expected_not_in_top'] = [re.sub(r'\s*\(.*?\)', '', item.strip()) for item in items]
    
    # Add last scenario
    if current_scenario and 'line_num' in current_scenario:
        scenarios.append(current_scenario)
    
    # Now extract source code for each scenario
    for i, scenario in enumerate(scenarios):
        # The TEST_POINT comment already gives us the line number (already 0-based from parsing)
        test_line = scenario['line_num']
        
        # Find start of THIS scenario (previous scenario's end or file start)
        if i > 0:
            # Start from AFTER previous scenario's test line
            prev_test_line = scenarios[i-1]['line_num']
            # Find next non-empty line after prev scenario (skip empty lines, find next # SCENARIO)
            start_line = prev_test_line + 1
            while start_line < test_line and (lines[start_line].strip() == '' or lines[start_line].strip().startswith('#')):
                start_line += 1
            # Actually, better to find the # SCENARIO line
            start_line = prev_test_line + 1
            while start_line < test_line:
                if lines[start_line].strip().startswith('# SCENARIO'):
                    break
                start_line += 1
        else:
            start_line = 0
        
        # Get lines from scenario start to test line (inclusive)
        # BUT skip comment lines (# SCENARIO, # TEST_POINT, # EXPECTED_*)
        source_lines = []
        actual_line_in_source = 0  # Track actual line number in cleaned source
        for line_idx in range(start_line, test_line + 1):
            line = lines[line_idx]
            # Skip comment lines
            if line.strip().startswith('#'):
                continue
            # Skip empty lines BEFORE first code line
            if len(source_lines) == 0 and line.strip() == '':
                continue
            # Add this line
            source_lines.append(line)
            # If this is the test line, remember its position in cleaned source
            if line_idx == test_line:
                actual_line_in_source = len(source_lines) - 1
        
        # LSP handles incomplete syntax fine, don't modify the code!
        
        scenario['source_code'] = ''.join(source_lines)
        # IMPORTANT: actual_line is 0-based index in cleaned source_lines
        scenario['actual_line'] = actual_line_in_source
        
        # Extract line_before_cursor (up to col_num)
        test_line_content = lines[test_line] if test_line < len(lines) else ""
        scenario['line_before_cursor'] = test_line_content[:scenario['col_num']]
        scenario['line_after_cursor'] = test_line_content[scenario['col_num']:]
    
    return scenarios


def run_scenario_test(scenario):
    """Run a single scenario test."""
    name = scenario['scenario_name']
    filepath = scenario['filepath']
    
    print("\n" + "="*80)
    print(f"📋 {name}")
    print(f"   File: {os.path.basename(filepath)}")
    print("="*80)
    
    # DEBUG INFO: LSP запит
    print(f"\n🔍 DEBUG: ЩО ПОВЕРНУВ PYRIGHT LSP:")
    print(f"   📡 Запит до pyright-langserver...")
    print(f"   📄 Source code length: {len(scenario['source_code'])} chars")
    print(f"   📍 Position: line {scenario['actual_line'] + 1}, col {scenario['col_num']}")
    
    lsp_items = get_completions_from_pyright(
        scenario['source_code'],
        scenario['actual_line'],
        scenario['col_num']
    )
    
    if not lsp_items:
        print("   ❌ LSP не повернув completions")
        print(f"   ℹ️  Можливо неповний синтаксис у рядку: {scenario['line_before_cursor']!r}")
        return False
    
    print(f"   ✅ LSP повернув {len(lsp_items)} completions")
    
    # Convert to lsp_types.CompletionItem
    completions = []
    for item in lsp_items:
        completions.append(lsp_types.CompletionItem(
            label=item.get('label', ''),
            kind=lsp_types.CompletionItemKind(item['kind']) if 'kind' in item else None,
            detail=item.get('detail', ''),
            sortText=item.get('sortText', ''),
            filterText=item.get('filterText', ''),
            insertText=item.get('insertText', '')
        ))
    
    print(f"   Перші 40 completions від LSP:")
    for i, c in enumerate(completions[:40], 1):
        kind_name = c.kind.name if c.kind else "?"
        sort_text = c.sortText[:20] if c.sortText else ""
        print(f"      {i:2}. {c.label:20} kind={kind_name:10} sortText={sort_text}")
    
    # DEBUG INFO: Context-aware алгоритм
    print(f"\n🔍 DEBUG: CONTEXT-AWARE SORTING:")
    
    # Extract prefix (последнее слово/идентификатор в line_before_cursor)
    line_before = scenario['line_before_cursor']
    prefix = ""
    if line_before:
        # Берем последнее слово (альфа-нумерик символы + _)
        import re
        match = re.search(r'(\w+)$', line_before)
        if match:
            prefix = match.group(1)
    
    print(f"   Extracted prefix: {prefix!r}")
    
    # Create sort key (це виведе логи про буусти)
    sort_key = create_context_aware_sort_key(
        prefix=prefix,
        line_before_cursor=scenario['line_before_cursor'],
        line_after_cursor=scenario['line_after_cursor'],
        source_code=scenario['source_code']
    )
    
    # Sort completions
    sorted_completions = sorted(completions, key=sort_key)
    
    # Filter out garbage builtins (use production code!)
    sorted_completions = filter_garbage_completions(sorted_completions)
    
    labels = [c.label for c in sorted_completions]
    
    print(f"\n   Топ-20 після sorting:")
    for i, c in enumerate(sorted_completions[:20], 1):
        kind_name = c.kind.name if c.kind else "?"
        print(f"      {i:2}. {c.label:20} | {kind_name}")
    
    # ============================================================
    # SUMMARY: Important info at the end for quick review
    # ============================================================
    print("\n" + "="*80)
    print("📝 SUMMARY (важлива інформація)")
    print("="*80)
    
    # 1. ВСЯ ПРОГРАМА
    print("\n1️⃣ ВСЯ ПРОГРАМА:")
    all_lines = scenario['source_code'].rstrip().split('\n')
    for i, line in enumerate(all_lines):
        marker = " <-- CURSOR" if i == scenario['actual_line'] else ""
        print(f"   {i+1:3}: {line}{marker}")
    
    # 2. ДЕ КУРСОР
    print(f"\n2️⃣ ПОЗИЦІЯ КУРСОРУ:")
    print(f"   Line {scenario['actual_line'] + 1}, Column {scenario['col_num']}")
    print(f"   Текст: '{scenario['line_before_cursor']}|{scenario['line_after_cursor'].rstrip()}'")
    
    # 3. РЕАЛЬНИЙ ВИВІД UI
    print(f"\n3️⃣ РЕАЛЬНИЙ AUTOCOMPLETE (що побачить користувач у Thonny):")
    print(f"   Top 10: {labels[:10]}")
    
    # 4. ВИСНОВОК З ТЕСТУ
    print(f"\n4️⃣ ВИСНОВОК З ТЕСТУ:")
    
    # Show what we're testing
    if 'expected_top' in scenario:
        expected_n = scenario.get('top_n', 3)
        print(f"   🎯 Очікуємо top-{expected_n}: {scenario['expected_top']}")
    if 'expected_first' in scenario:
        print(f"   🎯 Очікуємо перший: {scenario['expected_first']}")
    if 'expected_not_in_top' in scenario:
        not_n = scenario.get('top_n', 5)
        print(f"   🎯 НЕ очікуємо в top-{not_n}: {scenario['expected_not_in_top']}")
    
    passed = True
    issues = []
    successes = []
    
    # Check EXPECTED_FIRST
    if 'expected_first' in scenario:
        expected = scenario['expected_first'][0]
        actual = labels[0] if labels else None
        if actual != expected:
            issues.append(f"Очікували перший '{expected}', отримали '{actual}'")
            passed = False
        else:
            successes.append(f"✓ Перший елемент правильний: '{expected}'")
    
    # Check EXPECTED_TOP_N (ORDER MATTERS!)
    if 'expected_top' in scenario:
        expected = scenario['expected_top']
        expected_len = len(expected)
        actual_slice = labels[:expected_len]
        
        if expected != actual_slice:
            issues.append(f"Очікували top-{expected_len}: {expected}")
            issues.append(f"Отримали top-{expected_len}: {actual_slice}")
            issues.append(f"Повний UI: {labels[:20]}")
            passed = False
        else:
            successes.append(f"✓ Top-{expected_len} співпадає: {expected}")
            successes.append(f"  Повний UI: {labels[:20]}")
    
    # Check EXPECTED_NOT_IN_TOP_N
    if 'expected_not_in_top' in scenario:
        top_n = scenario.get('top_n', 5)
        not_expected = scenario['expected_not_in_top']
        actual_top = labels[:top_n]
        
        unexpected = [item for item in not_expected if item in actual_top]
        if unexpected:
            issues.append(f"Не повинні бути в top-{top_n}, але присутні: {unexpected}")
            issues.append(f"Повний UI: {labels[:20]}")
            passed = False
        else:
            successes.append(f"✓ Правильно виключені з top-{top_n}: {not_expected}")
            successes.append(f"  Повний UI: {labels[:20]}")
    
    # Print results
    if successes:
        for s in successes:
            print(f"   {s}")
    
    if issues:
        print(f"\n   ❌ ТЕСТ НЕ ПРОЙШОВ:")
        for issue in issues:
            print(f"      • {issue}")
    else:
        print(f"\n   ✅ ТЕСТ ПРОЙШОВ!")
    
    # Save results to scenario for external use (like run_single_test.py)
    scenario['sorted_labels'] = labels
    scenario['sorted_completions_objs'] = sorted_completions
    scenario['test_passed'] = passed
    
    return passed


def main():
    """Run all scenario tests."""
    print("\n" + "🧪"*40)
    print(" "*8 + "AUTOCOMPLETE SCENARIOS TEST RUNNER")
    print("🧪"*40)
    
    # Find all test scenario files
    scenarios_dir = Path(__file__).parent / "test_scenarios"
    scenario_files = sorted(scenarios_dir.glob("test_*.py"))
    
    if not scenario_files:
        print(f"❌ No test scenario files found in {scenarios_dir}")
        return 1
    
    print(f"\n📁 Found {len(scenario_files)} test files:")
    for f in scenario_files:
        print(f"   - {f.name}")
    
    all_scenarios = []
    for filepath in scenario_files:
        scenarios = parse_scenario_file(filepath)
        all_scenarios.extend(scenarios)
    
    print(f"\n📋 Parsed {len(all_scenarios)} scenarios total")
    
    # Run all tests
    passed = 0
    failed = 0
    
    for scenario in all_scenarios:
        try:
            if run_scenario_test(scenario):
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # Summary
    print("\n" + "="*80)
    print("📊 FINAL RESULTS")
    print("="*80)
    print(f"✅ Passed: {passed}/{len(all_scenarios)}")
    if failed > 0:
        print(f"❌ Failed: {failed}/{len(all_scenarios)}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {failed} tests failed")
        return 1


if __name__ == "__main__":
    # Redirect output to both console and file
    class TeeOutput:
        def __init__(self, *files):
            self.files = files
        def write(self, data):
            for f in self.files:
                f.write(data)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()
    
    # Open output file
    output_file = open('test_results.txt', 'w', encoding='utf-8')
    original_stdout = sys.stdout
    sys.stdout = TeeOutput(sys.stdout, output_file)
    
    try:
        exit_code = main()
    finally:
        sys.stdout = original_stdout
        output_file.close()
        print(f"\n📄 Results saved to: test_results.txt")
    
    sys.exit(exit_code)

