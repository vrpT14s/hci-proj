import colorsys
import hashlib

class Palette:
    PRESETS = {
        "kelly": [
            "#FFB300", "#803E75", "#FF6800", "#A6BDD7", "#C10020", "#CEA262",
            "#817066", "#007D34", "#F6768E", "#00538A", "#FF7A5C", "#53377A",
            "#FF8E00", "#B32851", "#F4C800", "#7F180D", "#93AA00", "#593315",
            "#F13A13", "#232C16"
        ],
        "glasbey": [
            "#ca0424", "#556dff", "#209600", "#ff41ff", "#710079", "#aafb00",
            "#00bec2", "#ffa210", "#593500", "#08008a", "#005d59", "#9a8286"
        ],
        "tableau": [
            "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a",
            "#d62728", "#ff9896", "#9467bd", "#c5b0d5", "#8c564b", "#c49c94",
            "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7", "#bcbd22", "#dbdb8d",
            "#17becf", "#9edae5"
        ],
        "vibrant": [
            "#EE7733", "#0077BB", "#33BBEE", "#EE3377", "#CC3311", "#009988",
            "#BBBBBB", "#332288", "#DDCC77", "#117733", "#88CCEE", "#882255"
        ]
    }

    def __init__(self, name="kelly"):
        self.colors = self.PRESETS.get(name, self.PRESETS["kelly"])

    def get_color(self, index):
        """Returns a stable color from the preset based on an index."""
        if index is None:
            return '#7f7f7f'
        return self.colors[index % len(self.colors)]

    def jitter(self, color_hex, key, l_delta=0.1, s_delta=0.1):
        """
        Takes a hex color and a 'thing' (the key). Returns a deterministic
        jittered version of that color based on the key's hash.
        """
        # 1. Hex to HLS
        hex_val = color_hex.lstrip('#')
        r, g, b = tuple(int(hex_val[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        h, l, s = colorsys.rgb_to_hls(r, g, b)

        # 2. Deterministic Hash (MD5 is stable across Python sessions)
        hash_digest = hashlib.md5(str(key).encode()).hexdigest()
        hash_int = int(hash_digest, 16)

        # 3. Use hash bits for Lightness/Saturation offsets
        # l_off and s_off will be between -1.0 and 1.0
        l_off = ((hash_int % 100) / 50.0 - 1.0) * l_delta
        s_off = (((hash_int // 100) % 100) / 50.0 - 1.0) * s_delta

        # 4. Apply and clamp (keep L between 0.2 and 0.8 to keep it visible)
        new_l = max(0.2, min(0.8, l + l_off))
        new_s = max(0.1, min(0.9, s + s_off))

        # 5. Back to Hex
        nr, ng, nb = colorsys.hls_to_rgb(h, new_l, new_s)
        return '#{:02x}{:02x}{:02x}'.format(int(nr*255), int(ng*255), int(nb*255))
