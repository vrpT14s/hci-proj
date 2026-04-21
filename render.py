import tkinter as tk
from pprint import pp
import sys
import os
from debugger import Debugger
import pickle
from flamegraph import *
from folder_tree import FolderTree
from pathlib import Path
#from color_flamegraph import Colorizer
from view.flamegraph_view import *
from view.dso_color_view import *
from view.folder_color_view import *
from view.sandwich_view import *
from request_editor import *

class Application:
    def __init__(self, root, bottom_right, flamegraph_file, diff_flamegraph_file=None):
        fg = load_flamegraph(flamegraph_file)
        diff_fg = load_flamegraph(diff_flamegraph_file) if diff_flamegraph_file else None

        self.fgv = FlamegraphView(fg, diff_fg, list(fg.roots.keys())[int(sys.argv[2])], root)
        self.ft = FolderTree(fg, self.fgv.current_node)
        self.dbg = Debugger()
        self.dcv = DsoColorView(self.fgv.fg, palette_name='kelley')
        self.fcv = FolderColorView(self.ft, palette_name='tableau', right_cb=self.path_menu)
        self.color_strategy = self.fcv
        self.sv = SandwichView(self.fgv.fg, self.fgv.current_node, bottom_right, self.color_strategy)

        def select_cb(node):
            self.fgv.current_node = node
            self.fcv.update_current_path(self.ft.get_pathfunc(node))
            print(self.ft.get_pathfunc(node))
            self.fgv.draw()
            editor_jump_to_node(self.fgv.fg, node)
        self.fgv.set_select_cb(select_cb)
        self.fgv.set_color_cb(self.color_strategy.color)
        self.fgv.set_magnify_cb(self.node_menu)



    def node_menu(self, node, event):
        menu = tk.Menu(root, tearoff=0)

        def rebase_color():
            print("set as root")
            self.fgv.magnified_node = node
            self.refresh()

        def reset_color():
            print("set as root")
            self.fgv.magnified_node = self.fgv.root
            self.refresh()

        def rebase_sandwich():
            print("set as sandwich node")
            self.sv.set_sandwich_node(node.func_id)
            self.refresh(keep_top_paths=True)

        menu.add_command(label="Set as color root", command=rebase_color)
        menu.add_command(label="Set as sandwich node", command=rebase_sandwich)
        menu.add_separator()
        menu.add_command(label="Reset color", command=reset_color)

        menu.tk_popup(event.x_root, event.y_root)

    def path_menu(self, path, event):
        menu = tk.Menu(root, tearoff=0)

        def reset_color():
            print("set as root")
            self.fgv.magnified_node = self.fgv.root
            self.refresh()

        def color_path():
            print("set as root")
            self.fcv.top_paths = [path]
            self.refresh(keep_top_paths=True)

        menu.add_command(label="Color path", command=color_path)
        menu.add_separator()
        menu.add_command(label="Reset color", command=reset_color)

        menu.tk_popup(event.x_root, event.y_root)

    def refresh(self, keep_top_paths=False):
        self.ft.rebuild(self.fgv.magnified_node)
        if not keep_top_paths:
            self.fcv.reset_top_paths()
        self.color_strategy.draw_legend(top_right)
        self.fgv.draw()
        self.sv.draw()

    def draw_control_panel(self, parent):
        # --- container ---
        ctrl = tk.Frame(parent)
        ctrl.pack(fill='x', side='top', padx=5, pady=5)

        roots = self.fgv.fg.roots
        total_samples = sum(v.total() for v in roots.values()) or 1
        comms = sorted(roots.keys(), key=lambda c: roots[c].total(), reverse=True)
        comm_labels = [f"{c} ({roots[c].total() / total_samples * 100:.1f}%)" for c in comms]
        self._comm_map = dict(zip(comm_labels, comms))

        # --- ROW 1: Comm Selection ---
        row1 = tk.Frame(ctrl)
        row1.pack(fill='x', side='top', pady=2)

        tk.Label(row1, text="Select comm:").pack(side='left')

        self._selected_comm = tk.StringVar()
        if comm_labels:
            self._selected_comm.set(comm_labels[0])

        def update_comm(*_):
            label = self._selected_comm.get()
            comm = self._comm_map.get(label)
            if not comm: return
            node = roots[comm]
            self.fgv.current_node = node
            self.fgv.magnified_node = node
            self.fgv.root = node
            self.sv.set_root(node)
            self.refresh()

        dropdown = ttk.OptionMenu(
            row1, # Attached to row1
            self._selected_comm,
            self._selected_comm.get(),
            *comm_labels,
            command=lambda _: update_comm()
        )
        dropdown.pack(side='left', padx=5)

        # --- ROW 2: Coloring Mode ---
        row2 = tk.Frame(ctrl)
        row2.pack(fill='x', side='top', pady=2)

        tk.Label(row2, text="Coloring:").pack(side='left')

        self._color_mode = tk.StringVar()
        self._color_mode.set("Folder")

        def update_color_mode(*_):
            mode = self._color_mode.get()
            old_color_strategy = self.color_strategy
            self.color_strategy = self.dcv if mode == "DSO" else self.fcv
            if old_color_strategy != self.color_strategy or mode == "DSO":
                self.fcv.reset_drawing()
            self.fgv.set_color_cb(self.color_strategy.color)
            self.refresh(keep_top_paths=True)

        color_dropdown = ttk.OptionMenu(
            row2, # Attached to row2
            self._color_mode,
            self._color_mode.get(),
            "Folder",
            "DSO",
            command=lambda _: update_color_mode()
        )
        color_dropdown.pack(side='left', padx=5)

        # initial update
        update_comm()


