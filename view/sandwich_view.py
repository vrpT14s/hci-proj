import tkinter as tk

class SandwichView:
    def __init__(self, fg, root, parent, color_strategy):
        self.fg = fg
        self.target_func_id = None
        self.root = root

        from view.flamegraph_view import FlamegraphView
        self.ctx = FlamegraphView.DrawContext(parent, lambda: self.draw())

        self.view_start = 0
        self.view_end = None

        self.sandwich_node = None
        self.select_node = self.default_select_node
        self.hover_node = self.default_hover_node
        self.color_node = color_strategy.color

    def set_root(self, root):
        self.root = root
        self.view_start = 0
        self.view_end = None

    def set_sandwich_node(self, func_id):
        self.target_func_id = func_id
        self.view_start = 0
        self.view_end = None

    def draw(self):
        if self.target_func_id is None:
            return
        self.ctx.canvas.delete("all")
        WIDTH = self.ctx.canvas.winfo_width()
        WINDOW_HEIGHT = self.ctx.canvas.winfo_height()

        discoveries = []
        stack = [self.root]
        while stack:
            curr = stack.pop()
            if curr.func_id == self.target_func_id:
                callers = []
                p = curr.parent
                while p and p.func_id is not None:
                    callers.append((p.func_id, p))
                    p = p.parent
                discoveries.append((curr, callers))
            stack.extend(curr.children.values())

        if not discoveries: return
        discoveries.sort(key=lambda x: [c[0] for c in x[1]]) # Sort by IDs

        total_samples = sum(d[0].total() for d in discoveries)
        if self.view_end is None: self.view_end = total_samples

        view_total = self.view_end - self.view_start
        def to_x(sample_idx):
            return (sample_idx - self.view_start) * (WIDTH / (view_total or 1))

        rects_to_render = []

        rects_to_render.append((self.target_func_id, to_x(0), to_x(total_samples), 0, (discoveries[0][0], 0, total_samples)))

        # 3. Callers (Downwards)
        max_caller_depth = max(len(d[1]) for d in discoveries) if discoveries else 0
        for d_idx in range(1, max_caller_depth + 1):
            current_s = 0
            i = 0
            while i < len(discoveries):
                node, callers = discoveries[i]
                if len(callers) >= d_idx:
                    target_id, target_node = callers[d_idx-1]
                    group_samples = 0
                    j = i
                    while j < len(discoveries) and len(discoveries[j][1]) >= d_idx and discoveries[j][1][d_idx-1][0] == target_id:
                        group_samples += discoveries[j][0].total()
                        j += 1

                    x0, x1 = to_x(current_s), to_x(current_s + group_samples)
                    if x1 > 0 and x0 < WIDTH:
                        # FIX: Pass target_node so color_node works for parents
                        rects_to_render.append((target_id, x0, x1, -d_idx, (target_node, current_s, current_s + group_samples)))
                    current_s += group_samples
                    i = j
                else:
                    current_s += node.total()
                    i += 1

        # 4. Callees (Upwards)
        current_s = 0
        for node, _ in discoveries:
            node_samples = node.total()
            x0, x1 = to_x(current_s), to_x(current_s + node_samples)
            if x1 > 0 and x0 < WIDTH:
                self._layout_recursive(node, 0, rects_to_render, to_x, current_s)
            current_s += node_samples

        min_depth = min(r[3] for r in rects_to_render) # The callers (negative)
        max_depth = max(r[3] for r in rects_to_render) # The callees (positive)

        # 5. Render
        y_center = WINDOW_HEIGHT / 2
        for i, (f_id, x0, x1, depth, zoom_data) in enumerate(rects_to_render):
            width = x1 - x0
            if width < 0.5: continue
            #y = y_center - (depth * self.ctx.RECT_HEIGHT)
            y = (max_depth - depth) * self.ctx.RECT_HEIGHT

            node_obj = zoom_data[0] if zoom_data else None
            hex_color = self.color_node(node_obj)
            label = self.fg.get_display_name(f_id)

            tag = f"node_{i}"
            self.ctx.canvas.create_rectangle(x0, y, x1, y + self.ctx.RECT_HEIGHT, fill=hex_color, outline="black", tags=tag)

            if depth == 0:
                self.ctx.canvas.create_rectangle(x0, y+2, x1, y+self.ctx.RECT_HEIGHT-2, outline="red", width=2)

            # FIX: Clamped text drawing
            self.draw_text_clamped(x0, x1, y, label, WIDTH)

            if zoom_data:
                _, s, e = zoom_data
                self.ctx.canvas.tag_bind(tag, "<Button-1>", lambda event, start=s, end=e: self.zoom(start, end))
                if node_obj:
                    self.ctx.canvas.tag_bind(tag, "<Enter>", lambda e, n=node_obj: self.hover_node(n))
        total_rows = max_depth - min_depth + 1
        total_height = total_rows * self.ctx.RECT_HEIGHT
        self.ctx.canvas.configure(scrollregion=(0, 0, WIDTH, total_height))
        # After the render loop:
        pivot_y_fraction = max_depth / total_rows
        # This moves the scrollbar so the pivot is at the top of the window
        # You can subtract a bit to center it in the window if you like
        self.ctx.canvas.yview_moveto(pivot_y_fraction - 0.5)

    def zoom(self, start, end):
        self.view_start = start
        self.view_end = end
        self.draw()

    def _layout_recursive(self, node, depth, rects, to_x, start_s):
        total = node.total()
        if total == 0: return
        if depth > 0:
            rects.append((node.func_id, to_x(start_s), to_x(start_s + total), depth, (node, start_s, start_s + total)))
        cur_s = start_s
        for child in node.children.values():
            self._layout_recursive(child, depth + 1, rects, to_x, cur_s)
            cur_s += child.total()

    def draw_text_clamped(self, x0, x1, y, text, canvas_width):
        """Draws text that stays within the visible screen area even when box is zoomed."""
        # Only draw if some part of the box is visible
        visible_x0 = max(0, x0)
        visible_x1 = min(canvas_width, x1)
        visible_width = visible_x1 - visible_x0

        if visible_width < 40 or not text:
            return

        # Center text in the *visible* portion of the box
        center_x = (visible_x0 + visible_x1) / 2
        center_y = y + (self.ctx.RECT_HEIGHT / 2)

        max_chars = int(visible_width / 8)
        if len(text) > max_chars:
            display_text = f"{text[:max_chars-3]}..." if max_chars > 3 else ""
        else:
            display_text = text

        if display_text:
            self.ctx.canvas.create_text(
                center_x, center_y, text=display_text,
                fill="black", font=("Arial", 10), state="disabled"
            )

    def default_select_node(self, node): print(f"Selected: {node.func_id}")
    def default_hover_node(self, node): pass
    def default_color_node(self, node): return "#ffaa66"
