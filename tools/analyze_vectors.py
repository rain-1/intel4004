#!/usr/bin/env python3
"""What do the transistor-level test vectors say?

    analyze_vectors.py vectors/v1

1. Checks every documented instruction against the behaviour described in the MCS-4
   manual (which is also what MAME's mcs40 core implements).
2. For opcodes the manual leaves undefined, finds which documented behaviour they match.
3. Works out what the CPU puts on the data bus in X1, X2 and X3.
"""
import collections
import glob
import gzip
import json
import sys

A1, A2, A3, M1, M2, X1, X2, X3 = range(8)
KBP = [0, 1, 2, 15, 3, 15, 15, 15, 4, 15, 15, 15, 15, 15, 15, 15]
DCL_LINES = [1, 2, 4, 6, 8, 10, 12, 14]


def manual(op, t):
    """Final state according to the manual, or None if the manual doesn't define op."""
    i = t["initial"]
    s = dict(pc=i["pc"], acc=i["acc"], cy=i["cy"], r=list(i["r"]), stack=list(i["stack"]),
             cm_ram=DCL_LINES[i["dcl"]])
    arg = t["fed"][1] if len(t["fed"]) > 1 else None
    opr, opa = op >> 4, op & 15
    pair = opa & 14
    s["pc"] = (s["pc"] + len(t["fed"])) & 0xFFF

    def add(v, c):
        total = s["acc"] + v + c
        s["acc"], s["cy"] = total & 15, total >> 4

    if op == 0x00:
        pass
    elif opr == 0x1:
        cond = (opa & 4 and s["acc"] == 0) or (opa & 2 and s["cy"]) or (opa & 1 and not i["test"])
        if bool(cond) != bool(opa & 8):
            s["pc"] = (s["pc"] & 0xF00) | arg
    elif opr == 0x2 and not opa & 1:
        s["r"][pair], s["r"][pair + 1] = arg >> 4, arg & 15
    elif opr == 0x2:
        pass                                    # SRC: bus activity only
    elif opr == 0x3 and not opa & 1:
        s["pc"] = (i["pc"] + 1) & 0xFFF         # FIN: one byte, two cycles
        s["r"][pair], s["r"][pair + 1] = arg >> 4, arg & 15
    elif opr == 0x3:
        s["pc"] = (s["pc"] & 0xF00) | (s["r"][pair] << 4) | s["r"][pair + 1]
    elif opr == 0x4:
        s["pc"] = (opa << 8) | arg
    elif opr == 0x5:
        s["stack"] = [s["pc"]] + s["stack"][:2]
        s["pc"] = (opa << 8) | arg
    elif opr == 0x6:
        s["r"][opa] = (s["r"][opa] + 1) & 15
    elif opr == 0x7:
        s["r"][opa] = (s["r"][opa] + 1) & 15
        if s["r"][opa]:
            s["pc"] = (s["pc"] & 0xF00) | arg
    elif opr == 0x8:
        add(s["r"][opa], s["cy"])
    elif opr == 0x9:
        add(s["r"][opa] ^ 15, 1 - s["cy"])
    elif opr == 0xA:
        s["acc"] = s["r"][opa]
    elif opr == 0xB:
        s["acc"], s["r"][opa] = s["r"][opa], s["acc"]
    elif opr == 0xC:
        # the 4th stack slot (the old PC) is not visible in the test, so the bottom is unknown
        s["pc"], s["stack"], s["acc"] = s["stack"][0], s["stack"][1:] + [None], opa
    elif opr == 0xD:
        s["acc"] = opa
    elif opr == 0xE:
        v = t["io_in"]
        if opa == 0x8:
            add(v ^ 15, 1 - s["cy"])
        elif opa == 0xB:
            add(v, s["cy"])
        elif opa >= 8:
            s["acc"] = v
    elif op == 0xF0:
        s["acc"] = s["cy"] = 0
    elif op == 0xF1:
        s["cy"] = 0
    elif op == 0xF2:
        add(1, 0)
    elif op == 0xF3:
        s["cy"] ^= 1
    elif op == 0xF4:
        s["acc"] ^= 15
    elif op == 0xF5:
        v = (s["acc"] << 1) | s["cy"]
        s["acc"], s["cy"] = v & 15, v >> 4
    elif op == 0xF6:
        s["acc"], s["cy"] = (s["acc"] >> 1) | (s["cy"] << 3), s["acc"] & 1
    elif op == 0xF7:
        s["acc"], s["cy"] = s["cy"], 0
    elif op == 0xF8:
        add(15, 0)
    elif op == 0xF9:
        s["acc"], s["cy"] = 9 + s["cy"], 0
    elif op == 0xFA:
        s["cy"] = 1
    elif op == 0xFB:
        if s["cy"] or s["acc"] > 9:
            total = s["acc"] + 6
            s["acc"] = total & 15
            if total > 15:
                s["cy"] = 1
    elif op == 0xFC:
        s["acc"] = KBP[s["acc"]]
    elif op == 0xFD:
        s["cm_ram"] = DCL_LINES[s["acc"] & 7]
    else:
        return None
    return s


def same(model, final):
    return all(model[k] == final[k] for k in ("pc", "acc", "cy", "r", "cm_ram")) and \
        all(m is None or m == f for m, f in zip(model["stack"], final["stack"]))


