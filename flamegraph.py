from debugger import Debugger
import pickle
import heapq
from pathlib import Path

class Flamegraph:
    def __init__(self, callstack_dict, name_table):
        self.pair_to_number = name_table
        self.roots = {comm: build_flamegraph(stacks) for (comm, stacks) in callstack_dict.items()}
        self.number_to_pair = {v: k for k, v in self.pair_to_number.items()}
        self.dbg = Debugger()
        self.number_to_path = {}
        print("looking up file paths")
        for (dso, func_name), number in self.pair_to_number.items():
            path = None
            if dso is not None and func_name is not None:
                path_and_line = self.dbg.lookup_symbol_location(dso, func_name)
                if path_and_line:
                    path_string, _, line = path_and_line.rpartition(':')
                    path = (Path(path_string), line)
                    print(f"{dso}:{func_name}\t-> {path}")
            self.number_to_path[number] = path
        self.dbg = None #idk if it can be pickled

    def get_number_to_pair(self, number):
        return self.number_to_pair.get(number)

    def get_number_to_path(self, number):
        return self.number_to_path.get(number)

    def get_pair_to_path(self, pair):
        return self.number_to_path(self.pair_to_number.get(pair))

    def get_display_name(self, number):
        dso, name = self.number_to_pair.get(number, (None, None))

        if dso is None and name is None:
            return "[unknown]"

        if name is None:
            return f"[{dso}]"

        return name

    def node_get_histogram(self, node):
        if self.dbg is None:
            self.dbg = Debugger()
        return self.dbg.byte_to_line_histogram(node.counter, self.node_pair(node))

    def node_path(self, node):
        return self.get_number_to_path(node.func_id)

    def node_pair(self, node):
        return self.number_to_pair.get(node.func_id)

    def node_display_name(self, node):
        return self.get_display_name(node.func_id)

    def dump(self, filename):
        with open(filename, 'wb') as f:
            pickle.dump(self, filename)

    #diffing
    def get_proportion_of_name(self, name_key, root):
        """Helper to find a node by name in a tree and return its total/root_total"""
        total_samples = root.total()
        if total_samples == 0: return 0.0

        # Search for node with this name key (dso, func)
        # Note: In a deep tree, you might want to cache this search
        target_total = 0
        stack = [root]
        while stack:
            curr = stack.pop()
            if self.number_to_pair.get(curr.func_id) == name_key:
                target_total = curr.total()
                break
            stack.extend(curr.children.values())

        return target_total / total_samples

    def get_color_for_diff(self, score):
        """
        Maps score [-1.0, 1.0] to Hex Color
        Positive (Grown): Red
        Negative (Shrunk): Blue
        Zero: White/Grey
        """
        # Clamp score just in case
        score = max(-1.0, min(1.0, score))

        # Intensity 0-255
        intensity = int(abs(score) * 255)
        remaining = 255 - intensity

        if score > 0:
            # Shift towards Red: (255, remaining, remaining)
            return f"#{255:02x}{remaining:02x}{remaining:02x}"
        elif score < 0:
            # Shift towards Blue: (remaining, remaining, 255)
            return f"#{remaining:02x}{remaining:02x}{255:02x}"
        else:
            return "#ffffff"

    def diff_with(self, old_flamegraph):
        """
        Returns a dict: { FlameNode: color_hex }
        """
        node_colors = {}

        for comm, root in self.roots.items():
            if comm not in old_flamegraph.roots:
                # If command is entirely new, everything is 1.0 (Red)
                self._fill_color_recursive(root, "#ff0000", node_colors)
                continue

            old_root = old_flamegraph.roots[comm]
            old_total = old_root.total()
            new_total = root.total()

            stack = [(root)]
            while stack:
                curr = stack.pop()
                name_key = self.number_to_pair.get(curr.func_id)

                # Get the proportion this function took in the old run
                # We use the old_flamegraph's lookup logic
                old_prop = old_flamegraph.get_proportion_of_name(name_key, old_root)
                new_prop = curr.total() / new_total if new_total > 0 else 0

                if old_prop == 0 and new_prop > 0:
                    score = 1.0
                elif new_prop == 0 and old_prop > 0:
                    score = -1.0
                elif old_prop == 0 and new_prop == 0:
                    score = 0.0
                else:
                    # Normalized difference
                    score = (new_prop - old_prop) / max(new_prop, old_prop)

                node_colors[curr] = self.get_color_for_diff(score)
                stack.extend(curr.children.values())

        return node_colors

    def _fill_color_recursive(self, node, color, color_map):
        color_map[node] = color
        for child in node.children.values():
            self._fill_color_recursive(child, color, color_map)

class FlameNode:
    __slots__ = ("func_id", "counter", "children", "parent")

    def __init__(self, func_id, parent=None):
        self.func_id = func_id
        self.counter = {}
        self.children = {}
        self.parent = parent

    def add_sample(self, offset):
        self.counter[offset] = self.counter.get(offset, 0) + 1

    def get_or_create_child(self, func_id):
        if func_id not in self.children:
            self.children[func_id] = FlameNode(func_id, self)
        return self.children[func_id]

    def total(self):
        if self.parent is None:
            return sum(c.total() for c in self.children.values())
        return sum(self.counter.values())

def build_flamegraph(stacks):
    root = FlameNode(None)

    prev_stack = []
    stack_nodes = [root]

    for stack in stacks:
        # LCP
        lcp = 0
        for a, b in zip(prev_stack, stack):
            if a[0] != b[0]:
                break
            lcp += 1

        stack_nodes = stack_nodes[:lcp + 1]

        # extend
        for i in range(lcp, len(stack)):
            func_id, _ = stack[i]
            parent = stack_nodes[-1]
            node = parent.get_or_create_child(func_id)
            stack_nodes.append(node)

        # update counters
        for node, (_, offset) in zip(stack_nodes[1:], stack):
            if offset is None or node == stack_nodes[-1]:
                node.add_sample(offset)
            else:
                node.add_sample(offset-1)


        prev_stack = stack

    return root

def layout(node, x0, x1, depth, rects):
    total = node.total()
    if total == 0:
        return

    rects.append((node, x0, x1, depth))

    cur_x = x0
    for child in node.children.values():
        w = (child.total() / total) * (x1 - x0)
        layout(child, cur_x, cur_x + w, depth + 1, rects)
        cur_x += w

def load_flamegraph(filepath):
    with open(filepath, 'rb') as f:
        return pickle.load(f)
