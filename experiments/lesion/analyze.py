#!/usr/bin/env python3
"""Summarise lesion results.

    analyze.py RESULTS NETLIST_JSON [TSV_OUT]

RESULTS: lines from ./lesion (T mode nbad reset_bad nosync unstable bad cyc state).
Classes per lesion:
  none     no test and the reset test differ from the intact chip
  global   NOP (opcode 00) fails, i.e. the set-up/read-out instructions themselves are
           broken, or >= 240 opcodes fail -- "breaks everything"
  reset    only the reset test differs
  broad    >= 12 of the 19 instruction groups fail on some operands (a datapath bit,
           an address bit, a timing signal: data-dependent rather than opcode-specific)
  partial  fewer groups fail: an instruction-class-specific lesion
"""
import json, sys, collections

GROUPS = [("NOP/undef", lambda o: o < 0x10 or o >= 0xFE), ("JCN", lambda o: o >> 4 == 1),
          ("FIM", lambda o: o >> 4 == 2 and not o & 1), ("SRC", lambda o: o >> 4 == 2 and o & 1),
          ("FIN", lambda o: o >> 4 == 3 and not o & 1), ("JIN", lambda o: o >> 4 == 3 and o & 1),
          ("JUN", lambda o: o >> 4 == 4), ("JMS", lambda o: o >> 4 == 5), ("INC", lambda o: o >> 4 == 6),
          ("ISZ", lambda o: o >> 4 == 7), ("ADD", lambda o: o >> 4 == 8), ("SUB", lambda o: o >> 4 == 9),
          ("LD", lambda o: o >> 4 == 0xA), ("XCH", lambda o: o >> 4 == 0xB), ("BBL", lambda o: o >> 4 == 0xC),
          ("LDM", lambda o: o >> 4 == 0xD), ("IO-write", lambda o: o >> 4 == 0xE and o & 15 < 8),
          ("IO-read", lambda o: o >> 4 == 0xE and o & 15 >= 8),
          ("ACC-group", lambda o: 0xF0 <= o <= 0xFD)]


def bits(h):
    v = int(h, 16)
    return [(v >> i) & 1 for i in range(256)]


def kind(t, pads):
    g, a, b = t["gate"], t["a"], t["b"]
    vdd, vss = pads["VDD"], pads["VSS"]
    if g == vdd and vdd in (a, b): return "load"
    if g in (a, b) and vss in (a, b): return "protect"
    if vdd in (a, b): return "pullup"     # driver to VDD (push-pull / superbuffer upper device)
    if vss in (a, b): return "pulldown"
    return "pass"


def main():
    net = json.load(open(sys.argv[2]))
    pads, T = net["pads"], net["transistors"]
    inv = {v: k for k, v in pads.items()}
    rows = []
    for line in open(sys.argv[1]):
        f = line.split()
        t, mode, nbad, rbad, nosync, unst = int(f[0]), f[1], int(f[2]), int(f[3]), int(f[4]), int(f[5])
        bad, cyc, st = bits(f[6]), bits(f[7]), bits(f[8])
        failing = []
        for name, pred in GROUPS:
            ops = [o for o in range(256) if pred(o)]
            n = sum(bad[o] for o in ops)
            if n: failing.append(f"{name}{'' if n == len(ops) else f'({n}/{len(ops)})'}")
        if nbad == 0 and not rbad: cls = "none"
        elif bad[0] or nbad >= 240: cls = "global"
        elif len(failing) >= 12: cls = "broad"
        elif nbad == 0: cls = "reset"
        else: cls = "partial"
        k = kind(T[t], pads)
        rows.append(dict(t=t, mode=mode, cls=cls, nbad=nbad, rbad=rbad, nosync=nosync, unstable=unst,
                         kind=k, x=T[t]["x"], y=T[t]["y"], gate=inv.get(T[t]["gate"], T[t]["gate"]),
                         a=inv.get(T[t]["a"], T[t]["a"]), b=inv.get(T[t]["b"], T[t]["b"]),
                         onlycyc=sum(cyc) > 0 and sum(st) == 0, groups=" ".join(failing)))
    print(f"{len(rows)} lesions")
    for mode in "oc":
        r = [x for x in rows if x["mode"] == mode]
        c = collections.Counter(x["cls"] for x in r)
        print(f"  stuck-{'open' if mode == 'o' else 'closed'}: n={len(r)} " +
              " ".join(f"{k}={c[k]} ({100 * c[k] / len(r):.0f}%)" for k in ("global", "broad", "partial", "reset", "none")))
        kc = collections.defaultdict(collections.Counter)
        for x in r: kc[x["kind"]][x["cls"]] += 1
        for k, cc in sorted(kc.items()):
            print(f"      {k:9s} " + " ".join(f"{c2}={cc[c2]}" for c2 in ("global", "broad", "partial", "reset", "none")))
    print("partial lesions: failing groups")
    for x in rows:
        if x["cls"] in ("partial", "reset", "broad"):
            print(f"  {x['t']:5d}{x['mode']} {x['kind']:8s} ({x['x']:.0f},{x['y']:.0f}) nbad={x['nbad']:3d} reset={x['rbad']}"
                  f"{' pins-only' if x['onlycyc'] else ''}  {x['groups']}")
    print("no-effect lesions")
    for x in rows:
        if x["cls"] == "none":
            print(f"  {x['t']:5d}{x['mode']} {x['kind']:8s} ({x['x']:.0f},{x['y']:.0f}) g={x['gate']} {x['a']}-{x['b']}")
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w") as f:
            keys = list(rows[0].keys())
            f.write("\t".join(keys) + "\n")
            for x in rows: f.write("\t".join(str(x[k]) for k in keys) + "\n")


main()
