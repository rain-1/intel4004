#!/usr/bin/env python3
"""Query the extracted netlist: list every transistor touching the given nodes."""
import json, sys
n = json.load(open(sys.argv[1]))
inv = {v: k for k, v in n["pads"].items()}
nm = lambda i: inv.get(i, str(i))
for q in sys.argv[2:]:
    q = n["pads"].get(q, None) if not q.isdigit() else int(q)
    print(f"== node {nm(q)} (area {n['area'][q]})")
    for t in n["transistors"]:
        if q in (t["gate"], t["a"], t["b"]):
            role = "GATE" if t["gate"] == q else "term"
            print(f"   {role}  g={nm(t['gate']):>6} {nm(t['a']):>6} - {nm(t['b']):<6} at ({t['x']:.0f},{t['y']:.0f}) area {t['area']}")
    for c in n["capacitors"]:
        if q in (c["gate"], c["node"]):
            print(f"   CAP   g={nm(c['gate'])} node={nm(c['node'])} at ({c['x']:.0f},{c['y']:.0f}) area {c['area']}")
