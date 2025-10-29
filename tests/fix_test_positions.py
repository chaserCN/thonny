#!/usr/bin/env python3
"""
Script to automatically calculate TEST_POINT positions for test scenarios.
Finds # CURSOR_HERE markers and calculates line/col positions.
"""

import sys
import re
from pathlib import Path

def fix_test_file(filepath):
    """Fix TEST_POINT positions in a test scenario file."""
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    # Find all CURSOR_HERE markers
    cursor_positions = []
    for i, line in enumerate(lines):
        if '# CURSOR_HERE' in line:
            # Find position before the comment
            col = line.find('# CURSOR_HERE')
            cursor_positions.append((i, col))
    
    print(f"Found {len(cursor_positions)} CURSOR_HERE markers")
    
    # Now process TEST_POINT_MARKER lines
    scenario_num = 0
    new_lines = []
    
    for i, line in enumerate(lines):
        if '# TEST_POINT_MARKER' in line:
            if scenario_num < len(cursor_positions):
                cursor_line, cursor_col = cursor_positions[scenario_num]
                # Line numbers are 1-based in comments
                new_line = f"# TEST_POINT: line {cursor_line + 1}, col {cursor_col}\n"
                new_lines.append(new_line)
                print(f"  Scenario {scenario_num + 1}: line {cursor_line + 1}, col {cursor_col}")
                scenario_num += 1
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    # Remove CURSOR_HERE markers
    final_lines = []
    for line in new_lines:
        if '# CURSOR_HERE' in line:
            # Remove the marker but keep the code before it
            final_lines.append(line.replace('# CURSOR_HERE', '').rstrip() + '\n')
        else:
            final_lines.append(line)
    
    # Write back
    with open(filepath, 'w') as f:
        f.writelines(final_lines)
    
    print(f"\n✅ Fixed {filepath}")
    print(f"   Updated {scenario_num} TEST_POINT lines")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python fix_test_positions.py <test_file.py>")
        sys.exit(1)
    
    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"❌ File not found: {filepath}")
        sys.exit(1)
    
    fix_test_file(filepath)

