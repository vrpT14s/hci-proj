from flamegraph import *
from view.palette import Palette

import tkinter as tk

class DsoColorView:
    def __init__(self, flamegraph, palette_name=None):
        self.fg = flamegraph
        self.palette = Palette(palette_name)
        dso_set = set(map(lambda x: x[0], self.fg.pair_to_number.keys()))
        self.dso_to_index = {dso: num for (num, dso) in enumerate(sorted(dso_set, key=lambda x: x if x is not None else ''))}
        print(self.dso_to_index)

    def color(self, node):
        dso, _ = self.fg.number_to_pair.get(node.func_id, (None, None))
        dso_color_index = self.dso_to_index.get(dso)
        color = self.palette.get_color(dso_color_index)
        return color

    def draw_legend(self, parent):
        """
        Draws a legend into the provided parent widget.
        'parent' should be a tk.Frame or tk.Toplevel.
        """
        for child in parent.winfo_children():
            child.destroy()
        # Container frame for the legend items
        legend_frame = tk.Frame(parent, padx=10, pady=10)
        legend_frame.pack(fill="both", expand=True)

        tk.Label(legend_frame, text="DSO Legend", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="w")

        # Iterate through our DSOs and create a row for each
        for row_idx, (dso_name, color_idx) in enumerate(self.dso_to_index.items(), start=1):
            color_hex = self.palette.get_color(color_idx)

            # 1. The Color Swatch
            swatch = tk.Label(legend_frame, width=2, height=1, bg=color_hex, relief="ridge", borderwidth=1)
            swatch.grid(row=row_idx, column=0, padx=5, pady=2)

            # 2. The Text Label
            display_name = dso_name if dso_name else "[unknown]"
            name_label = tk.Label(legend_frame, text=display_name, anchor="w")
            name_label.grid(row=row_idx, column=1, padx=5, pady=2, sticky="w")

        return legend_frame
