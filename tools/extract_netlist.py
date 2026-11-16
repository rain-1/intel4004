#!/usr/bin/env python3
"""Extract a transistor-level netlist of the Intel 4004 from its mask layers.

Input:  five 1-bit bitmaps (diffusion, poly, metal, vias, contacts) traced from the die.
Output: JSON netlist: electrical nodes, transistors (gate, a, b), capacitors, pads.

Silicon-gate pMOS rules used:
  * poly crossing diffusion makes a transistor channel (self-aligned gate) ...
  * ... unless a buried contact sits there, in which case poly and diffusion are joined
  * "vias" join metal to whatever is beneath (poly or diffusion)
"""
import json
import sys
import numpy as np
from layout import LAYERS, load_layers, label

# Bond pads: (name, x, y) -- a point inside each pad, read off the layout.
PADS = [
    ("TEST", 260, 84), ("RESET", 630, 84), ("SYNC", 1050, 84), ("VSS", 1265, 84),
    ("PHI2", 1600, 84), ("PHI1", 1890, 320), ("VSS2", 1890, 615),
    ("D3", 1890, 1975), ("D2", 1890, 2440), ("D1", 1275, 2625), ("D0", 795, 2625),
    ("CMRAM0", 545, 2625), ("CMRAM1", 195, 2625), ("CMRAM2", 70, 2145),
    ("CMRAM3", 70, 1835), ("VDD", 70, 1485), ("CMROM", 70, 425),
]


# A cut (via / buried contact) normally lands on ONE shape per layer. Where it touches a
# second shape of the same layer, that only counts as a real bridge if at least this
# fraction of the cut lies on it; otherwise it is tracing slop (the cut grazing a
# neighbouring line). Exactly one cut on the chip trips this: the buried contact at
# (130,845), which grazes the CM-ROM driver's gate and would short it to its own inverter.
MIN_SECOND_SHAPE_FRACTION = 0.2


class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def touching_pairs(la, lb):
    """Unique (a, b) label pairs where region a of la is 4-adjacent to region b of lb."""
    out = []
    for sa, sb in ((np.s_[:-1], np.s_[1:]), (np.s_[1:], np.s_[:-1]),
                   (np.s_[:, :-1], np.s_[:, 1:]), (np.s_[:, 1:], np.s_[:, :-1])):
        a, b = la[sa], lb[sb]
        m = (a > 0) & (b > 0)
        out.append(np.stack([a[m], b[m]], axis=1))
    return np.unique(np.concatenate(out), axis=0)


def overlap_pairs(la, lb, min_px=1):
    m = (la > 0) & (lb > 0)
    pairs, counts = np.unique(np.stack([la[m], lb[m]], axis=1), axis=0, return_counts=True)
    return pairs[counts >= min_px]


def centroids(lab, n):
    ys, xs = np.nonzero(lab)
    l = lab[ys, xs]
    cnt = np.bincount(l, minlength=n + 1)
    cx = np.bincount(l, xs, n + 1) / np.maximum(cnt, 1)
    cy = np.bincount(l, ys, n + 1) / np.maximum(cnt, 1)
    return cx, cy, cnt


