"""Minimal MCP stdio server for integration testing.
Responds to initialize, notifications/initialized, and tools/list.
Provides two fake tools: greet and add_numbers.
"""

import json
import sys

TOOLS = [
    {
        "name": "greet",
        "description": "Generate a greeting message for someone",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to greet"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_numbers",
        "description": "Add two numbers together and return the sum",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    },
]


def handle(request):
    method = request.get("method", "")
    req_id = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        args = request.get("params", {}).get("arguments", {})
        if tool_name == "greet":
            text = f"Hello, {args.get('name', 'World')}!"
        elif tool_name == "add_numbers":
            text = str(args.get("a", 0) + args.get("b", 0))
        else:
            content = [{"type": "text", "text": f"Unknown tool: {tool_name}"}]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": content, "isError": True},
            }
        content = [{"type": "text", "text": text}]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": content}}
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
