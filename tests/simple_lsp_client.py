#!/usr/bin/env python3
"""
Simple LSP client to get completions from Pyright.
"""

import json
import subprocess
import os
import tempfile
from pathlib import Path


def send_lsp_message(proc, method, params, msg_id=None):
    """Send LSP message to the process."""
    message = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params
    }
    if msg_id is not None:
        message["id"] = msg_id
    
    content = json.dumps(message)
    header = f"Content-Length: {len(content)}\r\n\r\n"
    proc.stdin.write(header + content)
    proc.stdin.flush()


def read_lsp_message(proc, timeout=5):
    """Read one LSP message from the process."""
    import select
    
    # Check if data is available
    if hasattr(select, 'poll'):
        poller = select.poll()
        poller.register(proc.stdout, select.POLLIN)
        if not poller.poll(timeout * 1000):
            raise TimeoutError("No data from LSP server")
    
    # Read headers
    headers = {}
    while True:
        line = proc.stdout.readline()
        if not line:
            raise EOFError("Connection closed")
        if line == '\r\n' or line == '\n':
            break
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip()] = value.strip()
    
    # Read content
    content_length = int(headers.get('Content-Length', 0))
    if content_length == 0:
        raise ValueError("Invalid Content-Length")
    
    content = proc.stdout.read(content_length)
    if not content:
        raise EOFError("No content received")
    
    return json.loads(content)


def get_completions_from_pyright(source_code, line, character):
    """
    Get completions from Pyright for given source code and position.
    
    Args:
        source_code: Python source code string
        line: Line number (0-based)
        character: Character position (0-based)
    
    Returns:
        List of completion items (dicts)
    """
    # Create a dedicated temp directory for this test (clean workspace)
    import tempfile
    temp_dir = tempfile.mkdtemp(prefix='pyright_test_')
    temp_path = os.path.join(temp_dir, 'test.py')
    
    with open(temp_path, 'w') as f:
        f.write(source_code)
    
    proc = None
    cleanup_dir = temp_dir  # Save for finally block
    try:
        uri = Path(temp_path).as_uri()
        root_uri = Path(temp_dir).as_uri()
        
        # Start pyright-langserver  
        proc = subprocess.Popen(
            ['pyright-langserver', '--stdio'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0
        )
        
        # Initialize
        send_lsp_message(proc, 'initialize', {
            'processId': os.getpid(),
            'rootUri': root_uri,
            'capabilities': {
                'textDocument': {
                    'completion': {
                        'completionItem': {
                            'snippetSupport': False
                        }
                    }
                }
            }
        }, msg_id=1)
        
        # Read initialize response
        response = read_lsp_message(proc)
        
        if 'error' in response:
            print(f"❌ Initialize error: {response['error']}")
            return []
        
        # Send initialized notification
        send_lsp_message(proc, 'initialized', {})
        
        # Open document
        send_lsp_message(proc, 'textDocument/didOpen', {
            'textDocument': {
                'uri': uri,
                'languageId': 'python',
                'version': 1,
                'text': source_code
            }
        })
        
        # Wait a bit and consume any notifications
        import time
        time.sleep(0.3)
        
        # Try to read any pending messages (notifications)
        try:
            while True:
                msg = read_lsp_message(proc, timeout=0.1)
        except (TimeoutError, EOFError):
            pass  # No more messages
        
        # Request completions
        send_lsp_message(proc, 'textDocument/completion', {
            'textDocument': {'uri': uri},
            'position': {'line': line, 'character': character},
            'context': {'triggerKind': 1}  # Invoked
        }, msg_id=2)
        
        # Read messages until we get our completion response
        for i in range(10):  # Max 10 messages
            try:
                msg = read_lsp_message(proc, timeout=2)
                
                # DEBUG: print all messages
                import json
                print(f"[DEBUG] Message {i+1}: {json.dumps(msg, indent=2)[:500]}")
                
                if 'id' in msg and msg['id'] == 2:
                    if 'result' in msg:
                        result = msg['result']
                        if isinstance(result, dict) and 'items' in result:
                            items = result['items']
                        elif isinstance(result, list):
                            items = result
                        else:
                            items = []
                        return items
                    elif 'error' in msg:
                        print(f"❌ Completion error: {msg['error']}")
                        return []
            except TimeoutError:
                print(f"❌ Timeout waiting for completion response (after {i} messages)")
                break
            except Exception as e:
                print(f"❌ Error reading message: {e}")
                break
        
        print("❌ Did not get completion response")
        return []
        
    except Exception as e:
        print(f"Error getting completions: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        if proc and proc.poll() is None:
            # Shutdown gracefully
            try:
                send_lsp_message(proc, 'shutdown', {}, msg_id=999)
                send_lsp_message(proc, 'exit', {})
                proc.wait(timeout=2)
            except:
                pass
            
            # Force kill if still alive
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except:
                    try:
                        proc.kill()
                    except:
                        pass
        # Cleanup temp directory
        try:
            import shutil
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        except:
            pass


def test_simple():
    """Test with simple code."""
    code = """
x = [1, 2, 3]
y = [4, 5, 6]
for item in 
"""
    
    print("Testing with code:")
    print(code)
    print("\nGetting completions at position (3, 12) - after 'for item in '...")
    
    completions = get_completions_from_pyright(code, 3, 12)
    
    print(f"\nGot {len(completions)} completions:")
    for item in completions[:10]:
        label = item.get('label', '?')
        kind = item.get('kind', '?')
        detail = item.get('detail', '')
        sort_text = item.get('sortText', '')
        print(f"  {label:20} kind={kind:2} sortText={sort_text:15} detail={detail[:40]}")


if __name__ == '__main__':
    test_simple()

