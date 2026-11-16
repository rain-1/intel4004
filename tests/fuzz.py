#!/usr/bin/env python3
"""Generate a random 4004 program for cross-checking: fuzz.py SEED > prog.asm

Random instructions from the whole instruction set, with forward conditional jumps,
ISZ, FIN and nested subroutine calls. Everything observable ends up on the bus
(SRC / I/O), and the program finishes by dumping all registers.
"""
import random
import sys

rng = random.Random(int(sys.argv[1]))
ONE_BYTE = (["NOP"] + [f"{op} R{r}" for op in ("INC", "ADD", "SUB", "LD", "XCH") for r in range(16)]
            + [f"LDM {d}" for d in range(16)] + [f"SRC P{p}" for p in range(8)]
            + ["WRM", "WMP", "WRR", "WPM", "WR0", "WR1", "WR2", "WR3", "SBM", "RDM", "RDR",
               "ADM", "RD0", "RD1", "RD2", "RD3"] * 3
            + ["CLB", "CLC", "IAC", "CMC", "CMA", "RAL", "RAR", "TCC", "DAC", "TCS", "STC",
               "DAA", "KBP", "DCL"] * 4)


def body(n, depth, subs):
    """n random items: (size, text) pairs. Jumps go forward to a label a few items on."""
    items = []
    for i in range(n):
        k = rng.random()
        if k < 0.70:
            items.append([1, rng.choice(ONE_BYTE), None])
        elif k < 0.78:
            items.append([2, f"FIM P{rng.randrange(8)}, ${rng.randrange(256):02X}", None])
        elif k < 0.81:
            items.append([1, f"FIN P{rng.randrange(8)}", None])
        elif k < 0.88:
            items.append([2, f"JCN {rng.randrange(16)}, ", rng.randint(1, 4)])
        elif k < 0.92:
            items.append([2, f"ISZ R{rng.randrange(16)}, ", rng.randint(1, 4)])
        elif k < 0.94:
            items.append([2, "JUN ", rng.randint(1, 3)])
        elif depth < 3 and subs:
            items.append([2, f"JMS {rng.choice(subs)}", None])
        else:
            items.append([1, "NOP", None])
    return items


def emit(name, items, org, tail):
    """Lay the items out at `org`; page-crossing short jumps are replaced by NOPs."""
    addr, pc = [], org
    for size, _, _ in items:
        addr.append(pc)
        pc += size
    end = pc
    out = [f"        ORG ${org:03X}", f"{name}:"]
    for i, (size, text, skip) in enumerate(items):
        label = f"{name}_{i}:"
        if skip is None:
            out.append(f"{label:<10} {text}")
            continue
        j = min(i + 1 + skip, len(items))
        target = addr[j] if j < len(items) else end
        if not text.startswith("JUN") and (target >> 8) != ((addr[i] + 2) >> 8):
            out.append(f"{label:<10} NOP")
            out.append("           NOP")
        else:
            out.append(f"{label:<10} {text}${target:03X}")
    out += [f"           {t}" for t in tail]
    return out, end + sum(2 if t.split()[0] in ("JUN", "JMS") else 1 for t in tail)


lines = ["; random cross-check program, seed " + sys.argv[1]]
# subroutines: level 3 calls nothing, level 2 calls level 3, level 1 calls level 2
subs = {3: ["s3a", "s3b"], 2: ["s2a", "s2b"], 1: ["s1a", "s1b"]}
org = 0x400
for level in (3, 2, 1):
    for name in subs[level]:
        callees = subs.get(level + 1, [])
        text, org = emit(name, body(rng.randint(5, 30), level, callees), org, [f"BBL {rng.randrange(16)}"])
        lines += text
        org += rng.randint(0, 40)
dump = []
for r in range(16):
    dump += [f"LD R{r}", "WRR"]
main, _ = emit("main", body(rng.randint(150, 400), 0, subs[1]), 0x001,
               ["TCC", "WRR"] + dump + ["JUN halt"])
lines += ["        ORG $000", "        NOP"] + main[1:]
lines += ["        ORG $3F0", "halt:   JUN halt"]
print("\n".join(lines))
