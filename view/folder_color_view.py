from folder_tree import *
from view.palette import Palette

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

class FolderColorView:
    def __init__(self, foldertree, right_cb, palette_name=None):
        self.ft = foldertree
        self.top_paths = None
        self.palette = Palette(palette_name)
        self.right_cb = right_cb
        from pprint import pp
        pp(self.top_paths)
        self.current_path = None

        self.show_all_folders = tk.BooleanVar(value=False)
        self.reset_top_paths()

    def color(self, node):
        if self.top_paths is None:
            raise "need to draw_legend first"
        node_path = self.ft.get_pathfunc(node)
        if node_path is None:
            return '#efefef'
        for (i, top_path) in enumerate(self.top_paths):
            if node_path.is_relative_to(top_path):
                return self.palette.get_color(i)
        return '#7f7f7f'

    def reset_top_paths(self):
        self.top_paths = self.ft.top_independent_paths()

    def reset_drawing(self):
        self._legend_tree = None

    def get_bridge_paths(self, current_path):
        bridge_paths = set()
        for path_str in self.top_paths + [current_path]:
            if not path_str:
                continue
            p = Path(path_str)
            for parent_path in p.parents:
                bridge_paths.add(str(parent_path))
        return bridge_paths

    def update_current_path(self, new_path):
        if new_path is None:
            return

        tree = getattr(self, "_legend_tree", None)
        if tree is None:
            return

        new_path = Path(new_path)
        old_path = self.current_path
        self.current_path = new_path

        bridge_paths = self.get_bridge_paths(new_path)

        def find_existing(path):
            """Map a real path to the nearest visible (possibly compressed) node."""
            p = Path(path)
            while True:
                p_str = str(p)
                if tree.exists(p_str):
                    return p_str
                if p == p.parent:
                    return None
                p = p.parent

        visited = set()  # avoid updating same compressed node multiple times

        def update_path_chain(path):
            if path is None:
                return
            for p in path.parents:
                node_id = find_existing(p)
                if node_id is None or node_id in visited:
                    continue

                visited.add(node_id)

                if node_id in bridge_paths:
                    tree.item(node_id, open=True)
                else:
                    tree.item(node_id, open=False)

        # Update only affected chains
        update_path_chain(old_path)
        update_path_chain(new_path)

        node_id = find_existing(new_path)
        if node_id is not None:
            tree.selection_set(node_id)
            tree.see(node_id)

    def draw_legend(self, parent):
        print(f"drawing legend for {self.top_paths}")
        tree = getattr(self, "_legend_tree", None)

        if tree is not None:
            tree.delete(*tree.get_children())  # clear rows only
        else:
            for child in parent.winfo_children():
                child.destroy()

            ctrl_frame = tk.Frame(parent)
            ctrl_frame.pack(fill='x', side='top')

            chk = tk.Checkbutton(
                ctrl_frame, text="Show Unmarked Folders",
                variable=self.show_all_folders,
                command=lambda: self.draw_legend(parent)
            )
            chk.pack(side='left', padx=5, pady=2)


            # 6. Widget Setup
            tree = ttk.Treeview(parent, columns=("area"), selectmode="browse")
            tree.heading("#0", text="Folder Structure", anchor="w")
            tree.heading("area", text="Usage %", anchor="w")
            tree.column("area", width=80, stretch=False)

            vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=vsb.set)
            vsb.pack(side='right', fill='y')
            tree.pack(side='left', fill='both', expand=True)
            self._legend_tree = tree

        def on_right_click(event):
            tree = self._legend_tree

            row_id = tree.identify_row(event.y)
            if not row_id:
                return

            path = row_id  # because iid == path

            # optional: select row for UX clarity
            tree.selection_set(row_id)

            self.right_cb(path, event)

        tree.bind("<Button-3>", on_right_click)

        bridge_paths = self.get_bridge_paths(self.current_path)

        # 7. Tags
        for i, _ in enumerate(self.top_paths):
            color = self.palette.get_color(i)
            tree.tag_configure(f"top_{i}", background=color, foreground="black")
        tree.tag_configure("default", foreground="#7f7f7f")

        # 8. Recursive Insertion
        total_area = max(self.ft.inodes['/'].area, 1)

        def insert_node(current_path, parent_id):
            node = self.ft.inodes[current_path]

            # Determine if this node belongs to a colored path
            assigned_tag = "default"
            is_colored = False
            for i, tp in enumerate(self.top_paths):
                if current_path == tp or Path(current_path).is_relative_to(tp):
                    assigned_tag = f"top_{i}"
                    is_colored = True
                    break

            # --- PRUNING LOGIC ---
            # If filtering is ON:
            # Only keep if it is colored OR it is a bridge to a colored path
            if not self.show_all_folders.get():
                is_bridge = current_path in bridge_paths
                if not (is_colored or is_bridge):
                    return

            # --- PATH COMPACTION ---
            display_name = Path(current_path).name or current_path
            while len(node.children) == 1 and current_path not in self.top_paths:
                child_name = list(node.children)[0]
                current_path = str(Path(current_path) / child_name)
                display_name = str(Path(display_name) / child_name)
                node = self.ft.inodes[current_path]

                # Re-check color after compaction in case we swallowed a top_path
                for i, tp in enumerate(self.top_paths):
                    if current_path == tp or Path(current_path).is_relative_to(tp):
                        assigned_tag = f"top_{i}"
                        break

            # --- INSERT ---
            pct_str = f"{(node.area / total_area * 100):.1f}%" if node.area > 0 else ""
            # Keep bridge paths open so you can see the colored children
            should_open = current_path in bridge_paths

            node_id = tree.insert(
                parent_id, "end", text=display_name,
                iid=current_path,
                values=(pct_str,), tags=(assigned_tag,), open=should_open
            )

            # --- RECURSE ---
            sorted_children = sorted(
                node.children,
                key=lambda c: self.ft.inodes[str(Path(current_path)/c)].area,
                reverse=True
            )

            for child_name in sorted_children:
                child_path = str(Path(current_path) / child_name)
                if child_path in self.ft.inodes:
                    insert_node(child_path, node_id)

        # Kick off from root
        insert_node('/', "")
