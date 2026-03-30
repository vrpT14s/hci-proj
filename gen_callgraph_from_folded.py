import networkx as nx
import subprocess
import matplotlib.pyplot as plt

from pprint import pprint as pp

from networkx.drawing.nx_pydot import write_dot


def directed_ego_subgraph(G, center, radius=2):
    """
    Get nodes within `radius` hops (undirected),
    but return a directed subgraph from original G.
    """
    # Step 1: find nodes using undirected graph
    undirected = G.to_undirected()
    nodes = nx.ego_graph(undirected, center, radius=radius).nodes()

    # Step 2: build directed subgraph from original graph
    H = G.subgraph(nodes).copy()

    return H

import networkx as nx

def weakly_connected_subgraph(G, center, radius=2):
    """
    Return a directed subgraph containing nodes weakly connected to `center`
    within `radius` hops (either forward or backward).
    """

    # Forward: center -> node
    forward_nodes = nx.ego_graph(G, center, radius=radius).nodes()

    # Backward: node -> center (use transpose)
    backward_nodes = nx.ego_graph(G.reverse(), center, radius=radius).nodes()

    # Union of both sets
    nodes = set(forward_nodes) | set(backward_nodes)

    # Preserve original directed edges
    H = G.subgraph(nodes).copy()
    return H

def dump_dot(G):
    write_dot(G, "subgraph.dot")

def parse_line(line: str, detect_recursion=False, recursion_stats=None):
    """
    Parse a single folded stack line.

    Format:
        funcA;funcB;funcC <count>

    Returns:
        (frames: list[str], count: int)
    """
    line = line.strip()
    if not line:
        return None, 0

    try:
        stack, count = line.rsplit(" ", 1)
        frames = stack.split(";")

        if frames[0].startswith("perf"):
            return None, 0

        if detect_recursion:
            seen = set()
            for f in frames:
                if f in seen:
                    # 🔴 recursion detected
                    if recursion_stats is not None:
                        recursion_stats[f] = recursion_stats.get(f, 0) + int(count)
                else:
                    seen.add(f)

        return frames, int(count)
    except ValueError:
        # malformed line
        return None, 0


def build_graph_fast(path: str):
    """
    Faster version:
    - accumulate weights in a dict first
    - then build graph in one go
    """
    edge_weights = {}

    recursion_stats = {}
    with open(path, "r") as f:
        for line in f:
            frames, count = parse_line(line, detect_recursion=True, recursion_stats=recursion_stats)
            if not frames:
                continue

            for i in range(len(frames) - 1):
                edge = (frames[i], frames[i + 1])
                edge_weights[edge] = edge_weights.get(edge, 0) + count

    print("Recursion stats:")
    pp(recursion_stats)
    print()

    G = nx.DiGraph()
    for (u, v), w in edge_weights.items():
        G.add_edge(u, v, weight=w)

    return G

import subprocess
import networkx as nx
from collections import defaultdict

def write_function_callgraph_dot(G, vmlinux_path, dot_path="graph.dot"):
    """
    Write a NetworkX function callgraph as a nested DOT file with folders/files clusters.
    Optimized to call addr2line only once for all functions.
    """

    # -------------------------
    # Step 1: Map functions -> source files (batch)
    # -------------------------
    functions = list(G.nodes())
    if not functions:
        raise ValueError("Graph has no nodes.")

    # Run addr2line in batch mode: one symbol per line
    # '-f' = print function name, '-i' = include inlined functions
    cmd = ["addr2line", "-e", vmlinux_path, "-f"] + functions
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"addr2line failed: {e.stderr}")

    # Parse output: addr2line prints 2 lines per input symbol
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2 * len(functions):
        raise RuntimeError("Unexpected addr2line output length")

    mapping = {}
    for i, func in enumerate(functions):
        file_line = lines[2*i + 1]  # 2nd line = file:line
        file_path = file_line.split(":")[0] if file_line != "??:0" else "unknown"
        mapping[func] = file_path

    # -------------------------
    # Step 2: Build nested dict tree by folder/file
    # -------------------------
    tree = lambda: defaultdict(tree)
    root = tree()
    for node in G.nodes():
        path = mapping.get(node, "unknown")
        parts = path.split("/") if path != "unknown" else [path]
        current = root
        for p in parts[:-1]:
            current = current[p]
        current[parts[-1]][node] = None

    # -------------------------
    # Step 3: Recursive function to write clusters (flatten single-item clusters)
    # -------------------------
    def write_cluster(f, subtree, name_prefix="cluster", level=0):
        for key, value in subtree.items():
            if all(v is None for v in value.values()):  # file cluster
                if len(value) == 1 and level > 0:
                    node = next(iter(value))
                    f.write(f'    {node};\n')
                else:
                    #f.write(f'  subgraph {name_prefix}_{key.replace(".", "_")} {{\n')
                    f.write(f'  subgraph "{name_prefix}_{key}" {{\n')
                    f.write(f'    label="{key}";\n')
                    f.write(f'    style=filled;\n')
                    f.write(f'    color=lightgrey;\n')
                    for node in value.keys():
                        f.write(f'    "{node}";\n')
                    f.write('  }\n')
            else:  # folder cluster
                children = []
                for child_key, child_value in value.items():
                    if all(v is None for v in child_value.values()) and len(child_value) == 1:
                        children.append(('node', next(iter(child_value))))
                    else:
                        children.append(('cluster', child_key))
                if len(children) == 1 and level > 0:
                    child_type, child = children[0]
                    if child_type == 'node':
                        f.write(f'    "{child}";\n')
                    else:
                        write_cluster(f, {child: value[child]}, name_prefix=name_prefix, level=level)
                else:
                    #f.write(f'  subgraph {name_prefix}_{key.replace("/", "_")} {{\n')
                    f.write(f'  subgraph "{name_prefix}_{key}" {{\n')
                    f.write(f'    label="{key}/";\n')
                    f.write(f'    style=rounded;\n')
                    f.write(f'    color=lightblue;\n')
                    write_cluster(f, value, name_prefix=f"{name_prefix}_{key.replace('/', '_')}", level=level+1)
                    f.write('  }\n')

    # -------------------------
    # Step 4: Write DOT file
    # -------------------------
    with open(dot_path, "w") as f:
        f.write("digraph G {\n")
        write_cluster(f, root)
        for u, v in G.edges():
            f.write(f'  "{u}" -> "{v}";\n')
        f.write("}\n")

    print(f"Wrote DOT file to {dot_path}")

def main():
    import sys

    if len(sys.argv) != 2:
        print("Usage: python build_callgraph.py <input_file>")
        return

    path = sys.argv[1]

    # Use fast version by default
    G = build_graph_fast(path)

    print(f"Nodes: {G.number_of_nodes()}")
    print(f"Edges: {G.number_of_edges()}")

    # example: print top edges by weight
    top_edges = sorted(G.edges(data=True), key=lambda x: x[2]["weight"], reverse=True)[:10]
    for u, v, d in top_edges:
        print(f"{u} -> {v}: {d['weight']}")
    #draw_graph(G)
    #H = weakly_connected_subgraph(G, '_raw_spin_unlock_irqrestore', radius=2)
    H = weakly_connected_subgraph(G, 'kmalloc', radius=3)
    #write_dot(H, "subgraph.dot")
    write_function_callgraph_dot(H, "/vol/os/linux/vmlinux", "ego-kmalloc.dot")

if __name__ == "__main__":
    main()
