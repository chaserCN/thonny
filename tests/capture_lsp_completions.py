#!/usr/bin/env python3
"""
Capture real LSP completions for test scenarios.

This script:
1. Reads test scenario files
2. Finds TEST_POINT markers  
3. Programmatically requests completions from LSP
4. Saves results as JSON fixtures

Usage:
    python3 capture_lsp_completions.py
"""

import os
import sys
import json
import re
from pathlib import Path

# Add thonny to path
sys.path.insert(0, os.path.dirname(__file__))

def parse_scenario_file(filepath):
    """
    Parse a test scenario file and extract test points.
    
    Returns list of test cases with structure:
    {
        'file': 'test_for_loops.py',
        'scenario_name': 'Simple list variable',
        'line': 9,
        'col': 10,
        'expected_top_3': ['mas', 'nums', 'data'],
        'expected_not_in_top_5': ['True', 'False', 'if'],
        'source_code': '...',
        'line_before_cursor': 'for x in ',
        'prefix': ''
    }
    """
    with open(filepath, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    test_cases = []
    current_test = None
    
    for i, line in enumerate(lines, 1):
        # Parse test point marker
        if line.strip().startswith('# SCENARIO'):
            # Extract scenario number and name
            match = re.search(r'# SCENARIO (\d+): (.+)', line)
            if match:
                scenario_num = match.group(1)
                scenario_name = match.group(2)
                current_test = {
                    'file': os.path.basename(filepath),
                    'scenario_num': scenario_num,
                    'scenario_name': scenario_name,
                    'source_code': content
                }
        
        elif line.strip().startswith('# TEST_POINT:') and current_test:
            # Parse: line 9, col 10
            match = re.search(r'line (\d+), col (\d+)', line)
            if match:
                current_test['line'] = int(match.group(1))
                current_test['col'] = int(match.group(2))
        
        elif line.strip().startswith('# EXPECTED_TOP_') and current_test:
            # Parse expected results
            if 'EXPECTED_TOP_3:' in line:
                items = re.search(r'EXPECTED_TOP_3:\s*(.+)', line)
                if items:
                    current_test['expected_top_3'] = [x.strip() for x in items.group(1).split(',')]
            elif 'EXPECTED_TOP_5:' in line:
                items = re.search(r'EXPECTED_TOP_5:\s*(.+)', line)
                if items:
                    current_test['expected_top_5'] = [x.strip() for x in items.group(1).split(',')]
        
        elif line.strip().startswith('# EXPECTED_NOT_IN_TOP_') and current_test:
            if 'EXPECTED_NOT_IN_TOP_3:' in line:
                items = re.search(r'EXPECTED_NOT_IN_TOP_3:\s*(.+)', line)
                if items:
                    current_test['expected_not_in_top_3'] = [x.strip() for x in items.group(1).split(',')]
            elif 'EXPECTED_NOT_IN_TOP_5:' in line:
                items = re.search(r'EXPECTED_NOT_IN_TOP_5:\s*(.+)', line)
                if items:
                    current_test['expected_not_in_top_5'] = [x.strip() for x in items.group(1).split(',')]
        
        elif line.strip().startswith('# EXPECTED_FIRST:') and current_test:
            items = re.search(r'EXPECTED_FIRST:\s*(.+)', line)
            if items:
                current_test['expected_first'] = items.group(1).strip()
        
        # When we hit a blank line after collecting test data, finalize it
        elif not line.strip() and current_test and 'line' in current_test:
            # Extract context
            test_line_idx = current_test['line'] - 1
            test_col = current_test['col']
            
            if test_line_idx < len(lines):
                test_line = lines[test_line_idx]
                current_test['line_before_cursor'] = test_line[:test_col]
                current_test['line_after_cursor'] = test_line[test_col:]
                
                # Extract prefix (what user typed)
                prefix = current_test['line_before_cursor'].split()[-1] if current_test['line_before_cursor'].split() else ''
                if not prefix.isidentifier():
                    prefix = ''
                current_test['prefix'] = prefix
            
            test_cases.append(current_test)
            current_test = None
    
    return test_cases


def request_completions_from_lsp(source_code, line, col):
    """
    Request completions from Pyright LSP directly via subprocess.
    
    Simpler and more reliable than using Thonny's workbench.
    """
    import tempfile
    import subprocess
    import json
    from pathlib import Path
    
    print(f"  📡 Requesting completions from Pyright at line {line}, col {col}...")
    
    # Create temp file with source code
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=Path(__file__).parent) as f:
        f.write(source_code)
        temp_path = Path(f.name)
    
    try:
        # Convert to URI
        uri = temp_path.as_uri()
        
        # LSP uses 0-based indexing
        lsp_line = line - 1
        lsp_col = col
        
        # Prepare LSP requests
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": None,
                "rootUri": temp_path.parent.as_uri(),
                "capabilities": {}
            }
        }
        
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        }
        
        did_open_notification = {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "python",
                    "version": 1,
                    "text": source_code
                }
            }
        }
        
        completion_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": lsp_line, "character": lsp_col}
            }
        }
        
        shutdown_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "shutdown",
            "params": None
        }
        
        exit_notification = {
            "jsonrpc": "2.0",
            "method": "exit",
            "params": None
        }
        
        # Combine all requests
        requests = [
            json.dumps(initialize_request),
            json.dumps(initialized_notification),
            json.dumps(did_open_notification),
            json.dumps(completion_request),
            json.dumps(shutdown_request),
            json.dumps(exit_notification)
        ]
        
        # Join with proper LSP framing
        lsp_input = ""
        for req in requests:
            lsp_input += f"Content-Length: {len(req)}\r\n\r\n{req}"
        
        # Run pyright-langserver
        try:
            result = subprocess.run(
                ['pyright-langserver', '--stdio'],
                input=lsp_input,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Parse LSP responses
            output = result.stdout
            completions = []
            
            # Extract completion response (id: 2)
            for part in output.split('Content-Length:'):
                if '"id":2' in part or '"id": 2' in part:
                    # Extract JSON
                    json_start = part.find('{')
                    if json_start >= 0:
                        try:
                            response_json = json.loads(part[json_start:])
                            if 'result' in response_json:
                                result_data = response_json['result']
                                if isinstance(result_data, list):
                                    completions = result_data
                                elif isinstance(result_data, dict) and 'items' in result_data:
                                    completions = result_data['items']
                        except json.JSONDecodeError:
                            pass
            
            if completions:
                print(f"  ✅ Received {len(completions)} completions from Pyright")
            else:
                print(f"  ⚠️  No completions received")
            
            return completions
            
        except FileNotFoundError:
            print(f"  ❌ pyright-langserver not found. Install with: pip install pyright")
            return []
        except subprocess.TimeoutExpired:
            print(f"  ❌ Pyright timeout")
            return []
    
    except Exception as e:
        print(f"  ❌ Error requesting completions: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    finally:
        # Cleanup temp file
        if temp_path.exists():
            temp_path.unlink()


def serialize_completion_item(item):
    """Convert CompletionItem (dict from Pyright) to simplified dict."""
    if isinstance(item, dict):
        # Already a dict from Pyright
        kind_value = item.get('kind')
        kind_name = get_completion_kind_name(kind_value) if kind_value else None
        
        return {
            'label': item.get('label', ''),
            'kind': kind_value,
            'kind_name': kind_name,
            'detail': item.get('detail'),
            'sortText': item.get('sortText'),
            'insertText': item.get('insertText'),
        }
    else:
        # CompletionItem object (if using Thonny)
        return {
            'label': item.label,
            'kind': item.kind.value if item.kind else None,
            'kind_name': item.kind.name if item.kind else None,
            'detail': item.detail,
            'sortText': item.sortText,
            'insertText': item.insertText,
        }


def get_completion_kind_name(kind_value):
    """Convert LSP CompletionItemKind number to name."""
    kind_map = {
        1: 'Text', 2: 'Method', 3: 'Function', 4: 'Constructor',
        5: 'Field', 6: 'Variable', 7: 'Class', 8: 'Interface',
        9: 'Module', 10: 'Property', 11: 'Unit', 12: 'Value',
        13: 'Enum', 14: 'Keyword', 15: 'Snippet', 16: 'Color',
        17: 'File', 18: 'Reference', 19: 'Folder', 20: 'EnumMember',
        21: 'Constant', 22: 'Struct', 23: 'Event', 24: 'Operator',
        25: 'TypeParameter'
    }
    return kind_map.get(kind_value, f'Unknown({kind_value})')


def main():
    """Main entry point."""
    print("🔍 LSP Completion Capture Tool")
    print("=" * 80)
    
    # Find all test scenario files
    scenarios_dir = Path(__file__).parent / 'test_scenarios'
    if not scenarios_dir.exists():
        print(f"❌ Scenarios directory not found: {scenarios_dir}")
        return 1
    
    scenario_files = sorted(scenarios_dir.glob('test_*.py'))
    print(f"📁 Found {len(scenario_files)} scenario files\n")
    
    all_test_cases = []
    
    # Parse all scenario files
    for filepath in scenario_files:
        print(f"📄 Parsing: {filepath.name}")
        test_cases = parse_scenario_file(filepath)
        print(f"   Found {len(test_cases)} test cases")
        all_test_cases.extend(test_cases)
        
        for tc in test_cases:
            print(f"   - Scenario {tc['scenario_num']}: {tc['scenario_name']}")
            print(f"     Position: line {tc['line']}, col {tc['col']}")
            print(f"     Context: '{tc.get('line_before_cursor', '')}' ← cursor")
    
    print(f"\n📊 Total test cases: {len(all_test_cases)}")
    print("\n" + "=" * 80)
    print("🚀 Capturing completions from LSP...")
    print("=" * 80 + "\n")
    
    # Create fixtures directory
    fixtures_dir = Path(__file__).parent / 'fixtures'
    fixtures_dir.mkdir(exist_ok=True)
    
    # Capture completions for each test case
    for i, tc in enumerate(all_test_cases, 1):
        print(f"[{i}/{len(all_test_cases)}] {tc['file']} - Scenario {tc['scenario_num']}")
        
        # Request completions from LSP
        completions = request_completions_from_lsp(
            tc['source_code'],
            tc['line'],
            tc['col']
        )
        
        # Save to fixture file
        fixture_name = f"{tc['file'].replace('.py', '')}_{tc['scenario_num']}.json"
        fixture_path = fixtures_dir / fixture_name
        
        fixture_data = {
            'metadata': {
                'file': tc['file'],
                'scenario_num': tc['scenario_num'],
                'scenario_name': tc['scenario_name'],
                'line': tc['line'],
                'col': tc['col'],
                'line_before_cursor': tc.get('line_before_cursor', ''),
                'line_after_cursor': tc.get('line_after_cursor', ''),
                'prefix': tc.get('prefix', ''),
                'source_code': tc['source_code'],
            },
            'expectations': {
                k: v for k, v in tc.items() 
                if k.startswith('expected_')
            },
            'completions': [serialize_completion_item(c) for c in completions]
        }
        
        with open(fixture_path, 'w') as f:
            json.dump(fixture_data, f, indent=2)
        
        print(f"   ✅ Saved to {fixture_name} ({len(completions)} completions)")
    
    print("\n" + "=" * 80)
    print(f"✅ Capture complete! {len(all_test_cases)} fixtures saved to {fixtures_dir}")
    print("=" * 80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

