#!/usr/bin/env python3
"""Follow up the unexplained no-effect lesions.

    followup.py [JOBS]       (run from the repository root, after analyze_study.py)

For every lesion in experiments/lesion/results/unexplained.txt:
  1. --peek: run the structured test set in lockstep with an intact twin and count, per node,
     the samples (phi2 high, every clock period) where the lesioned chip's internal node
     differs from the intact chip's.
  2. --fuzz 300 --minimise: 300 random 24-instruction programs from random states (random TEST
     level per cycle, random I/O input nibbles); every pin sample and the final state are
     compared; the first catching program is shrunk to a minimal test.
Verdict:
  test gap        a random program shows a pin difference (a test exists; minimal one printed)
  masked          internal nodes differ during the structured tests, but no pin difference found
  silent          no internal node ever differs from the intact chip in the structured tests
                  (and no random program catches it): invisible to this model with these tests
Writes experiments/lesion/results/followup.tsv and followup_raw.txt.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

D = "experiments/lesion"
R = os.path.join(D, "results")
jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
lesions = [l.strip() for l in open(os.path.join(R, "unexplained.txt")) if l.strip()]
chunks = [lesions[i::jobs] for i in range(jobs)]


def run(args):
    return subprocess.run([os.path.join(D, "study"), "--net", "netlist/4004.net"] + args, capture_output=True,
                          text=True).stdout


with ThreadPoolExecutor(jobs) as ex:
    peek = "".join(ex.map(lambda c: run(["--peek"] + c) if c else "", chunks))
    fuzz = "".join(ex.map(lambda c: run(["--fuzz", "300", "--minimise"] + c) if c else "", chunks))
open(os.path.join(R, "followup_raw.txt"), "w").write(peek + fuzz)

res = {}
for line in peek.splitlines():
    f = line.split()
    key = f[0] + f[1]
    kv = dict(x.split("=") for x in f[2:6])
    nodes = sorted(((int(a), int(b)) for a, b in (x.split(":") for x in f[6:])), key=lambda x: -x[1])
    res[key] = dict(t=f[0], mode=f[1], peek_nfail=kv["nfail"], peek_nodes=kv["nodes_differing"],
                    peek_top=",".join(f"{n}:{c}" for n, c in nodes[:8]), fuzz_caught="", fuzz_first="", minimal="")
last = None
for line in fuzz.splitlines():
    if line.startswith("   minimal test:"):
        res[last]["minimal"] = line.split("minimal test:", 1)[1].strip()
        continue
    f = line.split()
    last = f[0] + f[1]
    kv = dict(x.split("=") for x in f[2:])
    res[last]["fuzz_caught"] = kv["caught"]
    res[last]["fuzz_first"] = kv["first"]
for d in res.values():
    if int(d["fuzz_caught"] or 0) > 0:
        d["verdict"] = "test gap"
    elif int(d["peek_nodes"]) > 0:
        d["verdict"] = "masked"
    else:
        d["verdict"] = "silent"
cols = ["t", "mode", "verdict", "peek_nfail", "peek_nodes", "peek_top", "fuzz_caught", "fuzz_first", "minimal"]
with open(os.path.join(R, "followup.tsv"), "w") as f:
    f.write("\t".join(cols) + "\n")
    for k in lesions:
        if k in res:
            f.write("\t".join(str(res[k][c]) for c in cols) + "\n")
from collections import Counter
print(Counter(d["verdict"] for d in res.values()))
