#!/usr/bin/env python3
"""Analyse the full lesion sweep (study.c output).

    analyze_study.py [--dir experiments/lesion] [--net netlist/4004.json]

Reads   results/raw_lesions.txt.gz   one line per lesion (format in study.c)
        results/tests.txt            the test table (study --list-tests)
        results/floatprof.txt        intact chip: per node, samples floating (study --floatprof)
        results/node_names.tsv       behavioural node names (name_nodes.py), optional
        results/followup.tsv         peek/fuzz results for unexplained nulls (followup.py), optional
Writes  results/lesions.tsv          one row per lesion (columns documented in RESULTS.txt)
        results/transistors.tsv      one row per transistor: cluster, block, severities
        results/clusters.tsv         the functional clusters
        results/summary.txt          all the numbers quoted in RESULTS.txt
        results/web.json             compact data for web/4004-lesion.html
"""
import collections
import gzip
import json
import math
import os
import sys
import numpy as np
from isa import NAMES, OPS_OF, GROUPS, GROUP_OPS, KIND_BITS, K, K_STATE_DATA, K_STATE_FLOW, K_BUS, mnemonic

ARGS = dict(dir="experiments/lesion", net="netlist/4004.json")
for i, a in enumerate(sys.argv[1:]):
    if a.startswith("--"):
        ARGS[a[2:]] = sys.argv[i + 2]
D = ARGS["dir"]
R = os.path.join(D, "results")
out_lines = []


def say(s=""):
    out_lines.append(s)
    print(s)


# ------------------------------------------------------------------------------------
# inputs

net = json.load(open(ARGS["net"]))
P, T = net["pads"], net["transistors"]
VDD, VSS = P["VDD"], P["VSS"]
padname = {}
for k, v in P.items():
    padname.setdefault(v, k)
NT = len(T)
align = json.load(open(os.path.join(os.path.dirname(ARGS["net"]), "photo_align.json")))
A = np.array(align["affine"])
H_LAYOUT = net["size"][1]


def photo_xy(x, y, scale=2):
    """layout (x, y) -> pixel in the half-size photo used by the figures and the web page"""
    px, py = A @ [H_LAYOUT - 1 - y, x, 1]
    return px / scale, py / scale


tests = []
for line in open(os.path.join(R, "tests.txt")):
    if line.startswith("#"):
        continue
    f = line.split()
    tests.append(dict(idx=int(f[0]), op=int(f[1], 16), why=" ".join(f[16:])))
NTEST = len(tests)
test_op = np.array([t["op"] for t in tests])
test_inst = np.array([NAMES.index(mnemonic(o)) for o in test_op])

rows = []
opener = gzip.open if os.path.exists(os.path.join(R, "raw_lesions.txt.gz")) else open
rawpath = os.path.join(R, "raw_lesions.txt.gz") if opener is gzip.open else os.path.join(R, "raw_lesions.txt")
for line in opener(rawpath, "rt"):
    f = line.split()
    if len(f) < 14:
        continue
    kinds = np.frombuffer(bytes.fromhex(f[13]), dtype=">u2").astype(np.uint16)
    assert len(kinds) == NTEST, (f[0], len(kinds))
    rows.append(dict(t=int(f[0]), mode=f[1], nfail=int(f[2]), nbad=int(f[3]), rmask=int(f[4]), nosync=int(f[5]),
                     unst=int(f[6]), cont=int(f[7]), fl=[int(f[8]), int(f[9]), int(f[10])], samples=int(f[11]),
                     ms=int(f[12]), kinds=kinds))
rows.sort(key=lambda r: (r["t"], r["mode"]))
by = {(r["t"], r["mode"]): r for r in rows}

gfloat = np.zeros(net["nodes"])
fp = os.path.join(R, "floatprof.txt")
if os.path.exists(fp):
    for line in open(fp):
        n, c, s = map(int, line.split())
        gfloat[n] = c

names = {}
nnp = os.path.join(R, "node_names.tsv")
if os.path.exists(nnp):
    for line in list(open(nnp))[1:]:
        f = line.rstrip("\n").split("\t")
        names[int(f[0])] = dict(cat=f[1], name=f[2], pol=f[3], slot=f[4])

follow = {}
fup = os.path.join(R, "followup.tsv")
if os.path.exists(fup):
    hdr = None
    for line in open(fup):
        f = line.rstrip("\n").split("\t")
        if hdr is None:
            hdr = f; continue
        d = dict(zip(hdr, f))
        follow[(int(d["t"]), d["mode"])] = d

# ------------------------------------------------------------------------------------
# device classes and structure

def dev_class(t):
    g, a, b = t["gate"], t["a"], t["b"]
    if g == VDD and VDD in (a, b): return "load"
    if g in (a, b) and VSS in (a, b): return "protect"
    if VDD in (a, b): return "pullup"
    if VSS in (a, b): return "pulldown"
    return "pass"