def extract(src_dir, verbose=True):
    L = load_layers(src_dir)
    D, P, M, V, C = (L[n] for n in LAYERS)
    log = (lambda *a: print(*a, file=sys.stderr)) if verbose else (lambda *a: None)

    chan = D & P & ~C                 # gate oxide: poly over diffusion, no buried contact
    dcon = D & ~chan                  # conducting diffusion (source/drain/wiring)
    lp, n_p = label(P)
    lm, n_m = label(M)
    ld, n_d = label(dcon)
    lc, n_c = label(chan)
    lv, n_v = label(V)
    lb, n_b = label(C)
    log(f"regions: poly {n_p}, metal {n_m}, diffusion {n_d}, channels {n_c}, "
        f"vias {n_v}, buried contacts {n_b}")

    # one global id space: metal | poly | diffusion
    off_m, off_p, off_d = 0, n_m, n_m + n_p
    uf = UF(n_m + n_p + n_d)

    dangling = 0
    grazes = []
    for cut, lcut, n_cut, with_metal in ((V, lv, n_v, True), (C, lb, n_b, False)):
        hit = [[] for _ in range(n_cut + 1)]
        size = np.bincount(lcut.ravel(), minlength=n_cut + 1)
        layers = [(lp, off_p), (ld, off_d)] + ([(lm, off_m)] if with_metal else [])
        for lab, off in layers:
            m = (lcut > 0) & (lab > 0)
            pairs, px = np.unique(np.stack([lcut[m], lab[m]], axis=1), axis=0, return_counts=True)
            best = {}
            for (c, r), k in zip(pairs.tolist(), px.tolist()):
                best[c] = max(best.get(c, 0), k)
            for (c, r), k in zip(pairs.tolist(), px.tolist()):
                if k >= 4 and (k == best[c] or k >= MIN_SECOND_SHAPE_FRACTION * size[c]):
                    hit[c].append(off + r - 1)
                elif k >= 4:
                    grazes.append((int(k), int(size[c])))
        for c in range(1, n_cut + 1):
            if len(hit[c]) < 2:
                dangling += 1
            for other in hit[c][1:]:
                uf.union(hit[c][0], other)
    log(f"cuts joining fewer than two regions: {dangling}; grazing overlaps ignored: {grazes}")

    # compact node numbering
    roots = np.array([uf.find(i) for i in range(n_m + n_p + n_d)])
    uniq, node_of = np.unique(roots, return_inverse=True)
    n_nodes = len(uniq)
    node_m = np.concatenate([[-1], node_of[off_m:off_m + n_m]])
    node_p = np.concatenate([[-1], node_of[off_p:off_p + n_p]])
    node_d = np.concatenate([[-1], node_of[off_d:off_d + n_d]])

    # node "capacitance" ~ conductor area (used for charge sharing in the simulator)
    area = np.zeros(n_nodes)
    for lab, nmap, wgt in ((lm, node_m, 1.0), (lp, node_p, 1.0), (ld, node_d, 2.0)):
        cnt = np.bincount(lab.ravel(), minlength=len(nmap))
        np.add.at(area, nmap[1:], cnt[1:] * wgt)

    # transistors
    gate_of = {}
    for c, p in overlap_pairs(lc, lp).tolist():
        gate_of.setdefault(c, set()).add(int(node_p[p]))
    term_of = {}
    for c, d in touching_pairs(lc, ld).tolist():
        term_of.setdefault(c, set()).add(int(node_d[d]))
    cx, cy, cnt = centroids(lc, n_c)
    transistors, capacitors, odd = [], [], []
    for c in range(1, n_c + 1):
        g = sorted(gate_of.get(c, ()))
        t = sorted(term_of.get(c, ()))
        rec = {"x": round(float(cx[c]), 1), "y": round(float(cy[c]), 1), "area": int(cnt[c])}
        if len(g) != 1 or len(t) > 2 or len(t) == 0:
            odd.append({**rec, "gates": g, "terms": t})
        elif len(t) == 1:
            capacitors.append({**rec, "gate": g[0], "node": t[0]})
        else:
            transistors.append({**rec, "gate": g[0], "a": t[0], "b": t[1]})
    log(f"nodes {n_nodes}, transistors {len(transistors)}, "
        f"single-terminal gates (capacitors) {len(capacitors)}, unexplained {len(odd)}")
    for o in odd:
        log("  odd channel:", o)

    pads = {}
    for name, x, y in PADS:
        # pads carry lettering (holes in the metal), so take the dominant region nearby
        win = lm[y - 40:y + 40, x - 40:x + 40]
        cnt = np.bincount(win.ravel())
        cnt[0] = 0
        if cnt.max() < 1500:
            raise SystemExit(f"pad {name}: no pad metal near ({x},{y})")
        pads[name] = int(node_m[cnt.argmax()])
    log("pads:", pads)

    net = {
        "source": "Intel 4004 mask layers (4004.com 35th anniversary project, CC BY-NC-SA 3.0)",
        "size": [int(D.shape[1]), int(D.shape[0])],
        "nodes": n_nodes,
        "area": [int(a) for a in area],
        "pads": pads,
        "transistors": transistors,
        "capacitors": capacitors,
    }
    regions = {"metal": (lm, node_m), "poly": (lp, node_p), "diffusion": (ld, node_d)}
    return net, regions


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    net, _ = extract(src)
    with open(out, "w") as f:
        json.dump(net, f, separators=(",", ":"))
    # compact text form for the C simulator
    with open(out.rsplit(".", 1)[0] + ".net", "w") as f:
        f.write(f"{net['nodes']} {len(net['transistors'])} {len(net['pads'])}\n")
        for name, node in net["pads"].items():
            f.write(f"{name} {node}\n")
        f.write(" ".join(str(a) for a in net["area"]) + "\n")
        for t in net["transistors"]:
            f.write(f"{t['gate']} {t['a']} {t['b']}\n")
    print(f"wrote {out}", file=sys.stderr)
