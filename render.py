import pickle
import dearpygui.dearpygui as dpg

# ---------------- Load data ---------------- #

from perf_parser import PerfParser  # your class

with open("callstacks.pickle", "rb") as f:
    perf = pickle.load(f)

#--- debugger ---

from debugger import Debugger
import os
dbg = Debugger(os.environ.get("EXE", "/vol/os/linux/old-vmlinux-for-old-perf-data/vmlinux"))

groups = {
    "net": ["net", "drivers/net"],
    "memory": ["mm"],
    "fs": ["fs"],
    "core": ["kernel"],
    "arch": ["arch"]
}

# Optional overrides: RGB tuples (0–1 range)
overrides = {
    "net": (1.0, 0.0, 0.0),      # force net group red
    "misc": (0.8, 0.8, 0.8),     # misc white
}

# Optional: base directory to strip from paths
base_dir = "/vol/os/linux"

from color_flamegraph import PathColorizer
# Initialize PathColorizer
pc = PathColorizer(groups=groups, base_dir_root=base_dir, overrides=overrides)

# ---------------- Reverse function map ---------------- #

# (dso, func_name) -> id  ==>  id -> (dso, func_name)
id_to_func = {v: k for k, v in perf.function_names.items()}

# first, create a function id -> path lookup
id_to_path = {}
for (dso, func_name), fid in perf.function_names.items():
    # lookup full location using Debugger
    if func_name is None and dso is None:
        path = "[unknown]"
    elif func_name is None:
        path = f"[{dso}]"
    else:
        # use your debugger to resolve location path
        path = dbg.lookup_symbol_location(func_name) or f"[{dso}]"
    id_to_path[fid] = path


def func_label(func_id):
    dso, name = id_to_func.get(func_id, (None, None))

    if dso is None and name is None:
        return "[unknown]"

    if name is None:
        return f"[{dso}]"

    return name


# ---------------- Flamegraph structures ---------------- #

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
        return sum(self.counter.values())


# ---------------- Builder ---------------- #

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
            node.add_sample(offset)

        prev_stack = stack

    return root


# ---------------- Layout ---------------- #

RECT_HEIGHT = 20
WIDTH = 1400


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


# ---------------- Rendering ---------------- #

def remove_item(tag):
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

RECT_HEIGHT = 20
WIDTH = 1400
WINDOW_HEIGHT = 800  # used for scrolling

def draw_flamegraph(root):
    print(f"drawing for item {root}")
    rects = []

    # --- find ancestors ---
    ancestors = []
    current = root
    while current is not None:
        ancestors.append(current)
        current = current.parent
    ancestors.reverse()  # root-most ancestor first

    # starting depth is number of ancestors
    start_depth = len(ancestors)

    # --- layout subtree ---

    if root.parent is None:
        total = sum(c.total() for c in root.children.values())
    else:
        total = root.total()
    cur_x = 0
    for child in root.children.values():
        w = (child.total() / total) * WIDTH if total > 0 else WIDTH
        layout(child, cur_x, cur_x + w, start_depth, rects)  # start_depth passed here
        cur_x += w

    # --- combine ancestors as full-width rects ---
    ancestor_rects = [(node, 0, WIDTH, i) for i, node in enumerate(ancestors)]
    rects_to_render = ancestor_rects + rects

    # --- draw child window ---
    remove_item("flamegraph-container")
    with dpg.child_window(width=WIDTH, height=WINDOW_HEIGHT, border=False, tag="flamegraph-container", parent="flamegraph-window"):
        print(f"drawing child window item {root}")

        # invert y so depth 0 is at bottom
        max_depth = max(depth for _, _, _, depth in rects_to_render) if rects_to_render else 0
        # compute total used height
        total_height = (max_depth + 1) * RECT_HEIGHT
        y_offset = max(0, WINDOW_HEIGHT - total_height)  # push down if smaller than window

        for i, (node, x0, x1, depth) in enumerate(rects_to_render):
            width = max(x1 - x0, 1)
            y = (max_depth - depth) * RECT_HEIGHT + y_offset

            label = func_label(node.func_id) if width > 60 else ""
            if node.parent is None:
                label = "[all]"

            tag = f"func_button_{i}"

            # get path for coloring
            path = id_to_path.get(node.func_id, "[unknown]")
            rgb = pc.color(path)
            color = [int(c*255) for c in rgb] + [255]

            with dpg.theme() as color_theme:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, tuple(color))
                    dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0,255))  # black text

            dpg.add_button(
                label=label,
                pos=(x0, y),
                width=width,
                height=RECT_HEIGHT,
                callback=lambda s,a,u: draw_flamegraph(u),
                user_data=node,
                tag=tag
            )
            dpg.bind_item_theme(tag, color_theme)
            dpg.set_y_scroll("flamegraph-container", max_depth * RECT_HEIGHT)

    # auto-scroll to bottom
    dpg.set_y_scroll("flamegraph-container", max_depth * RECT_HEIGHT)

# ---------------- Pick a command ---------------- #

# perf.callstacks: {command_name: [stacks]}
print("Available commands:")
for cmd in perf.callstacks:
    print(" -", cmd)

# just pick the first one for now
#command = next(iter(perf.callstacks))
command = "head"
#command = "perf"
print(f"\nUsing command: {command}")

stacks = perf.callstacks[command]

# IMPORTANT: ensure sorted
stacks.sort()

# ---------------- Build + run ---------------- #

root = build_flamegraph(stacks)

dpg.create_context()


with dpg.window(label="Flamegraph", tag="flamegraph-window"):
    draw_flamegraph(root)
pc.draw_legend()

dpg.create_viewport(title="Flamegraph", width=1500, height=900)
dpg.setup_dearpygui()
dpg.show_viewport()

while dpg.is_dearpygui_running():
    dpg.render_dearpygui_frame()

dpg.destroy_context()