def bus_candidates(t, c, n):
    """Named values that might be what the CPU drives; n = which cycle (0 or 1)."""
    i, f = t["initial"], t["final"]
    op = t["opcode"]
    opa = op & 15
    out = {"OPA": opa, "OPR": op >> 4, "acc before": i["acc"], "acc after": f["acc"],
           "R[opa] before": i["r"][opa], "R[opa] after": f["r"][opa],
           "R[pair] high": i["r"][opa & 14], "R[pair] low": i["r"][opa | 1],
           "R[pair] high after": f["r"][opa & 14], "R[pair] low after": f["r"][opa | 1],
           "R0": i["r"][0], "R1": i["r"][1], "carry before (0/1)": i["cy"],
           "~acc before": i["acc"] ^ 15, "~R[opa] before": i["r"][opa] ^ 15,
           "bus at M2 (ROM low nibble)": c["bus"][M2], "bus at M1 (ROM high nibble)": c["bus"][M1]}
    if t["io_in"] is not None:
        out["I/O data read"] = t["io_in"]
    if len(t["fed"]) > 1:
        out["2nd byte high"] = t["fed"][1] >> 4
        out["2nd byte low"] = t["fed"][1] & 15
    for k in range(16):
        out[f"constant {k:X}"] = k
    return out


GROUPS = [("NOP", [0x00]), ("JCN", range(0x10, 0x20)), ("FIM", range(0x20, 0x30, 2)),
          ("SRC", range(0x21, 0x30, 2)), ("FIN", range(0x30, 0x40, 2)), ("JIN", range(0x31, 0x40, 2)),
          ("JUN", range(0x40, 0x50)), ("JMS", range(0x50, 0x60)), ("INC", range(0x60, 0x70)),
          ("ISZ", range(0x70, 0x80)), ("ADD", range(0x80, 0x90)), ("SUB", range(0x90, 0xA0)),
          ("LD", range(0xA0, 0xB0)), ("XCH", range(0xB0, 0xC0)), ("BBL", range(0xC0, 0xD0)),
          ("LDM", range(0xD0, 0xE0)), ("I/O write (WRM WMP WRR WPM WR0-3)", range(0xE0, 0xE8)),
          ("I/O read (SBM RDM RDR ADM RD0-3)", range(0xE8, 0xF0)), ("accumulator group", range(0xF0, 0xFE))]


def main(folder):
    tests = {}
    for path in sorted(glob.glob(folder + "/*.json.gz")):
        data = json.load(gzip.open(path, "rt"))
        tests[data[0]["opcode"]] = data
    total = sum(len(v) for v in tests.values())
    print(f"{total} vectors, {len(tests)} opcodes\n")

    print("== 1. Documented instructions against the manual ==")
    undefined, bad = [], 0
    for op, data in tests.items():
        if manual(op, data[0]) is None:
            undefined.append(op)
            continue
        fails = [t for t in data if not same(manual(op, t), t["final"])]
        bad += len(fails)
        if fails:
            t = fails[0]
            print(f"  {op:02X}: {len(fails)}/{len(data)} differ. e.g. {t['name']}: initial {t['initial']} fed {t['fed']} "
                  f"final {t['final']} expected {manual(op, t)}")
    print(f"  {len(tests) - len(undefined)} documented opcodes, {total - 400 * len(undefined)} vectors: {bad} differ from the manual\n")

    print("== 2. Opcodes the manual leaves undefined ==")
    for op in undefined:
        data = tests[op]
        matches = []
        for other in tests:
            if other in undefined or len(tests[other][0]["fed"]) != len(data[0]["fed"]):
                continue
            if (other >> 4) == 0xE and (other & 15) >= 8:
                continue      # needs I/O data we did not supply
            if all(same(manual(other, dict(t, opcode=other)), t["final"]) for t in data):
                matches.append(other)
        cm = collections.Counter(tuple(c["cm"]) for t in data for c in t["cycles"])
        cm_m2 = any(c["cm"][M2] for t in data for c in t["cycles"])
        cm_x2 = any(c["cm"][X2] for t in data for c in t["cycles"])
        names = ", ".join(f"{m:02X}" for m in matches[:6]) or "NOTHING documented"
        print(f"  {op:02X}: {len(data[0]['fed'])} cycle(s); state changes like opcode(s) {names}; "
              f"CM lines at M2: {'yes' if cm_m2 else 'no'}, at X2: {'yes' if cm_x2 else 'no'}")
    print()

    print("== 3. What the CPU drives onto the data bus in X1, X2, X3 ==")
    print("   (driven = all four lines held by the CPU's output drivers; otherwise the bus floats)")
    for name, ops in GROUPS:
        ncycles = len(tests[list(ops)[0]][0]["fed"])
        for n in range(ncycles):
            parts = []
            for slot, sname in ((X1, "X1"), (X2, "X2"), (X3, "X3")):
                rows = [(t, t["cycles"][n]) for op in ops for t in tests[op]]
                drv = collections.Counter(c["driven"][slot] for _, c in rows)
                if set(drv) == {0}:
                    parts.append(f"{sname}: floating")
                    continue
                if set(drv) != {15}:
                    parts.append(f"{sname}: driven mask varies {dict(drv)}")
                    continue
                cands = None
                for t, c in rows:
                    ok = {k for k, v in bus_candidates(t, c, n).items() if v == c["bus"][slot]}
                    cands = ok if cands is None else cands & ok
                    if not cands:
                        break
                label = " = ".join(sorted(cands, key=len)[:3]) if cands else "?? (matches no simple candidate)"
                parts.append(f"{sname}: {label}")
            cyc = f" cycle {n + 1}" if ncycles > 1 else ""
            print(f"  {name}{cyc}:  " + "  |  ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1])
