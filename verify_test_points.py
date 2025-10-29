#!/usr/bin/env python3
"""
Проверяет что TEST_POINT указывает на правильную строку и колонку.
"""

import re
import sys
from pathlib import Path


def verify_test_points(filepath):
    """Проверяет TEST_POINT в файле."""
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    errors = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Ищем TEST_POINT
        match = re.search(r'# TEST_POINT: line (\d+), col (\d+)', line)
        if match:
            expected_line = int(match.group(1))
            expected_col = int(match.group(2))
            
            # Проверяем что указанная строка существует
            if expected_line > len(lines):
                errors.append(f"  ❌ Line {i+1}: TEST_POINT указывает на несуществующую строку {expected_line}")
                i += 1
                continue
            
            # Получаем реальную строку кода (1-based to 0-based)
            actual_line_content = lines[expected_line - 1]
            # НЕ используем rstrip() - нужны trailing пробелы!
            actual_line_stripped = actual_line_content.rstrip('\n\r')  # Только убираем переводы строк
            
            # Проверяем что колонка не выходит за пределы строки
            if expected_col > len(actual_line_stripped):
                errors.append(
                    f"  ❌ Line {i+1}: TEST_POINT col={expected_col}, но строка {expected_line} "
                    f"имеет длину {len(actual_line_stripped)}"
                )
                errors.append(f"     Строка: {repr(actual_line_stripped)}")
            else:
                # Показываем где курсор
                cursor_context = actual_line_stripped[:expected_col] + '|' + actual_line_stripped[expected_col:]
                print(f"  ✓ Line {i+1}: TEST_POINT line={expected_line}, col={expected_col}")
                print(f"    Code: {repr(cursor_context)}")
        
        i += 1
    
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