DEV = [dev_class(t) for t in T]
EXT_DRIVEN = {P["TEST"], P["RESET"], P["PHI1"], P["PHI2"]}
CLOCKS = {P["PHI1"], P["PHI2"]}
par = collections.Counter((t["gate"], min(t["a"], t["b"]), max(t["a"], t["b"])) for t in T)
PARALLEL = [par[(t["gate"], min(t["a"], t["b"]), max(t["a"], t["b"]))] > 1 for t in T]
has_load = np.zeros(net["nodes"], bool)
for t, d in zip(T, DEV):
    if d == "load":
        has_load[t["a"] if t["b"] == VDD else t["b"]] = True
# gate nodes that never change: driven only by loads (bootstrapped-load gates), or constant in every
# intact-chip probe sample (all tests, all 8 slots, at phi2)
only_loads = np.zeros(net["nodes"], bool)
chan_devs = collections.defaultdict(list)
for t, d in zip(T, DEV):
    for n in (t["a"], t["b"]):
        chan_devs[n].append(d)
for n, ds in chan_devs.items():
    only_loads[n] = all(d == "load" for d in ds)
const_val = np.full(net["nodes"], -1)
pp = os.path.join(R, "probe.bin")
if os.path.exists(pp):
    nn_ = net["nodes"]
    raw = np.fromfile(pp, np.uint8)
    rec = 112 + 8 * nn_
    Sp = raw[: len(raw) // rec * rec].reshape(-1, rec)[:, 112:].reshape(-1, 8, nn_)
    mn, mx = Sp.min(axis=(0, 1)), Sp.max(axis=(0, 1))
    const_val = np.where(mn == mx, mn.astype(int), -1)
    del raw, Sp
XY = np.array([(t["x"], t["y"]) for t in T])
PXY = np.array([photo_xy(t["x"], t["y"]) for t in T])


def nname(n):
    if n in padname: return padname[n]
    if n in names:
        nm = names[n]["name"]
        if len(nm) > 28: nm = "decode:" + nm.lstrip("{")[:19].split("+")[0] + "+..."
        return f"{n}({'~' if names[n]['pol'] == '-' else ''}{nm})"
    return str(n)


# ------------------------------------------------------------------------------------
# per-lesion derived quantities

FLOAT_MARGIN = 0.005   # lesion makes a node float in >0.5% more of the samples than intact


def derive(r):
    k = r["kinds"]
    t = T[r["t"]]
    fail = k != 0
    r["fail"] = fail
    r["union"] = int(np.bitwise_or.reduce(k)) if fail.any() else 0
    inst_frac = np.zeros(len(NAMES))
    for i in range(len(NAMES)):
        m = test_inst == i
        inst_frac[i] = fail[m].mean()
    r["inst_frac"] = inst_frac
    ops_bad = set(int(o) for o in test_op[fail])
    r["ops_bad"] = ops_bad
    groups = []
    for g, ops in GROUP_OPS.items():
        n = len(ops_bad.intersection(ops))
        if n: groups.append((g, n, len(ops)))
    r["groups"] = groups
    nop_fail = fail[test_op == 0].any()
    if not fail.any():
        sev = "reset-only" if r["rmask"] else "none"
    elif nop_fail or r["nbad"] >= 240:
        sev = "global"
    elif len(groups) >= 12:
        sev = "broad"
    else:
        sev = "partial"
    r["sev"] = sev
    u = r["union"]
    if u & K["UNST"]: eff = "non-convergence"
    elif u & (K["SYNC"] | K["NOSYNC"]): eff = "SYNC/timing"
    elif u & K_STATE_DATA and u & K_STATE_FLOW: eff = "data + PC/stack"
    elif u & K_STATE_DATA: eff = "register/acc/carry"
    elif u & K_STATE_FLOW: eff = "PC/stack"
    elif u & (K["CMRAM"] | K["CM"]): eff = "CM lines"
    elif u & K_BUS: eff = "bus contents only"
    elif u & K["XUND"]: eff = "undocumented X2/X3 only"
    elif r["rmask"]: eff = "reset only"
    else: eff = "no effect"
    r["eff"] = eff
    # artefact flags
    nodes = [t["gate"], t["a"], t["b"]]
    fl = []
    for i, n in enumerate(nodes):
        if r["fl"][i] >= 0 and r["samples"]:
            if (r["fl"][i] - gfloat[n]) / r["samples"] > FLOAT_MARGIN:
                fl.append(n)
    flags = []
    if r["unst"]: flags.append("settle-cap")
    if r["nosync"]: flags.append("nosync")
    if r["cont"]: flags.append("contention")
    if fl: flags.append("floats")
    if t["gate"] in CLOCKS: flags.append("clock")
    if any(n in EXT_DRIVEN for n in nodes): flags.append("ext-pin")
    if PARALLEL[r["t"]]: flags.append("parallel")
    term = [n for n in (t["a"], t["b"]) if n not in (VDD, VSS)]
    if term and not any(has_load[n] for n in term) and DEV[r["t"]] != "load": flags.append("dynamic-node")
    r["flags"] = flags
    r["float_nodes"] = fl
    # explanation of a null
    expl = ""
    if sev == "none":
        d = DEV[r["t"]]
        if d == "load" and r["mode"] == "c": expl = "by construction: load already always on"
        elif d == "protect" and r["mode"] == "o": expl = "by construction: protection device never conducts"
        elif r["mode"] == "c" and only_loads[t["gate"]]: expl = "by construction: gate node fed only by loads (always on)"
        elif const_val[t["gate"]] == (1 if r["mode"] == "c" else 0): expl = "gate constant in the intact chip (device already always " + ("on)" if r["mode"] == "c" else "off)")
        elif "ext-pin" in flags: expl = "ideal external pin driver"
        elif "parallel" in flags and r["mode"] == "o": expl = "parallel duplicate device"
        elif r["mode"] == "c" and "contention" in flags: expl = "VSS-wins resolution of a fight"
        elif r["mode"] == "o" and "floats" in flags: expl = "node keeps charge (no leakage)"
        elif "clock" in flags: expl = "clocked device (no delays modelled)"
        else: expl = "unexplained"
    r["expl"] = expl


for r in rows:
    derive(r)

# ------------------------------------------------------------------------------------
# headline tables

say("LESION STUDY: FULL SWEEP")
say(f"{len(rows)} lesions ({len(set(r['t'] for r in rows))} transistors), {NTEST} tests + 3 reset tests each")
tot_ms = sum(r["ms"] for r in rows)
say(f"CPU time in lesion runs: {tot_ms / 3.6e6:.2f} h ({tot_ms / 1000 / len(rows):.1f} s per lesion)")
say()
SEV = ["global", "broad", "partial", "reset-only", "none"]
EFF = ["non-convergence", "SYNC/timing", "data + PC/stack", "register/acc/carry", "PC/stack", "CM lines",
       "bus contents only", "undocumented X2/X3 only", "reset only", "no effect"]


def table(title, keyf, cats):
    say(title)
    say(f"  {'':24s} {'stuck-open':>16s} {'stuck-closed':>16s} {'closed, no loads':>18s}")
    for c in cats:
        cells = []
        for sel in (lambda r: r["mode"] == "o", lambda r: r["mode"] == "c",
                    lambda r: r["mode"] == "c" and DEV[r["t"]] != "load"):
            rr = [r for r in rows if sel(r)]
            n = sum(keyf(r) == c for r in rr)
            cells.append(f"{n:5d} ({100 * n / max(len(rr), 1):4.1f}%)")
        say(f"  {c:24s} {cells[0]:>16s} {cells[1]:>16s} {cells[2]:>18s}")
    say()


table("Severity (global = NOP fails or >= 240 opcodes; broad = >= 12 of 19 groups; partial = fewer):",
      lambda r: r["sev"], SEV)
table("Effect class (first match in this order; 'data' = acc/carry/index registers):", lambda r: r["eff"], EFF)

say("Failure kinds present (multi-label; % of lesions with any failing test):")
for mode in "oc":
    rr = [r for r in rows if r["mode"] == mode and r["union"]]
    say(f"  stuck-{'open' if mode == 'o' else 'closed'} (n={len(rr)}): " + " ".join(
        f"{kn}={sum(1 for r in rr if r['union'] & K[kn])}" for kn in KIND_BITS))
say()

say("Severity by device class:")
for mode in "oc":
    say(f"  stuck-{'open' if mode == 'o' else 'closed'}")
    for d in ("load", "pullup", "pulldown", "pass", "protect"):
        rr = [r for r in rows if r["mode"] == mode and DEV[r["t"]] == d]
        c = collections.Counter(r["sev"] for r in rr)
        say(f"    {d:9s} n={len(rr):4d} " + " ".join(f"{s}={c[s]}" for s in SEV))
say()

say("Artefact flags (lesions with the flag / of which no effect):")
for mode in "oc":
    rr = [r for r in rows if r["mode"] == mode]
    fc = collections.Counter(f for r in rr for f in r["flags"])
    fn = collections.Counter(f for r in rr if r["sev"] == "none" for f in r["flags"])
    say(f"  stuck-{'open' if mode == 'o' else 'closed'}: " + " ".join(f"{f}={fc[f]}/{fn[f]}" for f in sorted(fc)))
say()

# ------------------------------------------------------------------------------------
# nulls

say("No-effect lesions by explanation (first match in this order):")
EXPL = ["by construction: load already always on", "by construction: protection device never conducts",
        "by construction: gate node fed only by loads (always on)", "gate constant in the intact chip (device already always on)",
        "gate constant in the intact chip (device already always off)",
        "ideal external pin driver", "parallel duplicate device", "VSS-wins resolution of a fight",
        "node keeps charge (no leakage)", "clocked device (no delays modelled)", "unexplained"]
for mode in "oc":
    rr = [r for r in rows if r["mode"] == mode and r["sev"] == "none"]
    c = collections.Counter(r["expl"] for r in rr)
    say(f"  stuck-{'open' if mode == 'o' else 'closed'}: {len(rr)} no-effect")
    for e in EXPL:
        say(f"     {c[e]:5d}  {e}")
unexpl = [r for r in rows if r["expl"] == "unexplained"]
say(f"  unexplained in total: {len(unexpl)} ({sum(r['mode'] == 'o' for r in unexpl)} open, "
    f"{sum(r['mode'] == 'c' for r in unexpl)} closed)")
c = collections.Counter(DEV[r["t"]] for r in unexpl)
say("  unexplained by device class: " + " ".join(f"{k}={v}" for k, v in c.most_common()))
c = collections.Counter(f for r in unexpl for f in r["flags"])
say("  flags among unexplained: " + " ".join(f"{k}={v}" for k, v in c.most_common()))
say()
with open(os.path.join(R, "unexplained.txt"), "w") as f:
    for r in unexpl:
        f.write(f"{r['t']}{r['mode']}\n")

POINTER_NODES = set()
if os.path.exists(pp):
    # nodes that carry the address-stack pointer (equal to bit 0/1 of the set-up stack position in
    # >= 99.5% of the probe records at some slot)
    raw = np.fromfile(pp, np.uint8)
    rec = 112 + 8 * net["nodes"]
    raw = raw[: len(raw) // rec * rec].reshape(-1, rec)
    Hp = raw[:, :112].copy().view(np.int32)
    Sp = raw[:, 112:].reshape(-1, 8, net["nodes"])
    for b in (0, 1):
        f = ((Hp[:, 2] >> b) & 1)[:, None, None]
        a = (Sp == f).mean(axis=0)
        POINTER_NODES |= set(np.nonzero((np.maximum(a, 1 - a) > 0.995).any(axis=0))[0].tolist())
    del raw, Sp


def follow_class(r):
    d = follow.get((r["t"], r["mode"]))
    if not d: return ""
    if d["verdict"] != "masked": return d["verdict"]
    t = T[r["t"]]
    nodes = [int(x.split(":")[0]) for x in d["peek_top"].split(",") if x]
    if int(d["peek_nodes"]) <= 8 and set(nodes) <= {t["gate"], t["a"], t["b"]}:
        return "masked: only the device's own nodes differ"
    if set(nodes[:3]) & POINTER_NODES:
        return "masked: stack-pointer bit consistently inverted (row relabelling)"
    return "masked: internal difference does not reach the pins"


for r in rows:
    r["follow"] = follow_class(r) if r["expl"] == "unexplained" else ""
if follow:
    say("Follow-up of the unexplained nulls (followup.py: lockstep internal comparison + 300 random programs):")
    fc = collections.Counter(r["follow"] for r in unexpl)
    for k, v in fc.most_common():
        say(f"  {v:5d}  {k}")
    for r in unexpl:
        d = follow.get((r["t"], r["mode"]))
        if d and d["verdict"] == "test gap":
            say(f"    test gap T{r['t']}{r['mode']}: caught by {d['fuzz_caught']}/300 programs; minimal: {d['minimal']}")
    say()

# ------------------------------------------------------------------------------------
# functional clustering (per transistor)

INST_N = len(NAMES)
# coarse failure-kind features for clustering
KIND_GROUPS = {"ACC/CY": K["ACC"] | K["CY"], "REG": K["REG"], "PC/STACK": K_STATE_FLOW, "CM": K["CMRAM"] | K["CM"],
               "BUS": K_BUS, "XUND": K["XUND"], "SYNC": K["SYNC"] | K["NOSYNC"]}
KIND_FEATS = list(KIND_GROUPS)


IDLE = np.isin(test_inst, [NAMES.index("NOP"), NAMES.index("undef")])


def kind_groups(mask):
    return [bool(mask & KIND_GROUPS[k]) for k in KIND_FEATS]


def tr_signature(t):
    """instructions broken (either mode); failure kinds on idle (NOP/undefined) tests, i.e. state
    that is lost or misread with no instruction acting on it; failure kinds on all other tests"""
    inst = np.zeros(INST_N, bool)
    idle = active = 0
    reset = 0
    for m in "oc":
        r = by.get((t, m))
        if r is None: continue
        inst |= r["inst_frac"] > 0
        k = r["kinds"]
        if (k[IDLE] != 0).any(): idle |= int(np.bitwise_or.reduce(k[IDLE]))
        if (k[~IDLE] != 0).any(): active |= int(np.bitwise_or.reduce(k[~IDLE]))
        reset |= bool(r["rmask"])
    return inst, idle, active, reset


sig = {}
for t in range(NT):
    inst, idle, active, reset = tr_signature(t)
    vec = np.concatenate([inst, kind_groups(idle), kind_groups(active), [reset]]).astype(bool)
    sig[t] = vec
FEAT = NAMES + ["idle:" + k for k in KIND_FEATS] + ["k:" + k for k in KIND_FEATS] + ["RESET"]

# exact groups first
groups = collections.defaultdict(list)
for t, v in sig.items():
    groups[v.tobytes()].append(t)
keys = list(groups)
vecs = np.array([np.frombuffer(k, dtype=bool) for k in keys])
sizes = np.array([len(groups[k]) for k in keys], float)
say(f"Distinct transistor signatures (instructions broken in either mode + failure kinds + reset): {len(keys)}")

# average-linkage agglomeration on Jaccard distance of the instruction part, with kinds as a
# secondary part (weight 0.5): stops when the closest pair is further apart than CUT
CUT = 0.3


def jacc(a, b):
    u = (a | b).sum()
    return 0.0 if u == 0 else 1 - (a & b).sum() / u


ni = INST_N
def dist(a, b):
    nk = len(KIND_FEATS)
    return (jacc(a[:ni], b[:ni]) + jacc(a[ni:ni + nk], b[ni:ni + nk]) + jacc(a[ni + nk:], b[ni + nk:])) / 3


clusters = [[i] for i in range(len(keys))]
Dm = np.array([[dist(vecs[i], vecs[j]) for j in range(len(keys))] for i in range(len(keys))])
empty = np.where(~vecs.any(axis=1))[0]
everything_inst = vecs[:, :ni].all(axis=1)
active = [c for c in clusters]


def cdist(c1, c2):
    w1, w2 = sizes[c1], sizes[c2]
    return float((Dm[np.ix_(c1, c2)] * np.outer(w1, w2)).sum() / (w1.sum() * w2.sum()))


while True:
    best = None
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            # never merge the no-effect signature with anything
            if (len(a) == 1 and a[0] in empty) or (len(b) == 1 and b[0] in empty): continue
            d = cdist(a, b)
            if best is None or d < best[0]:
                best = (d, i, j)
    if best is None or best[0] > CUT:
        break
    d, i, j = best
    active[i] = active[i] + active[j]
    del active[j]

cl_members = []
for c in active:
    mem = sorted(t for i in c for t in groups[keys[i]])
    cl_members.append(mem)
cl_members.sort(key=lambda m: -len(m))


def describe(mem):
    V = np.array([sig[t] for t in mem])
    frac = V.mean(axis=0)
    nk = len(KIND_FEATS)
    inst_core = [NAMES[i] for i in range(ni) if frac[i] >= 0.75]
    inst_any = [NAMES[i] for i in range(ni) if frac[i] > 0]
    idle_core = [KIND_FEATS[i] for i in range(nk) if frac[ni + i] >= 0.5]
    act_core = [KIND_FEATS[i] for i in range(nk) if frac[ni + nk + i] >= 0.5]
    if not inst_any and not frac[-1]:
        return "no effect", inst_core, inst_any, act_core
    if len(inst_core) >= ni - 2:
        name = "every instruction"
    elif not inst_core:
        name = ("reset only" if frac[-1] >= 0.5 else "mixed")
    else:
        name = "+".join(compress(inst_core))
        if set(inst_any) <= set(inst_core):
            name = "only " + name
    if idle_core:
        name += "; idle: " + ",".join(idle_core)
    if act_core:
        name += " [" + ",".join(act_core) + "]"
    return name, inst_core, inst_any, (["idle:" + k for k in idle_core] + act_core)


def compress(insts):
    s = list(insts)
    for grp, members in (("I/O-write", NAMES[17:25]), ("I/O-read", NAMES[25:33]), ("acc-group", NAMES[33:47])):
        if all(m in s for m in members):
            s = [x for x in s if x not in members] + [grp]
    return s


# ------------------------------------------------------------------------------------
# floorplan blocks from behaviourally named nodes

BLOCK_OF_CAT = {"index register": "index registers", "address register": "address stack array",
                "program counter": "PC path", "accumulator": "accumulator/carry", "carry": "accumulator/carry",
                "timing": "timing", "decode": "instruction decode", "DCL register": "DCL/CM-RAM",
                "TEST input": "TEST input"}
tr_block = ["" for _ in range(NT)]
if names:
    for i, t in enumerate(T):
        cats = collections.Counter()
        for n in (t["gate"], t["a"], t["b"]):
            if n in names and names[n]["cat"] in BLOCK_OF_CAT:
                cats[BLOCK_OF_CAT[names[n]["cat"]]] += 2 if n == t["gate"] else 1
        if cats:
            tr_block[i] = cats.most_common(1)[0][0]
    # pads
    for i, t in enumerate(T):
        if not tr_block[i]:
            for n in (t["gate"], t["a"], t["b"]):
                if n in padname and padname[n] not in ("VDD", "VSS", "VSS2"):
                    tr_block[i] = "pad " + padname[n]
# spatial extension: unlabelled transistors take the majority label of their 7 nearest labelled
lab_idx = np.array([i for i in range(NT) if tr_block[i] and not tr_block[i].startswith("pad")])
region = list(tr_block)
if len(lab_idx):
    for i in range(NT):
        if not region[i]:
            d = np.hypot(*(XY[lab_idx] - XY[i]).T)
            nn = lab_idx[np.argsort(d)[:7]]
            region[i] = "~" + collections.Counter(tr_block[j] for j in nn).most_common(1)[0][0]

rng = np.random.default_rng(4004)


def spread(idx):
    p = XY[idx]
    return float(np.median(np.hypot(*(p - np.median(p, axis=0)).T)))


def compact_p(mem, n_perm=2000):
    if len(mem) < 3:
        return float("nan"), float("nan")
    s = spread(mem)
    null = np.array([spread(rng.choice(NT, len(mem), replace=False)) for _ in range(n_perm)])
    return s, float((1 + (null <= s).sum()) / (n_perm + 1))


say()
say("FUNCTIONAL CLUSTERS (per transistor; Jaccard average linkage, cut %.2f)" % CUT)
say("  spread = median distance of members from their median point (layout px; die is 1968 x 2706);")
say("  p = fraction of 2000 random same-size transistor sets at least as compact; blocks = behaviourally")
say("  named region of the members (~ = nearest named neighbours)")
cl_rows = []
tr_cluster = [-1] * NT
for ci, mem in enumerate(cl_members):
    name, core, anyi, kc = describe(mem)
    for t in mem:
        tr_cluster[t] = ci
    s, p = compact_p(mem) if name not in ("no effect", "every instruction") else (spread(mem), float("nan"))
    blk = collections.Counter(region[t].lstrip("~") for t in mem)
    cx, cy = np.median(XY[mem], axis=0)
    cl_rows.append(dict(id=ci, n=len(mem), name=name, core=core, any=anyi, kinds=kc, spread=s, p=p,
                        blocks=blk.most_common(4), cx=cx, cy=cy))
    if len(mem) >= 3 or ci < 40:
        say(f"  C{ci:<3d} n={len(mem):4d} spread={s:6.0f} p={p:.4f} at ({cx:.0f},{cy:.0f})  {name}")
        if anyi and set(anyi) != set(core) and len(anyi) < ni - 2:
            say(f"        some members also: {'+'.join(compress([a for a in anyi if a not in core]))}")
        say(f"        blocks: " + ", ".join(f"{b or '?'} {n}" for b, n in blk.most_common(4)))
small = [c for c in cl_rows if c["n"] < 3]
say(f"  ... plus {len(small)} clusters with 1-2 members")
say()

# ------------------------------------------------------------------------------------
# single-instruction / single-flag lesions, undocumented bus

say("Narrow lesions:")
single_inst = [r for r in rows if r["sev"] in ("partial",) and len({mnemonic(o) for o in r["ops_bad"]}) == 1]
c = collections.Counter(mnemonic(next(iter(r["ops_bad"]))) for r in single_inst)
say(f"  lesions breaking exactly one instruction (all failing opcodes share one mnemonic): {len(single_inst)}")
say("    " + " ".join(f"{k}:{v}" for k, v in sorted(c.items(), key=lambda x: -x[1])))
for r in single_inst:
    kn = [kk for kk in KIND_BITS if r["union"] & K[kk]]
    inst = mnemonic(next(iter(r["ops_bad"])))
    nf = int(r["fail"].sum())
    nt_inst = int((test_inst == NAMES.index(inst)).sum())
    say(f"    T{r['t']}{r['mode']:1s} {DEV[r['t']]:8s} ({T[r['t']]['x']:.0f},{T[r['t']]['y']:.0f}) {inst:5s} "
        f"{len(r['ops_bad'])} opcode(s), {nf}/{nt_inst} tests  kinds={','.join(kn)}  "
        f"g={nname(T[r['t']]['gate'])} {nname(T[r['t']]['a'])}-{nname(T[r['t']]['b'])}")
single_flag = [r for r in rows if r["union"] and bin(r["union"] & ~(K["UNST"] | K["NOSYNC"])).count("1") == 1
               and not r["rmask"]]
say(f"  lesions with exactly one failure kind: {len(single_flag)}  " + " ".join(
    f"{k}:{v}" for k, v in collections.Counter(next(kk for kk in KIND_BITS if r['union'] & K[kk]) for r in single_flag).most_common()))
only_cy = [r for r in single_flag if r["union"] == K["CY"]]
for r in only_cy:
    say(f"    carry only: T{r['t']}{r['mode']} {DEV[r['t']]} ({T[r['t']]['x']:.0f},{T[r['t']]['y']:.0f}) "
        f"instructions: {'+'.join(compress(sorted({mnemonic(o) for o in r['ops_bad']}, key=NAMES.index)))} "
        f"({int(r['fail'].sum())} tests)")
xund = [r for r in rows if r["union"] and not (r["union"] & ~(K["XUND"] | K["DRV"])) and not r["rmask"]]
say(f"  lesions whose ONLY effect is on undocumented X2/X3 bus contents (+/- drive): {len(xund)}")
for r in xund:
    insts = sorted({mnemonic(o) for o in r["ops_bad"]}, key=NAMES.index)
    say(f"    T{r['t']}{r['mode']} {DEV[r['t']]:8s} ({T[r['t']]['x']:.0f},{T[r['t']]['y']:.0f}) "
        f"{'+'.join(compress(insts))}  ({int(r['fail'].sum())} tests)  g={nname(T[r['t']]['gate'])} "
        f"{nname(T[r['t']]['a'])}-{nname(T[r['t']]['b'])}")
pins_only = [r for r in rows if r["union"] and not (r["union"] & (K_STATE_DATA | K_STATE_FLOW | K["CMRAM"]))]
say(f"  lesions with pin/bus differences but correct final state in every test: {len(pins_only)}")
say()

# ------------------------------------------------------------------------------------
# coverage: what the pilot's K=2 random tests and K=16 recheck found

def load_pilot(path):
    d = {}
    if not os.path.exists(path): return d
    for line in open(path):
        f = line.split()
        d[(int(f[0]), f[1])] = (int(f[2]), int(f[3]))
    return d


k2 = load_pilot(os.path.join(D, "pilot_k2.txt"))
k16 = load_pilot(os.path.join(D, "recheck_k16.txt"))
say("Coverage against the pilot's random tests:")
caught16 = [k for k, v in k16.items() if (v[0] or v[1]) and k in k2 and not (k2[k][0] or k2[k][1]) and k in by]
say(f"  caught only with 16 random tests per opcode (pilot recheck): {len(caught16)} "
    f"-> caught by the structured set: {sum(1 for k in caught16 if by[k]['sev'] != 'none')}")
for k in sorted(caught16):
    r = by[k]
    say(f"    {k[0]}{k[1]}: structured set {r['sev']}, {int(r['fail'].sum())} tests fail, "
        f"{'+'.join(compress(sorted({mnemonic(o) for o in r['ops_bad']}, key=NAMES.index)))}")
both = [k for k in k2 if k in by]
k2_hit = [k for k in both if k2[k][0] or k2[k][1]]
missed = [k for k in k2_hit if by[k]["sev"] == "none"]
gained = [k for k in both if not (k2[k][0] or k2[k][1]) and by[k]["sev"] != "none"]
say(f"  pilot sample (K=2 random, {len(both)} lesions): K=2 found {len(k2_hit)} with an effect; the structured set "
    f"misses {len(missed)} of them {[f'{a}{b}' for a, b in missed]} and finds {len(gained)} more")
say()

# ------------------------------------------------------------------------------------
# Jonas & Kording comparison (stuck-closed)

say("Comparison with Jonas & Kording 2017 (6502, stuck-closed only, 3 games, 3510 transistors):")
say("  6502: no effect 1565 (44.6%), all three games 1560 (44.4%), two 200 (5.7%), one 186 (5.3%)")
rc = [r for r in rows if r["mode"] == "c"]
nn_ = sum(r["sev"] == "none" for r in rc)
gl = sum(r["sev"] == "global" for r in rc)
say(f"  4004 stuck-closed: no effect {nn_} ({100 * nn_ / len(rc):.1f}%), global {gl} ({100 * gl / len(rc):.1f}%), "
    f"broad+partial+reset {len(rc) - nn_ - gl} ({100 * (len(rc) - nn_ - gl) / len(rc):.1f}%)")
rcn = [r for r in rc if DEV[r["t"]] != "load"]
nn2 = sum(r["sev"] == "none" for r in rcn)
gl2 = sum(r["sev"] == "global" for r in rcn)
say(f"  4004 stuck-closed excluding loads: no effect {nn2} ({100 * nn2 / len(rcn):.1f}%), global {gl2} "
    f"({100 * gl2 / len(rcn):.1f}%)")
say()

# ------------------------------------------------------------------------------------
# outputs

def fmt_groups(r):
    return " ".join(f"{g}" + ("" if n == m else f"({n}/{m})") for g, n, m in r["groups"])


with open(os.path.join(R, "lesions.tsv"), "w") as f:
    cols = ["t", "mode", "x", "y", "photo_x", "photo_y", "device", "gate", "a", "b", "severity", "effect",
            "n_fail_tests", "n_bad_opcodes", "reset_mask", "nosync", "unstable", "contention", "float_nodes",
            "flags", "null_explanation", "kinds", "instructions", "groups", "cluster", "block"]
    f.write("\t".join(cols) + "\n")
    for r in rows:
        t = T[r["t"]]
        insts = sorted({mnemonic(o) for o in r["ops_bad"]}, key=NAMES.index)
        px, py = PXY[r["t"]]
        f.write("\t".join(str(v) for v in [
            r["t"], r["mode"], t["x"], t["y"], f"{px:.1f}", f"{py:.1f}", DEV[r["t"]], nname(t["gate"]),
            nname(t["a"]), nname(t["b"]), r["sev"], r["eff"], int(r["fail"].sum()), r["nbad"], r["rmask"],
            r["nosync"], r["unst"], r["cont"], ",".join(map(str, r["float_nodes"])), ",".join(r["flags"]),
            r["expl"], ",".join(kk for kk in KIND_BITS if r["union"] & K[kk]),
            " ".join(f"{n}:{int(round(100 * r['inst_frac'][NAMES.index(n)]))}" for n in insts), fmt_groups(r),
            tr_cluster[r["t"]], region[r["t"]]]) + "\n")

with open(os.path.join(R, "clusters.tsv"), "w") as f:
    f.write("cluster\tn\tname\tcore_instructions\tany_instructions\tcore_kinds\tspread\tp_compact\tcentre_x\tcentre_y\tblocks\n")
    for c in cl_rows:
        f.write(f"{c['id']}\t{c['n']}\t{c['name']}\t{'+'.join(c['core'])}\t{'+'.join(c['any'])}\t{','.join(c['kinds'])}\t"
                f"{c['spread']:.0f}\t{c['p']:.4f}\t{c['cx']:.0f}\t{c['cy']:.0f}\t"
                + "; ".join(f"{b or '?'}:{n}" for b, n in c["blocks"]) + "\n")

with open(os.path.join(R, "transistors.tsv"), "w") as f:
    f.write("t\tx\ty\tdevice\tgate\ta\tb\tsev_open\tsev_closed\tcluster\tcluster_name\tblock\n")
    for i, t in enumerate(T):
        f.write(f"{i}\t{t['x']}\t{t['y']}\t{DEV[i]}\t{nname(t['gate'])}\t{nname(t['a'])}\t{nname(t['b'])}\t"
                f"{by[(i, 'o')]['sev'] if (i, 'o') in by else ''}\t{by[(i, 'c')]['sev'] if (i, 'c') in by else ''}\t"
                f"{tr_cluster[i]}\t{cl_rows[tr_cluster[i]]['name'] if tr_cluster[i] >= 0 else ''}\t{region[i]}\n")

# web data: per transistor compact record
web = dict(names=NAMES, kinds=KIND_BITS, sev=SEV, eff=EFF,
           clusters=[dict(id=c["id"], n=c["n"], name=c["name"]) for c in cl_rows], tr=[])
for i, t in enumerate(T):
    rec = dict(x=round(float(PXY[i][0]), 1), y=round(float(PXY[i][1]), 1), d=DEV[i],
               g=nname(t["gate"]), a=nname(t["a"]), b=nname(t["b"]), cl=tr_cluster[i], blk=region[i])
    for m in "oc":
        r = by.get((i, m))
        if r is None: continue
        rec[m] = dict(s=SEV.index(r["sev"]), e=EFF.index(r["eff"]), nf=int(r["fail"].sum()),
                      i=[int(round(100 * v)) for v in r["inst_frac"]], k=r["union"], r=r["rmask"],
                      f=r["flags"], x=r["expl"],
                      fu=r.get("follow", ""))
    web["tr"].append(rec)
json.dump(web, open(os.path.join(R, "web.json"), "w"), separators=(",", ":"))
open(os.path.join(R, "summary.txt"), "w").write("\n".join(out_lines) + "\n")