if __name__ == '__main__':
    root = tk.Tk()
    root.title("Flamegraph Profiler")

    # Create a horizontal paned window
    paned = tk.PanedWindow(root, orient=tk.HORIZONTAL)
    paned.pack(fill=tk.BOTH, expand=True)

    # Left frame (75%)
    left_frame = tk.Frame(paned, bg="white")  # this is where your flamegraph goes
    paned.add(left_frame, stretch="always")   # main area expands

    right_frame = tk.Frame(paned, bg="gray")
    paned.add(right_frame)

    # Right frame becomes another paned window
    right_paned = tk.PanedWindow(right_frame, orient=tk.VERTICAL)
    right_paned.pack(fill=tk.BOTH, expand=True)

    control_panel = tk.Frame(right_paned)
    right_paned.add(control_panel)

    right_data = tk.PanedWindow(right_paned, orient=tk.VERTICAL)
    #right_data.pack(fill=tk.BOTH, expand=True)
    right_paned.add(right_data, stretch="always")

    # Top-right pane
    top_right = tk.Frame(right_data, bg="lightgray")
    right_data.add(top_right, stretch="always")

    # Bottom-right pane
    bottom_right = tk.Frame(right_data, bg="lightgray")
    right_data.add(bottom_right)

    # Optional: set initial split (e.g. 50/50)
    root.update_idletasks()
    total_height = right_paned.winfo_height() or 600
    right_paned.sash_place(0, 0, int(total_height * 0.5))

    total_height = right_paned.winfo_height()
    split = int(total_height * 0.1)
    right_paned.sash_place(0, 0, split)

    # Set initial size ratio (~75%)
    #root.update_idletasks()
    total_width = root.winfo_width() or 800
    paned.sash_place(0, int(total_width * 0.75), 0)

    app = Application(left_frame, bottom_right, sys.argv[1])
    app.color_strategy.draw_legend(top_right)
    app.fgv.draw()
    #app.dcv.draw_legend(bottom_right)
    #app.fcv.draw_tree(top_right)
    app.sv.draw()
    app.draw_control_panel(control_panel)

    root.mainloop()
