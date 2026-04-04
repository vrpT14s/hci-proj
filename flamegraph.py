from debugger import Debugger

class Flamegraphs:
    def __init__(self, callstack_dict, name_table, executable_path):
        self.name_table = name_table
        print("Merging stacks")
        self.roots = {comm: build_flamegraph(stacks) for (comm, stacks) in callstack_dict.items()}
        self.idx_to_name = {v: k for k, v in self.name_table.items()}
        self.dbg = Debugger(executable_path)
        self.id_to_path = {}
        print("looking up file paths")
        for (dso, func_name), fid in self.name_table.items():
            if func_name is None and dso is None:
                path = "[unknown]"
            elif func_name is None:
                path = f"[{dso}]"
            else:
                path = self.dbg.lookup_symbol_location(func_name) or f"[{dso}]"
            self.id_to_path[fid] = path
        self.dbg = None #idk if it can be pickled

    def func_label(self, func_id):
        dso, name = self.idx_to_name.get(func_id, (None, None))

        if dso is None and name is None:
            return "[unknown]"

        if name is None:
            return f"[{dso}]"

        return name

    def dump(self, filename):
        with open(filename, 'wb') as f:
            pickle.dump(self, filename)

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
