import tkinter as tk
from flamegraph import *

class FlamegraphView:
    class DrawContext:
        def __init__(self, parent, resize_cb):
            self.parent = parent
            self.RECT_HEIGHT = 20
            self.container = tk.Frame(parent)
            self.container.pack(fill="both", expand=True)

            self.canvas = tk.Canvas(self.container, bg="white", highlightthickness=0)
            self.scrollbar = tk.Scrollbar(self.container, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=self.scrollbar.set)

            self.canvas.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")

            self._resize_job = None
            parent.bind("<Configure>", self.on_resize)
            self.resize_cb = resize_cb

        def on_resize(self, event):
            if self._resize_job is not None:
                self.parent.after_cancel(self._resize_job)

            self._resize_job = self.parent.after(100, self.on_resize_done)

        def on_resize_done(self):
            print("Resize finished")
            self.resize_cb()

    def __init__(self, fg, dfg, comm, parent):
        self.fg = fg
        self.dfg = dfg
        self.comm = comm
        self.root = self.fg.roots[comm]
        self.current_node = self.root
        self.magnified_node = self.current_node

        self.ctx = self.DrawContext(parent, lambda: self.draw())
        self.select_node = self.default_select_node
        self.hover_node = self.default_select_node
        self.color_node = self.default_color_node
        self.magnify_node = self.default_select_node

    def set_select_cb(self, cb):
        self.select_node = cb
    def set_hover_cb(self, cb):
        self.hover_node = cb
    def set_color_cb(self, cb):
        self.color_node = cb
    def set_magnify_cb(self, cb):
        self.magnify_node = cb

    def draw(self):
        self.draw_root(self.current_node)

    def draw_root(self, root):
        self.ctx.canvas.addtag_all("garbage")
        self.ctx.canvas.delete("all")

        WIDTH = self.ctx.canvas.winfo_width()
        WINDOW_HEIGHT = self.ctx.canvas.winfo_height()

        rects = []

        ancestors = []
        current = root.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        ancestors.reverse()

        start_depth = len(ancestors)

        layout(root, 0, WIDTH - 5, start_depth, rects)

        ancestor_rects = [(node, 0, WIDTH - 5, i) for i, node in enumerate(ancestors)]
        rects_to_render = ancestor_rects + rects

        if not rects_to_render:
            return

        max_depth = max(depth for _, _, _, depth in rects_to_render)
        total_height = (max_depth + 1) * self.ctx.RECT_HEIGHT

        # Push down if the graph is smaller than the window (Your y_offset logic)
        y_offset = max(0, WINDOW_HEIGHT - total_height)

        # Set the scrollable region
        self.ctx.canvas.configure(scrollregion=(0, 0, WIDTH, total_height + y_offset))

        for i, (node, x0, x1, depth) in enumerate(rects_to_render):
            width = max(x1 - x0, 1)
            y = (max_depth - depth) * self.ctx.RECT_HEIGHT + y_offset

            label = self.fg.node_display_name(node) if width > 60 else ""
            if node.parent is None:
                label = "[all]"

            #rgb = self.colorizer.color(node)
            hex_color = self.color_node(node)

            rect_tag = f"node_{i}"
            self.ctx.canvas.create_rectangle(
                x0, y, x0 + width, y + self.ctx.RECT_HEIGHT,
                fill=hex_color, outline="black", tags=rect_tag
            )
            if node == self.magnified_node:
                self.ctx.canvas.create_rectangle(
                    x0, y + 1, x0 + width, y + self.ctx.RECT_HEIGHT - 1,
                    outline="blue")
            if node == root:
                self.ctx.canvas.create_rectangle(
                    x0, y + 1, x0 + width, y + self.ctx.RECT_HEIGHT - 1,
                    outline="red")


            self.draw_text_in_box(x0, y, width, self.ctx.RECT_HEIGHT, label)

            self.ctx.canvas.tag_bind(rect_tag, "<Button-1>", lambda e, n=node: self.select_node(n))
            self.ctx.canvas.tag_bind(rect_tag, "<Enter>", lambda e, n=node: self.hover_node(n))
            self.ctx.canvas.tag_bind(rect_tag, "<Button-3>", lambda e, n=node: self.magnify_node(n, e))

        self.ctx.canvas.delete("garbage")
        # Auto-scroll to bottom
        self.ctx.canvas.yview_moveto(1.0)


    def draw_text_in_box(self, x0, y, width, height, text, color="black"):
        """Draws centered, truncated text within a canvas rectangle."""
        if not text or width < 10:  # Don't bother if box is tiny
            return

        # Calculate the center point of the box
        center_x = x0 + (width / 2)
        center_y = y + (height / 2)

        # Manual Ellipsis: Adjust '8' based on your font size/style
        # This is a rough character-width estimate
        max_chars = int(width / 9)

        if len(text) > max_chars:
            if max_chars > 3:
                display_text = f"{text[:max_chars-3]}..."
            else:
                display_text = "" # Too small for even dots
        else:
            display_text = text

        if display_text:
            self.ctx.canvas.create_text(
                center_x,
                center_y,
                text=display_text,
                fill=color,
                font=("Arial", 10),
                anchor="center",
                state="disabled"
            )
    def default_select_node(self, node):
        print(f"Selected: {self.fg.get_number_to_pair(node.func_id)}")
    def default_hover_node(self, node):
        print(f"Hovering: {self.fg.get_number_to_pair(node.func_id)}")
    def default_color_node(self, node):
        return '#7f7f7f'


def rgb_to_hex(rgb):
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"

def invert_color(rgb):
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    r = 255 - int(r, 16)
    g = 255 - int(g, 16)
    b = 255 - int(b, 16)
    return f"#{r:02x}{g:02x}{b:02x}"
