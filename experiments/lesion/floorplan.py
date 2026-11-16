#!/usr/bin/env python3
"""Floorplan of the 4004 drawn from the lesion study alone.

Each transistor is put in a zone according to WHAT ITS FAILURE BREAKS (the lesion
cluster it fell in, results/clusters.tsv), not according to any drawing of the chip.
The die is then divided into cells; each cell takes the majority zone of the
transistors near it. Output: figures/floorplan.png and results/floorplan_zones.tsv.

Usage: floorplan.py <lesion dir> <die photo>
"""
import csv
import os
import sys
from collections import Counter, defaultdict

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import Patch

D, PHOTO = sys.argv[1], sys.argv[2]
R, F = os.path.join(D, "results"), os.path.join(D, "figures")

# zone -> (label, colour). Hues validated for a dark surface; grey = uninformative.
ZONES = {
    "pc":    ("Program counter and address stack", "#3987e5"),
    "reg":   ("Index registers", "#d95926"),
    "alu":   ("Accumulator, carry and arithmetic", "#199e70"),
    "cm":    ("Command lines (CM-ROM, CM-RAM, DCL)", "#c98500"),
    "mixed": ("Shared decode (breaks several blocks)", "#d55181"),
    "bus":   ("Data bus contents only", "#0ca30c"),
    "reset": ("Reset only", "#9085e9"),
    "all":   ("Breaks everything (clock, timing, control)", "#b9b8b0"),
    "none":  ("No effect in the model", "#55544f"),
}


def zone_of(c):
    name = c["name"]
    parts = [k for k in c["core_kinds"].split(",") if k]
    idle = {k[5:] for k in parts if k.startswith("idle:")}
    kinds = {k for k in parts if not k.startswith("idle:")}
    if name.startswith("reset only"):
        return "reset"
    if name.startswith("no effect"):
        return "none"
    if len(idle) >= 3 or "SYNC" in kinds or not kinds:
        return "all"
    if idle == {"PC/STACK"} or ("PC/STACK" in kinds and kinds <= {"PC/STACK", "BUS"}):
        return "pc"
    if idle == {"REG"} or ("REG" in kinds and "ACC/CY" not in kinds):
        return "reg"
    if kinds <= {"CM"}:
        return "cm"
    if kinds <= {"BUS", "XUND"}:
        return "bus"
    if "ACC/CY" in kinds and "REG" not in kinds and (idle <= {"ACC/CY", "XUND"}):
        if "PC/STACK" in kinds and len(c["core_instructions"].split("+")) <= 6:
            return "mixed"
        return "alu"
    if idle == {"ACC/CY"}:
        return "alu"
    return "mixed"


clusters = {c["cluster"]: c for c in csv.DictReader(open(os.path.join(R, "clusters.tsv")), delimiter="\t")}
czone = {k: zone_of(c) for k, c in clusters.items()}

# photo coordinates per transistor come from lesions.tsv
pos = {}
for r in csv.DictReader(open(os.path.join(R, "lesions.tsv")), delimiter="\t"):
    # lesions.tsv stores coordinates on the half-size photo used by the web page
    pos[r["t"]] = (2 * float(r["photo_x"]), 2 * float(r["photo_y"]))
T = list(csv.DictReader(open(os.path.join(R, "transistors.tsv")), delimiter="\t"))
xy = np.array([pos[t["t"]] for t in T])
tz = [czone[t["cluster"]] for t in T]
zkeys = list(ZONES)
zi = np.array([zkeys.index(z) for z in tz])

# ---- cells: majority zone of the 9 nearest transistors, where any lie within reach
photo = Image.open(PHOTO).convert("L")
W, H = photo.size
CELL, REACH, K = 40, 95, 9
gx = np.arange(CELL / 2, W, CELL)
gy = np.arange(CELL / 2, H, CELL)
GX, GY = np.meshgrid(gx, gy)
tree = cKDTree(xy)
dist, idx = tree.query(np.c_[GX.ravel(), GY.ravel()], k=K)
grid = np.full(GX.size, -1)
for i in range(GX.size):
    near = idx[i][dist[i] < REACH * 1.6]
    if dist[i][0] > REACH or len(near) == 0:
        continue
    w = Counter()
    for j, d in zip(idx[i], dist[i]):
        if d < REACH * 1.6:
            w[zi[j]] += 1.0 / (d + 15)
    grid[i] = max(w, key=w.get)
grid = grid.reshape(GX.shape)
# remove specks: a cell surrounded by another zone takes the neighbourhood's zone
for _ in range(2):
    g2 = grid.copy()
    for y in range(1, grid.shape[0] - 1):
        for x in range(1, grid.shape[1] - 1):
            if grid[y, x] < 0:
                continue
            nb = [v for v in grid[y - 1:y + 2, x - 1:x + 2].ravel() if v >= 0]
            v, n = Counter(nb).most_common(1)[0]
            if v != grid[y, x] and n >= 6:
                g2[y, x] = v
    grid = g2

