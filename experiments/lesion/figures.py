#!/usr/bin/env python3
"""Figures for the lesion study (run from the repository root after analyze_study.py).

    figures.py

Writes experiments/lesion/figures/*.png:
  die_severity.png   die photo, every transistor coloured by lesion severity (one panel per mode)
  die_clusters.png   small multiples: one panel per functional cluster, members highlighted
  die_blocks.png     small multiples: behaviourally named blocks (the floorplan reference)
  effects.png        effect classes, stuck-open vs stuck-closed
  cluster_matrix.png clusters x instructions: fraction of members that break each instruction
Transistor positions: channel centroids from the netlist extraction, mapped onto the die photo
with netlist/photo_align.json (the alignment used by the web demo).
Photo: Intel 4004 35th Anniversary Project, 4004.com, CC BY-NC-SA 3.0.
"""
import json
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

sys.path.insert(0, "tools")
sys.path.insert(0, "experiments/lesion")
from isa import NAMES

D = "experiments/lesion"
R, F = os.path.join(D, "results"), os.path.join(D, "figures")
os.makedirs(F, exist_ok=True)
CREDIT = "Die photo: Intel 4004 35th Anniversary Project, 4004.com (CC BY-NC-SA 3.0)"

web = json.load(open(os.path.join(R, "web.json")))
TR = web["tr"]
X = np.array([t["x"] for t in TR]); Y = np.array([t["y"] for t in TR])

photo_path = os.path.join(F, ".photo_half.png")
if not os.path.exists(photo_path):
    from diemap import photo_maps
    photo, _, _, _ = photo_maps("source/analyzer", "source/4004-composite-photo.jpg", "netlist/photo_align.json")
    photo.save(photo_path)
photo = np.asarray(Image.open(photo_path).convert("L")).astype(float) / 255
H, W = photo.shape
BG = "#1a1a19"; INK = "#f0efec"; INK2 = "#c3c2b7"; MUTED = "#8a897f"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": "#3a3a37",
                     "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG})
# crop to the transistor area with a margin
x0, x1 = max(0, X.min() - 25), min(W, X.max() + 25)
y0, y1 = max(0, Y.min() - 25), min(H, Y.max() + 25)


def die(ax, dim=0.45):
    ax.imshow(photo * dim, cmap="gray", vmin=0, vmax=1, interpolation="lanczos")
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)


# single-hue sequential ramp (orange), most severe = lightest/most saturated on the dark photo
SEV_COL = {"global": "#ffb07a", "broad": "#f28a4e", "partial": "#d95926", "reset-only": "#a3431c", "none": None}
fig, axs = plt.subplots(1, 2, figsize=(12, 5.4))
for ax, m, title in zip(axs, "oc", ("stuck-open", "stuck-closed")):
    die(ax)
    for si, s in enumerate(web["sev"]):
        sel = [i for i, t in enumerate(TR) if m in t and t[m]["s"] == si]
        if not sel: continue
        if SEV_COL[s] is None:
            ax.scatter(X[sel], Y[sel], s=7, facecolors="none", edgecolors="#6f6e68", linewidths=0.6,
                       label=f"no effect ({len(sel)})")
        else:
            ax.scatter(X[sel], Y[sel], s=9, c=SEV_COL[s], linewidths=0, label=f"{s} ({len(sel)})")
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    leg = ax.legend(loc="lower left", fontsize=7.5, frameon=True, facecolor=BG, edgecolor="#3a3a37", labelcolor=INK)
fig.suptitle("Lesion severity per transistor (global: set-up/read-out or >= 240 opcodes broken; broad: >= 12 of 19 "
             "instruction groups; partial: fewer)", color=INK, fontsize=10, x=0.01, ha="left")
fig.text(0.01, 0.01, CREDIT, color=MUTED, fontsize=7)
fig.tight_layout(rect=(0, 0.02, 1, 0.95))
fig.savefig(os.path.join(F, "die_severity.png"), dpi=150)
plt.close(fig)

# clusters: small multiples
clusters = [c for c in web["clusters"] if c["n"] >= 4]
n = len(clusters)
cols = 5
rows = (n + cols - 1) // cols
fig, axs = plt.subplots(rows, cols, figsize=(cols * 3.0, rows * 2.6))
axs = np.atleast_1d(axs).ravel()
cl = np.array([t["cl"] for t in TR])
for ax, c in zip(axs, clusters):
    die(ax, 0.35)
    ax.scatter(X, Y, s=0.8, c="#5d5c56", linewidths=0)
    sel = cl == c["id"]
    ax.scatter(X[sel], Y[sel], s=6, c="#3987e5", linewidths=0)
    name = c["name"] if len(c["name"]) <= 44 else c["name"][:42] + "..."
    ax.set_title(f"C{c['id']} n={c['n']}\n{name}", fontsize=6.6, color=INK, loc="left")
