import os
import pickle
import queue
import subprocess
import webbrowser
import dearpygui.dearpygui as dpg
from flamegraph import *
from pathlib import Path
from urllib.parse import quote

from vscode_bridge import VSCodeBridge


def remove_item(tag):
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

class Application:
    def __init__(self, flamegraphs_file="flamegraphs.pickle"):
        with open(flamegraphs_file, "rb") as f:
            self.fgs = pickle.load(f)

        self.active_node = None
        self.hovered_node = None
        self.current_comm = None
        self.source_path = None
        self.source_line = None
        self.pending_commands = queue.Queue()
        self.bridge = None

        from debugger import Debugger
        self.dbg = Debugger(os.environ["SOURCE_EXE"])

        self._start_bridge()

    def _start_bridge(self):
        port = int(os.environ.get("VSCODE_BRIDGE_PORT", "8765"))

        def on_command(payload):
            self.pending_commands.put(payload)

        self.bridge = VSCodeBridge(port=port, on_command=on_command)
        self.bridge.start()
        print(f"VS Code bridge listening on http://127.0.0.1:{port}")

    def _process_pending_commands(self):
        while True:
            try:
                payload = self.pending_commands.get_nowait()
            except queue.Empty:
                return

            action = payload.get("action")
            if action == "select_function":
                name = payload.get("function")
                if name:
                    node = self._find_node_by_function_name(name)
                    if node is not None:
                        self.select_node(node)
            elif action == "select_location":
                path = payload.get("path")
                line = payload.get("line")
                if path and line is not None:
                    node = self._find_node_by_pathline(path, int(line))
                    if node is not None:
                        self.select_node(node)

    def _find_node_by_function_name(self, function_name):
        if self.current_comm is None:
            return None
        root = self.fgs.roots.get(self.current_comm)
        if root is None:
            return None

        target = function_name.strip()

        stack = [root]
        while stack:
            node = stack.pop()
            dso, name = self.fgs.idx_to_name.get(node.func_id, (None, None))
            if name == target:
                return node
            stack.extend(node.children.values())

        return None

    def _find_node_by_pathline(self, path, line):
        if self.current_comm is None:
            return None
        root = self.fgs.roots.get(self.current_comm)
        if root is None:
            return None

        normalized_path = str(Path(path).resolve())
        best = None
        best_dist = None

        stack = [root]
        while stack:
            node = stack.pop()
            pathline = self.fgs.id_to_path.get(node.func_id)
            if pathline and ":" in pathline and not pathline.startswith("["):
                node_path, _, node_line = pathline.rpartition(":")
                try:
                    node_path = str(Path(node_path).resolve())
                    node_line = int(node_line)
                except Exception:
                    node_path = None

                if node_path == normalized_path:
                    dist = abs(node_line - int(line))
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best = node

            stack.extend(node.children.values())

        return best

    def _open_in_vscode(self, path, line):
        if not path:
            return
        try:
            line = int(line)
        except Exception:
            line = 1

        abspath = str(Path(path).resolve())
        cmd = ["code", "--goto", f"{abspath}:{line}"]
        try:
            subprocess.run(cmd, check=False)
            return
        except FileNotFoundError:
            pass

        uri = f"vscode://file/{quote(abspath)}:{line}"
        webbrowser.open(uri)

    def select_node(self, node):
        old_active = self.active_node
        if node is not None:
            self.active_node = node
        if node != old_active:
            self.draw_flamegraph(self.active_node)
            self.set_source(self.active_node)

    def hover_node(self, node):
        old_hover = self.hovered_node
        if node is not None:
            self.hovered_node = node
        if node != old_hover:
            self.set_source(self.hovered_node)

    def set_source(self, node):
        self.source_path = None
        self.source_line = None

        if node is None:
            return

        pathline = self.fgs.id_to_path.get(node.func_id)
        print(pathline)
        if pathline is None:
            return

        if pathline.startswith("["):
            remove_item("source-container")
            with dpg.child_window(width=-1, height=-1, border=False, tag="source-container", parent="source-window"):
                dpg.add_text(pathline)
            return

        line_hist = self.dbg.byte_to_line_histogram(
            node.counter,
            self.fgs.idx_to_name[node.func_id][1]
        )

        total_samples = sum(node.counter.values())
        if total_samples == 0:
            total_samples = 1  # avoid division by zero


        from pprint import pp
        pp(self.dbg.byte_to_line_histogram(node.counter, self.fgs.idx_to_name[node.func_id][1]))

        path, _, line_no = pathline.rpartition(':')
        self.source_path = path
        self.source_line = int(line_no)
        try:
            with open(path, 'r') as f:
                full_lines = f.readlines()
                header = full_lines[int(line_no)-3:int(line_no)]
                lines = full_lines[int(line_no):int(line_no) + 200]
        except (OSError, ValueError):
            remove_item("source-container")
            with dpg.child_window(width=-1, height=-1, border=False, tag="source-container", parent="source-window"):
                dpg.add_text(pathline)
                dpg.add_button(
                    label="Open in VS Code",
                    callback=lambda s, a, u: u[0]._open_in_vscode(u[1], u[2]),
                    user_data=(self, path, int(line_no)),
                )
            return

        display_lines = []
        for i, line in enumerate(lines, start=1):  # lines start at 1
            count = line_hist.get(i, 0)
            percent = int(count * 100 / total_samples)
            if percent > 0:
                display_line = f"{percent:>3}% {line}"
            else:
                display_line = f"    {line}"  # align lines with no samples
            display_lines.append(display_line)

        remove_item("source-container")
        with dpg.child_window(width=-1, height=-1, border=False, tag="source-container", parent="source-window"):
            rel_path = path
            try:
                rel_path = str(Path(path).relative_to(base_dir))
            except ValueError:
                pass
            dpg.add_text(f"{rel_path}:{line_no}")
            dpg.add_button(
                label="Open in VS Code",
                callback=lambda s, a, u: u[0]._open_in_vscode(u[1], u[2]),
                user_data=(self, path, int(line_no)),
            )
            dpg.add_separator()
            dpg.add_text(''.join(header))
            dpg.add_text(''.join(display_lines))


    def draw_flamegraph(self, root):
        WIDTH = parent_width = dpg.get_item_width("flamegraph-window")
        WINDOW_HEIGHT = parent_height = dpg.get_item_height("flamegraph-window")
        RECT_HEIGHT=20
        rects = []

        # --- find ancestors ---
        ancestors = []
        current = root.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        ancestors.reverse()

        start_depth = len(ancestors)

        layout(root, 0, WIDTH - 40, start_depth, rects)
        ancestor_rects = [(node, 0, WIDTH - 40, i) for i, node in enumerate(ancestors)]
        rects_to_render = ancestor_rects + rects

        # --- draw child window ---
        remove_item("flamegraph-container")

        with dpg.child_window(width=-1, height=-1, border=False, tag="flamegraph-container", parent="flamegraph-window"):
            # invert y so depth 0 is at bottom
            max_depth = max(depth for _, _, _, depth in rects_to_render) if rects_to_render else 0
            # compute total used height
            total_height = (max_depth + 1) * RECT_HEIGHT
            y_offset = max(0, WINDOW_HEIGHT - total_height)  # push down if smaller than window

            for i, (node, x0, x1, depth) in enumerate(rects_to_render):
                width = max(x1 - x0, 1)
                y = (max_depth - depth) * RECT_HEIGHT + y_offset

                label = self.fgs.func_label(node.func_id) if width > 60 else ""
                if node.parent is None:
                    label = "[all]"

                tag = f"func_button_{i}"

                # get path for coloring
                path = self.fgs.id_to_path.get(node.func_id, "[unknown]")
                rgb = pc.color(path)
                color = [int(c*255) for c in rgb] + [255]

                with dpg.theme() as color_theme:
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, tuple(color))
                        dpg.add_theme_color(dpg.mvThemeCol_Text, (0,0,0,255))  # black text

                remove_item(f"flamegraph_hover_handler_{i}")
                def hover_callback(sender, app_data, user_data):
                    self.hover_node(user_data)
                with dpg.item_handler_registry(tag=f"flamegraph_hover_handler_{i}") as handler:
                    dpg.add_item_hover_handler(callback=hover_callback, user_data=node)

                dpg.add_button(
                    label=label,
                    pos=(x0, y),
                    width=width,
                    height=RECT_HEIGHT,
                    callback=lambda s,a,u: u[0].select_node(u[1]),
                    user_data=(self, node),
                    tag=tag
                )
                dpg.bind_item_handler_registry(tag, f"flamegraph_hover_handler_{i}")
                dpg.bind_item_theme(tag, color_theme)
                dpg.set_y_scroll("flamegraph-container", max_depth * RECT_HEIGHT)

        # auto-scroll to bottom
        dpg.set_y_scroll("flamegraph-container", max_depth * RECT_HEIGHT)
        #dpg.set_primary_window("flamegraph-window", True)

    def run(self):
        dpg.create_context()


        with dpg.window(label="Flamegraph", tag="flamegraph-window", width=1400, height=1000):
            totals = {k: self.fgs.roots[k].total() for k in self.fgs.roots}
            grand_total = sum(totals.values()) or 1  # avoid div by zero

            items = sorted(totals, key=totals.get, reverse=True)
            labels = {
                f"{k} ({totals[k] / grand_total:.1%})": k
                for k in items
            }

            def on_select(sender, app_data):
                key = labels[app_data]
                 
                self.current_comm = key
                self.select_node(self.fgs.roots[key])

            dpg.add_combo(list(labels.keys()), callback=on_select, default_value=next(iter(labels.keys())))
            pc.draw_legend()
            dpg.add_button(label="Refresh", callback=lambda s, a, u: u.select_node(None), user_data=self)
            on_select(None, next(iter(labels.keys())))

        with dpg.window(label="Function snippet", tag="source-window", height=800, width=400):
            pass


        dpg.create_viewport(title="Flamegraph", width=1500, height=900)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        while dpg.is_dearpygui_running():
            self._process_pending_commands()
            dpg.render_dearpygui_frame()

        if self.bridge is not None:
            self.bridge.stop()

        dpg.destroy_context()

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


Application().run()
