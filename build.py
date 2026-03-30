#!/usr/bin/env python3
import subprocess

# Paths
flamegraph_script = "/home/user/FlameGraph/mai-edited-flamegraph.pl"
folded_file       = "minix.out.folded"
template_file     = "template.html"
output_file       = "index.html"

# 1️⃣ Generate SVG from FlameGraph
svg = subprocess.check_output([flamegraph_script, folded_file], text=True)

# 2️⃣ Read template
with open(template_file, "r", encoding="utf-8") as f:
    template = f.read()

# 3️⃣ Replace placeholder {$svg} with actual SVG
html = template.replace("{$svg}", svg)

# 4️⃣ Write final index.html
with open(output_file, "w", encoding="utf-8") as f:
    f.write(html)

print("index.html generated successfully.")