for ax in axs[n:]:
    ax.axis("off")
fig.suptitle("Functional clusters (transistors grouped by the set of instructions their lesions break, and how)",
             color=INK, fontsize=10, x=0.01, ha="left")
fig.text(0.01, 0.003, CREDIT, color=MUTED, fontsize=7)
fig.tight_layout(rect=(0, 0.01, 1, 0.97))
fig.savefig(os.path.join(F, "die_clusters.png"), dpi=100)
plt.close(fig)

# blocks
blk = np.array([t["blk"].lstrip("~") for t in TR])
direct = np.array([not t["blk"].startswith("~") and t["blk"] != "" for t in TR])
names = [b for b in ("index registers", "address stack array", "PC path", "accumulator/carry", "instruction decode", "timing",
                     "DCL/CM-RAM") if (blk == b).any()]
if names:
    fig, axs = plt.subplots(1, len(names), figsize=(2.6 * len(names), 2.8))
    for ax, b in zip(np.atleast_1d(axs), names):
        die(ax, 0.35)
        ax.scatter(X, Y, s=0.8, c="#5d5c56", linewidths=0)
        sel = (blk == b) & ~direct
        ax.scatter(X[sel], Y[sel], s=4, c="#1c4f8f", linewidths=0)
        sel = (blk == b) & direct
        ax.scatter(X[sel], Y[sel], s=6, c="#3987e5", linewidths=0)
        ax.set_title(f"{b}\n{int(((blk == b) & direct).sum())} touch a named node", fontsize=7.5, color=INK, loc="left")
    fig.suptitle("Behaviourally identified blocks (bright: transistor touches a node identified by its behaviour; "
                 "dark: nearest-neighbour extension)", color=INK, fontsize=9, x=0.01, ha="left")
    fig.text(0.01, 0.005, CREDIT, color=MUTED, fontsize=6.5)
    fig.tight_layout(rect=(0, 0.02, 1, 0.9))
    fig.savefig(os.path.join(F, "die_blocks.png"), dpi=150)
    plt.close(fig)

# effect classes bar chart (two series: blue = stuck-open, orange = stuck-closed)
eff = web["eff"]
cnt = {m: [sum(1 for t in TR if m in t and t[m]["e"] == i) for i in range(len(eff))] for m in "oc"}
fig, ax = plt.subplots(figsize=(8, 4))
yy = np.arange(len(eff))
h = 0.38
for k, (m, col, lab) in enumerate((("o", "#3987e5", "stuck-open"), ("c", "#d95926", "stuck-closed"))):
    ax.barh(yy + (k - 0.5) * (h + 0.02), cnt[m], height=h, color=col, label=lab)
    for yi, v in zip(yy, cnt[m]):
        ax.text(v + 15, yi + (k - 0.5) * (h + 0.02), str(v), va="center", fontsize=7.5, color=INK2)
ax.set_yticks(yy); ax.set_yticklabels(eff); ax.invert_yaxis()
ax.set_xlabel("lesions (of 2242 per mode)")
ax.grid(axis="x", color="#33332f", linewidth=0.6); ax.set_axisbelow(True)
for s in ("top", "right"): ax.spines[s].set_visible(False)
ax.legend(frameon=False, loc="lower right")
ax.set_title("Effect class of each lesion (first matching class)", loc="left", color=INK, fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(F, "effects.png"), dpi=150)
plt.close(fig)

# cluster x instruction matrix (sequential, one hue)
cl_list = [c for c in web["clusters"] if c["n"] >= 4 and c["name"] != "no effect"]
M = np.zeros((len(cl_list), len(NAMES)))
for r, c in enumerate(cl_list):
    mem = [t for t in TR if t["cl"] == c["id"]]
    for t in mem:
        b = np.zeros(len(NAMES), bool)
        for m in "oc":
            if m in t: b |= np.array(t[m]["i"]) > 0
        M[r] += b
    M[r] /= max(len(mem), 1)
fig, ax = plt.subplots(figsize=(12, 0.28 * len(cl_list) + 1.6))
from matplotlib.colors import LinearSegmentedColormap
cmap = LinearSegmentedColormap.from_list("blue", ["#1a1a19", "#1c4f8f", "#3987e5", "#cfe3fb"])
ax.imshow(M, aspect="auto", cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
ax.set_xticks(range(len(NAMES))); ax.set_xticklabels(NAMES, rotation=90, fontsize=6.5)
ax.set_yticks(range(len(cl_list)))
ax.set_yticklabels([f"C{c['id']} n={c['n']}  {c['name'][:50]}" for c in cl_list], fontsize=6.5)
ax.set_title("Fraction of each cluster's transistors whose lesion (either mode) breaks the instruction",
             loc="left", color=INK, fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(F, "cluster_matrix.png"), dpi=150)
plt.close(fig)
print("figures written to", F)
