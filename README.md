pygui demo video

https://github.com/user-attachments/assets/6034afa1-7ad2-4c4a-8027-e676f290f299

## VS Code integration

This project now supports bidirectional communication between the flamegraph app and VS Code.

### App → VS Code (open file + line)

- In the **Function snippet** panel, click **Open in VS Code**.
- The app will try `code --goto /abs/path:line` first.
- If `code` is unavailable in PATH, it falls back to a `vscode://file/...:line` URI.

### VS Code extension → App (focus function/location)

The app starts a localhost HTTP bridge on `127.0.0.1:8765` (override with `VSCODE_BRIDGE_PORT`).

- Health:
	- `GET /health`
- Command:
	- `POST /command`

#### Payloads

Select by function name:

```json
{
	"action": "select_function",
	"function": "my_function_name"
}
```

Select by file/line (chooses closest matching symbol in current process root):

```json
{
	"action": "select_location",
	"path": "/absolute/path/to/file.c",
	"line": 123
}
```

