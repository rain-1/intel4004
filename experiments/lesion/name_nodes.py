#!/usr/bin/env python3
"""Name internal nodes of the intact chip by their behaviour (the landmarks used to check
lesion clusters against the floorplan).

    name_nodes.py PROBE.bin NETLIST_JSON OUT.tsv

PROBE.bin comes from `study --probe FILE --probe-random N`: for every structured test and N
NOP tests from random states, the state of every node at phi2 of each of the 8 slots
(A1..X3) of the instruction's first cycle, plus the initial state that was set up.

A node gets a name if, at some slot, it equals (or is the inverse of) one of:
  * a state bit set up before the instruction, over the random-state tests (>= 99% agreement):
    ACC.b, CY, R<i>.b, ROW<j>.b (physical row j of the 4 x 12-bit address register file:
    the row that is PC depends on the stack pointer), DCL.b, TEST;
  * a timing pattern: same value in every test at each slot, varying between slots (A1..X3);
  * a decode pattern: at X1/X2/X3 the value depends only on the opcode, and the set of
    opcodes where it is 1 (or 0) equals an instruction (group) named on Kintli's schematic,
    or else is reported as an anonymous opcode set.
Output columns: node, category, name, polarity (+ same, - inverted), slot, agreement, x, y
(centroid of the transistors gated by or connected to the node, layout coordinates).
"""
import json
import sys
import numpy as np
from isa import SCHEMATIC_DECODES, mnemonic, NAMES, OPS_OF

SLOTS = ["A1", "A2", "A3", "M1", "M2", "X1", "X2", "X3"]


def load_probe(path, n_nodes):
    rec = 28 * 4 + 8 * n_nodes
    raw = np.fromfile(path, np.uint8)
    n = len(raw) // rec
    raw = raw[: n * rec].reshape(n, rec)
    hdr = raw[:, :112].copy().view(np.int32)
    S = raw[:, 112:].reshape(n, 8, n_nodes)
    return hdr, S


def features(hdr):
    """Named state bits for each record: dict name -> 0/1 array."""
    f = {}
    rot, acc, cy, test, dcl, pc = (hdr[:, i] for i in (2, 3, 4, 5, 6, 7))
    st = hdr[:, 8:11]
    r = hdr[:, 11:27]
    for b in range(4):
        f[f"ACC.{b}"] = (acc >> b) & 1
    f["CY"] = cy
    f["TEST"] = test
    for b in range(3):
        f[f"DCL.{b}"] = (dcl >> b) & 1
    for i in range(16):
        for b in range(4):
            f[f"R{i}.{b}"] = (r[:, i] >> b) & 1
    # physical address rows: after `rot` extra pushes and 3 set-up pushes, PC is in row (rot+3)&3,
    # stack[k] (most recent first) in row (rot+2-k)&3
    rows = np.zeros((len(hdr), 4), np.int64)
    for k in range(len(hdr)):
        rows[k, (rot[k] + 3) & 3] = pc[k]
        for j in range(3):
            rows[k, (rot[k] + 2 - j) & 3] = st[k, j]
    for j in range(4):
        for b in range(12):
            f[f"ROW{j}.{b}"] = (rows[:, j] >> b) & 1
    for b in range(12):
        f[f"PC.{b}"] = (pc >> b) & 1
    return f


def category(feature):
    for prefix, cat in (("ROW", "address register"), ("PC", "program counter"), ("ACC", "accumulator"),
                        ("CY", "carry"), ("TEST", "TEST input"), ("DCL", "DCL register"), ("R", "index register")):
        if feature.startswith(prefix):
            return cat
    return "state"