# ---- how well does a cell's zone describe the transistors in it?
cell_of = (np.clip((xy[:, 1] // CELL).astype(int), 0, grid.shape[0] - 1),
           np.clip((xy[:, 0] // CELL).astype(int), 0, grid.shape[1] - 1))
agree = grid[cell_of] == zi
by_zone = defaultdict(lambda: [0, 0])
for a, z in zip(agree, tz):
    by_zone[z][0] += int(a)
    by_zone[z][1] += 1
with open(os.path.join(R, "floorplan_zones.tsv"), "w") as f:
    f.write("zone\tlabel\ttransistors\tin_own_zone_cell\tclusters\n")
    for z in zkeys:
        cl = ",".join(k for k in clusters if czone[k] == z)
        f.write(f"{z}\t{ZONES[z][0]}\t{by_zone[z][1]}\t{by_zone[z][0]}\t{cl}\n")
print(f"transistors lying in a cell of their own zone: {agree.sum()} of {len(T)} ({100 * agree.mean():.0f}%)")
for z in zkeys:
    print(f"  {z:6s} {by_zone[z][1]:5d} transistors, {by_zone[z][0]:5d} in own-zone cells")

# ---- figure
BG, INK = "#1a1a19", "#f0efec"
fig = plt.figure(figsize=(15, 9.2), facecolor=BG)
ax = fig.add_axes([0.015, 0.03, 0.70, 0.90])
ax.imshow(np.asarray(photo), cmap="gray", vmin=0, vmax=420, extent=(0, W, H, 0))
rgba = np.zeros(grid.shape + (4,))
for k, z in enumerate(zkeys):
    c = matplotlib.colors.to_rgb(ZONES[z][1])
    rgba[grid == k] = (*c, 0.62 if z not in ("all", "none") else 0.30)
ax.imshow(rgba, extent=(0, W, H, 0), interpolation="nearest")
# outlines between zones
for k, z in enumerate(zkeys):
    m = (grid == k).astype(float)
    if m.any():
        ax.contour(GX, GY, m, levels=[0.5], colors=[BG], linewidths=1.6)
ax.scatter(xy[:, 0], xy[:, 1], s=3.0, c=[ZONES[z][1] for z in tz], linewidths=0, alpha=0.95)

halo = [pe.withStroke(linewidth=3.2, foreground=BG)]
SHORT = {"pc": "PROGRAM COUNTER\n+ ADDRESS STACK", "reg": "INDEX\nREGISTERS", "alu": "ACCUMULATOR\n+ ARITHMETIC",
         "cm": "COMMAND\nLINES", "mixed": "SHARED\nDECODE", "bus": "DATA BUS", "reset": "RESET",
         "all": "CLOCK, TIMING,\nCONTROL", "none": ""}
tags = []
# callouts: clusters whose lesions break only one to three instructions
for k, c in clusters.items():
    ins = c["core_instructions"].split("+") if c["core_instructions"] else []
    if not (1 <= len(ins) <= 3) or int(c["n"]) < 5:
        continue
    m = np.array([t["cluster"] == k for t in T])
    cx, cy = np.median(xy[m], axis=0)
    tags.append((cx, cy))
    ax.text(cx, cy, "/".join(ins), color=INK, fontsize=7.5, ha="center", va="center", style="italic",
            path_effects=[pe.withStroke(linewidth=2.4, foreground=BG)],
            bbox=dict(boxstyle="round,pad=0.18", fc=BG, ec=INK, lw=0.6, alpha=0.78))
for k, z in enumerate(zkeys):
    if not SHORT[z]:
        continue
    lab, n = ndimage.label(grid == k)
    sizes = ndimage.sum(grid == k, lab, range(1, n + 1))
    for j in np.argsort(sizes)[::-1][:3]:
        if sizes[j] < (70 if z != "all" else 160):
            continue
        ys, xs = np.nonzero(lab == j + 1)
        # label at the cell deepest inside the region
        dt = ndimage.distance_transform_edt(lab == j + 1)
        yy, xx = np.unravel_index(dt.argmax(), dt.shape)
        # keep the zone name clear of instruction tags
        if any(abs(tx - gx[xx]) < 190 and abs(ty - gy[yy]) < 55 for tx, ty in tags):
            free = [(dt[y, x], y, x) for y, x in zip(ys, xs)
                    if not any(abs(tx - gx[x]) < 190 and abs(ty - gy[y]) < 55 for tx, ty in tags)]
            if not free or max(free)[0] < 1.5:
                continue
            _, yy, xx = max(free)
        ax.text(gx[xx], gy[yy], SHORT[z], color=INK, fontsize=11, fontweight="bold", ha="center",
                va="center", path_effects=halo, linespacing=1.05)

ax.set_xlim(0, W)
ax.set_ylim(H, 0)
ax.axis("off")

fig.text(0.015, 0.955, "Intel 4004 floorplan, drawn from what breaks", color=INK, fontsize=19, fontweight="bold")
lx = 0.735
fig.text(lx, 0.905, "Each transistor was broken in simulation,\none at a time. Colour shows which part of\nthe chip's state its failure corrupts.",
         color="#c3c2b7", fontsize=10.5, va="top", linespacing=1.4)
handles = [Patch(fc=ZONES[z][1], ec="none", label=f"{ZONES[z][0]}  ({by_zone[z][1]})") for z in zkeys]
leg = fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(lx - 0.005, 0.80), frameon=False,
                 fontsize=10, labelcolor=INK, handlelength=1.1, handleheight=1.1, labelspacing=0.75,
                 title="Zone  (transistors)", title_fontsize=10)
leg.get_title().set_color("#c3c2b7")
leg._legend_box.align = "left"
fig.text(lx, 0.30,
         "Italic tags mark groups of transistors whose\nfailure breaks only the named instructions.\n\n"
         "Zones come from the lesion clusters only.\nNo schematic or published floorplan was used,\n"
         "and the names are my reading of the effects.\n\n"
         f"{100 * agree.mean():.0f}% of transistors lie in a cell of their\nown zone; the rest are interleaved.\n\n"
         "Switch-level model, not checked on a real chip.\nPhoto: 4004.com, CC BY-NC-SA 3.0.",
         color="#c3c2b7", fontsize=9.5, va="top", linespacing=1.4)
out = os.path.join(F, "floorplan.png")
fig.savefig(out, dpi=150, facecolor=BG)
print("wrote", out)
