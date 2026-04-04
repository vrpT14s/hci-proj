import hashlib
import colorsys
from pathlib import Path

class PathColorizer:
    def __init__(self, groups, base_dir_root="", overrides=None):
        """
        groups: dict like {"net": ["net", "drivers/net"], "mm": ["mm"]}
        overrides: optional dict of group -> RGB tuple to override default coloring
                   also can include "misc" for unmatched paths
        """
        self.base_dir_root = Path(base_dir_root) if base_dir_root else None
        self.overrides = overrides or {}

        # flatten prefixes -> group
        prefix_map = []
        for group, prefixes in groups.items():
            for p in prefixes:
                prefix_map.append((Path(p), group))
        # sort longest prefix first
        self.prefix_map = sorted(prefix_map, key=lambda x: len(x[0].parts), reverse=True)

        # assign distinct hues for groups that don't have overrides
        group_names = list(groups.keys())
        self.group_to_hue = {}
        hue_list = self._generate_distinct_hues(len(group_names) + 1)
        for i, g in enumerate(group_names):
            if g not in self.overrides:
                self.group_to_hue[g] = hue_list[i]
        self.misc_hue = hue_list[-1]

    def color(self, path):
        # strip base root if provided
        p = Path(path)
        if self.base_dir_root:
            try:
                p = p.relative_to(self.base_dir_root)
            except ValueError:
                pass

        if not p.parts:
            base_rgb = self.overrides.get("misc", (0.5,0.5,0.5))
            base_hsv = colorsys.rgb_to_hsv(*base_rgb)
            return self._vary_hsv(base_hsv, str(p))

        # longest-prefix match
        group = None
        for prefix, g in self.prefix_map:
            try:
                p.relative_to(prefix)
                group = g
                break
            except ValueError:
                continue

        # get base RGB
        if group and group in self.overrides:
            base_rgb = self.overrides[group]
        elif group is None and "misc" in self.overrides:
            base_rgb = self.overrides["misc"]
        else:
            h = self.group_to_hue.get(group, self.misc_hue)
            h2 = int(hashlib.md5(str(p).encode()).hexdigest(), 16)
            s = min(0.65 + (h2 % 40)/100.0, 1.0)
            v = min(0.7 + ((h2//100) % 40)/100.0, 1.0)
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            return (r,g,b)

        # convert override RGB to HSV and vary it
        base_hsv = colorsys.rgb_to_hsv(*base_rgb)
        return self._vary_hsv(base_hsv, str(p))

    # helper for per-path variation
    def _vary_hsv(self, base_hsv, path_str):
        h, s, v = base_hsv
        h2 = int(hashlib.md5(path_str.encode()).hexdigest(), 16)
        s = min(max(s * (0.85 + (h2 % 30)/100.0), 0), 1)
        v = min(max(v * (0.85 + ((h2//100)%30)/100.0), 0), 1)
        return colorsys.hsv_to_rgb(h, s, v)

    @staticmethod
    def _generate_distinct_hues(n):
        golden_angle = 137.508
        return [(i*golden_angle % 360)/360.0 for i in range(n)]

    def draw_legend(self, parent="legend_window"):
        import dearpygui.dearpygui as dpg
        def add_entry(name, rgb):
            color = [int(c*255) for c in rgb] + [255]
            with dpg.group(parent=parent, horizontal=True):
                dpg.add_color_button(default_value=color, no_alpha=True, width=18, height=18)
                dpg.add_text(name)

        for g, hue in self.group_to_hue.items():
            add_entry(g, colorsys.hsv_to_rgb(hue, 0.75, 0.85))
        misc_color = self.overrides.get("misc", colorsys.hsv_to_rgb(self.misc_hue, 0.75, 0.85))
        add_entry("misc", misc_color)