def main(probe, netpath, out):
    net = json.load(open(netpath))
    nn = net["nodes"]
    T = net["transistors"]
    hdr, S = load_probe(probe, nn)
    rnd = hdr[:, 0] >= 100000
    hs, Ss = hdr[~rnd], S[~rnd]
    hr, Sr = hdr[rnd], S[rnd]
    print(f"probe: {len(hs)} structured + {len(hr)} random-state records", file=sys.stderr)

    # node positions: centroid of all transistors touching the node
    pos = np.zeros((nn, 2)); cnt = np.zeros(nn)
    for t in T:
        for k in {t["gate"], t["a"], t["b"]}:
            pos[k] += (t["x"], t["y"]); cnt[k] += 1
    pos /= np.maximum(cnt, 1)[:, None]
    supplies = {net["pads"]["VDD"], net["pads"]["VSS"]}

    names = {}  # node -> (category, name, pol, slot, agreement)

    # 1. state bits (random-state records)
    F = features(hr)
    fn = list(F)
    Fm = np.array([F[k] for k in fn], np.float32)               # (nf, n)
    X = Sr.astype(np.float32)                                     # (n, 8, nn)
    n = len(hr)
    # storage, not a bus line that carries the value at one moment: the match must hold at >= 5 of
    # the 8 slots (dynamic cells may be inverted or refreshed in some slots)
    best = {}
    hits = np.zeros((len(fn), nn), int)
    for s in range(8):
        agree = (Fm @ X[:, s, :] + (1 - Fm) @ (1 - X[:, s, :])) / n   # (nf, nn)
        a2 = np.maximum(agree, 1 - agree)
        ok = (a2 >= 0.99) & (X[:, s, :].std(axis=0) > 0)[None, :]
        hits += ok
        for node in np.nonzero(ok.any(axis=0))[0]:
            i = int(np.argmax(np.where(ok[:, node], a2[:, node], 0)))
            if node not in best or a2[i, node] > best[node][2]:
                best[node] = (i, s, float(a2[i, node]), "+" if agree[i, node] >= 0.5 else "-")
    for node, (i, s, a, pol) in best.items():
        if node in supplies or hits[i, node] < 5:
            continue
        names[node] = (category(fn[i]), fn[i], pol, SLOTS[s], a)

    # 2. timing: per slot constant over every record, not constant over slots
    Sall = S
    lo, hi = Sall.min(axis=0), Sall.max(axis=0)                   # (8, nn)
    for node in range(nn):
        if node in supplies or node in names:
            continue
        if (lo[:, node] == hi[:, node]).all() and lo[:, node].min() != lo[:, node].max():
            pat = "".join(str(int(v)) for v in lo[:, node])
            on = [SLOTS[i] for i in range(8) if pat[i] == "1"]
            names[node] = ("timing", "+".join(on), "+", "-", 1.0)

    # 3. decode: at X1..X3 the value depends only on the opcode (structured records)
    ops = hs[:, 1]
    for s in (5, 6, 7, 4):
        V = Ss[:, s, :]
        for node in range(nn):
            if node in supplies or node in names:
                continue
            v = V[:, node]
            mn = np.full(256, 2); mx = np.full(256, -1)
            np.minimum.at(mn, ops, v); np.maximum.at(mx, ops, v)
            if (mn != mx).any() or mn.min() == mn.max():
                continue
            ones = frozenset(int(o) for o in np.nonzero(mn == 1)[0])
            zeros = frozenset(range(256)) - ones
            label, pol = None, "+"
            for nm, opset in SCHEMATIC_DECODES.items():
                if ones == opset:
                    label = nm; break
                if zeros == opset:
                    label, pol = nm, "-"; break
            if label is None:
                # a function of one nibble only: instruction register (OPR = high, OPA = low) decode
                for nib, shift, nm in ((0xF0, 0, "OPA"), (0x0F, 4, "OPR")):
                    vals = {(o >> shift) & 15 for o in ones}
                    if ones == frozenset(o for o in range(256) if ((o >> shift) & 15) in vals):
                        bits = [b for b in range(4) if all(((v >> b) & 1) for v in vals) and len(vals) == 8]
                        label = f"{nm}.{bits[0]}" if bits else f"{nm} in {{{','.join(f'{v:X}' for v in sorted(vals))}}}"
                        if len(vals) == 8 and not bits:
                            nb = [b for b in range(4) if not any(((v >> b) & 1) for v in vals)]
                            if nb: label = f"~{nm}.{nb[0]}"
                        break
            if label is None:
                small = ones if len(ones) <= 128 else zeros
                pol = "+" if small is ones else "-"
                insts = sorted({mnemonic(o) for o in small}, key=NAMES.index)
                full = [m for m in insts if set(OPS_OF[m]) <= small]
                part = [m for m in insts if m not in full]
                label = "{" + "+".join(full) + ("" if not part else " part:" + "+".join(part)) + "}"
            names[node] = ("decode", label, pol, SLOTS[s], 1.0)

    with open(out, "w") as f:
        f.write("node\tcategory\tname\tpolarity\tslot\tagreement\tx\ty\n")
        for node in sorted(names):
            c, nm, pol, s, a = names[node]
            f.write(f"{node}\t{c}\t{nm}\t{pol}\t{s}\t{a:.3f}\t{pos[node,0]:.0f}\t{pos[node,1]:.0f}\n")
    from collections import Counter
    print(Counter(v[0] for v in names.values()), file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:4])
