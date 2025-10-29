#!/usr/bin/env python3
"""
Проверяет что TEST_POINT указывает на правильную строку и колонку.
Показывает какой код будет извлечен test_scenarios_runner.py.
"""

import sys
from pathlib import Path

# Add parent to path to import test_scenarios_runner
sys.path.insert(0, str(Path(__file__).parent))

from test_scenarios_runner import parse_scenario_file


def verify_test_points(filepath):
    """Проверяет TEST_POINT в файле и показывает извлеченный код."""
    
    # Используем ту же функцию что и test_scenarios_runner
    scenarios = parse_scenario_file(filepath)
    
    if not scenarios:
        return [f"  ❌ Не найдено сценариев в файле"]
    
    errors = []
    
    # Проверяем каждый сценарий
    for idx, scenario in enumerate(scenarios):
        print(f"\n  {'='*60}")
        print(f"  Scenario {idx + 1}: {scenario.get('scenario_name', 'Unknown')}")
        print(f"  {'='*60}")
        
        # Показываем извлеченный код
        source_code = scenario.get('source_code', '')
        actual_line = scenario.get('actual_line', 0)
        col_num = scenario.get('col_num', 0)
        
        if not source_code:
            errors.append(f"  ❌ Не удалось извлечь код для сценария")
            continue
        
        source_lines = source_code.split('\n')
        print(f"  📄 Extracted code ({len(source_lines)} lines):")
        for j, code_line in enumerate(source_lines):
            marker = " <-- CURSOR" if j == actual_line else ""
            print(f"     {j+1}: {code_line}{marker}")
        
        # Получаем строку с курсором
        if actual_line < len(source_lines):
            cursor_line = source_lines[actual_line]
            
            # Проверяем что колонка не выходит за пределы строки
            if col_num > len(cursor_line):
                errors.append(
                    f"  ❌ TEST_POINT col={col_num}, но строка имеет длину {len(cursor_line)}"
                )
                errors.append(f"     Строка: {repr(cursor_line)}")
            else:
                # Показываем где курсор
                cursor_context = cursor_line[:col_num] + '|' + cursor_line[col_num:]
                print(f"\n  ✓ Cursor position: {repr(cursor_context)}")
                print(f"  ✓ Line before cursor: {repr(scenario.get('line_before_cursor', ''))}")
                print(f"  ✓ Line after cursor: {repr(scenario.get('line_after_cursor', ''))}")
        else:
            errors.append(f"  ❌ actual_line={actual_line} >= len(source_lines)={len(source_lines)}")
    
    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_test_points.py <test_file.py> [test_file2.py ...]")
        sys.exit(1)
    
    filepaths = sys.argv[1:]
    all_errors = []
    
    for filepath in filepaths:
        print(f"\n{'='*70}")
        print(f"📋 Checking {filepath}")
        print('='*70)
        
        errors = verify_test_points(filepath)
        
        if errors:
            print(f"\n❌ Found {len(errors)} error(s):")
            for error in errors:
                print(error)
            all_errors.extend(errors)
        else:
            print("\n✅ All TEST_POINTs are valid!")
    
    print(f"\n{'='*70}")
    if all_errors:
        print(f"❌ Total: {len(all_errors)} error(s) found")
        sys.exit(1)
    else:
        print("✅ All TEST_POINTs are valid in all files!")
        sys.exit(0)


if __name__ == "__main__":
    main()

