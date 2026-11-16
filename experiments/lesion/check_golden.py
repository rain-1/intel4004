#!/usr/bin/env python3
"""Check that the lesion harness's intact-chip runs reproduce the first K tests of
vectors/v1 exactly (same initial state, same bus samples, same final state).

    lesion --k K --golden > g.jsonl ; check_golden.py g.jsonl vectors/v1
"""
import gzip, json, sys, os

rows = [json.loads(l) for l in open(sys.argv[1])]
cache, bad = {}, 0
for g in rows:
    op = g["op"]
    if op not in cache:
        cache[op] = json.load(gzip.open(os.path.join(sys.argv[2], f"{op:02x}.json.gz"), "rt"))
    v = cache[op][g["n"]]
    vbus = [b for c in v["cycles"] for b in c["bus"]]
    vf = v["final"]
    ok = (v["initial"]["pc"] == g["pc"] and v["initial"]["acc"] == g["acc"] and vbus == g["bus"]
          and all(vf[k] == g["final"][k] for k in ("pc", "acc", "cy", "r", "cm_ram"))
          and vf["stack"] == g["final"]["stack"])
    if not ok:
        bad += 1
        if bad < 5:
            print("MISMATCH", op, g["n"], file=sys.stderr)
print(f"{len(rows)} tests compared with v1, {bad} mismatches")
sys.exit(1 if bad else 0)
