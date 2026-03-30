import asyncio
from pprint import pprint
from pygdbmi.gdbcontroller import GdbController
import json
import networkx as nx
import websockets

from gen_callgraph_from_folded import build_graph_fast

perf_callgraph = build_graph_fast("minix.out.folded");

from pprint import pprint

import debugger
dbg = debugger.Debugger("/vol/os/linux/vmlinux")


# ----------------------------
# Graph logic
# ----------------------------

def build_callgraph(func, radius=1):
    func = func.split()[0]
    if func not in perf_callgraph:
        return nx.DiGraph()

    # ego graph around the function
    return nx.ego_graph(perf_callgraph, func, radius=radius, undirected=False)


def render_callgraph_svg(g):
    if len(g.nodes) == 0:
        return "<svg></svg>"

    from networkx.drawing.nx_pydot import to_pydot

    p = to_pydot(g)

    # optional: basic styling
    p.set_rankdir("TB")  # top-to-bottom layout

    return p.create_svg().decode("utf-8")


# ----------------------------
# Event handlers
# ----------------------------

async def handle_zoom(ws, msg):
    func = msg.get("function")
    if not func:
        return

    print(f"[zoom] {func}")

    cg = build_callgraph(func)
    svg = render_callgraph_svg(cg)
    #print(svg)

    response = {
        "type": "callgraph_update",
        "svg": svg,
        "focus": func
    }

    await ws.send(json.dumps(response))


# ----------------------------
# Dispatcher
# ----------------------------

async def respond_source(ws, func):
        print(f"Trying out {func}")
        #resp = gdb.write(f"list {func}", timeout_sec=5)
        #pprint(resp)
        #text_lines = [i["payload"] for i in resp if i["type"] == "console"]
        #pprint("".join(text_lines))
        await ws.send(json.dumps({
            "type": "source",
            "function": func,
            "text": dbg.list_function(func, 50),
        }))

async def handle_event(ws, msg):
    t = msg.get("type")
    func = msg["function"].split()[0]
    if t == "get_source":
        await respond_source(ws, func)
    elif t == "zoom":
        await handle_zoom(ws, msg)
        await respond_source(ws, func)
    else:
        print(f"[warn] unknown event type: {t}")


# ----------------------------
# WebSocket connection handler
# ----------------------------

async def handle_connection(ws):
    print("[connect] client connected")

    try:
        async for message in ws:
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                print("[error] invalid json")
                continue

            await handle_event(ws, msg)

    except websockets.exceptions.ConnectionClosed:
        print("[disconnect] client disconnected")


# ----------------------------
# Main
# ----------------------------

async def main():
    async with websockets.serve(handle_connection, "localhost", 8765):
        print("WebSocket server running on ws://localhost:8765")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
