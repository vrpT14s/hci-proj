#courtesy of sam altman
class FlameNode:
    __slots__ = ("func_id", "counter", "children")

    def __init__(self, func_id):
        self.func_id = func_id
        self.counter = {}          # {offset_bytes: count}
        self.children = {}         # {func_id: FlameNode}

    def add_sample(self, offset):
        c = self.counter
        c[offset] = c.get(offset, 0) + 1

    def get_or_create_child(self, func_id):
        children = self.children
        if func_id not in children:
            children[func_id] = FlameNode(func_id)
        return children[func_id]

    def pretty(self, indent=0):
        pad = "  " * indent

        total = sum(self.counter.values())
        print(f"{pad}{self.func_id} [{total}] {self.counter}")

        for child in self.children.values():
            child.pretty(indent + 1)

def build_flamegraph(stacks):
    root = FlameNode(-1)
    prev_stack = []
    stack_nodes = [root]

    for stack in stacks:
        # 1. longest common prefix
        lcp = 0
        for a, b in zip(prev_stack, stack):
            if a[0] != b[0]:
                break
            lcp += 1

        # 2. trim current path
        stack_nodes = stack_nodes[:lcp + 1]

        # 3. extend path
        for i in range(lcp, len(stack)):
            func_id, _ = stack[i]
            parent = stack_nodes[-1]
            node = parent.get_or_create_child(func_id)
            stack_nodes.append(node)

        # 4. update counters
        for node, (_, offset) in zip(stack_nodes[1:], stack):
            node.add_sample(offset)

        prev_stack = stack

    return root


import os
import pickle
from perf_parser import PerfParser

with open(os.environ.get("PICKLE_FILE", "callstacks.pickle"), 'rb') as f:
    parser = pickle.load(f)
callstacks = parser.callstacks

for comm in callstacks:
    callstacks[comm] = build_flamegraph(callstacks[comm])
breakpoint()
