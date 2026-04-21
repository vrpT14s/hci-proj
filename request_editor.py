import requests

editor_ip = ('127.0.0.1', '9999')

def editor_jump_to_location(pathline):
    host, port = editor_ip
    try:
        response = requests.post(f"http://{host}:{port}/command", json={"location": pathline})
        if response.status_code == 200:
            print(f"Successfully jumped to: {pathline}")
        else:
            print(f"Failed to jump. Server returned: {response.status_code} - {response.text}")
    except requests.exceptions.ConnectionError:
        print(f"Could not connect to VS Code at {url}. Is the extension server running?")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def editor_jump_to_node(fg, node):
    path, line = fg.node_path(node) or (None, None)
    if path is None or line is None:
        return
    if str(path)[0] == '[':
        return
    editor_jump_to_location(str(path) + ':' + line)
    editor_sync_histogram(fg, node)

def editor_sync_histogram(fg, node):
    path, base_line = fg.node_path(node) or (None, None)
    if not path or str(path).startswith('['): return

    # Get the {offset: count} dict from your LLDB logic
    line_hist = fg.node_get_histogram(node)

    host, port = editor_ip
    response = requests.post(
        f"http://{host}:{port}/histogram",
        json={
            "path": str(path),
            "baseLine": int(base_line),
            "histogram": line_hist
        }
    )
    print(response)
