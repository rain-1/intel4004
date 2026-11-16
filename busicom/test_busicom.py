#!/usr/bin/env python3
"""Regression test for the Busicom 141-PF firmware on the transistor-level 4004.

For every case below:
  (a) the transistor-level run and the reference-emulator run must produce byte-identical
      bus-activity logs (every fetch, SRC and I/O transfer) and identical paper tapes;
  (b) the tape must equal the expected tape written out below, and the result line is
      also checked numerically against the arithmetic (Python Decimal) under the stated
      rule; quirks documented in the listing (chapter 4.6) are checked against the
      listing's own text instead;
  (c) the final lamp state must match.
Also, on the reference emulator only (cheap), every case must print the same tape with
the drum modelled the other way round (--drum pilot) and with a 10 ms sector pulse.

    python3 busicom/test_busicom.py [-j JOBS] [--keep] [--ref-only] [name ...]

Run from the repository root (make test-busicom). Logs go to build/busicom/ and are
deleted when they match, unless --keep.
"""
import argparse, filecmp, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, getcontext

getcontext().prec = 50
TOOL = "./i4004-busicom"
OUT = "build/busicom"


def L(digits, c17="", c18="", red=False):
    """One printed line: 15 digit columns, then columns 17 and 18."""
    return f"|{digits:>15}  {c17:<2} {c18:<3}|" + (" red" if red else "")


BLANK = L("")
DOTS = L("." * 15)

# (name, keys, expected tape, lamps (memory, overflow, minus), check)
# check = (expression, rule) for the last non-blank line, or None.
#   rule: "exact" | ("trunc", decimals) | ("round", decimals) | ("sig", digits) [truncated]
#         | ("listing", text) [value printed in the listing] | "overflow"
CASES = [
    # --- adding-machine logic: number, then + or -; "=" prints and clears the total
    ("add", "18 + 42 + =", [L("18", "+"), L("42", "+"), L("60", "", "*"), BLANK], (0, 0, 0), ("18+42", "exact")),
    ("subtract", "100 + 25 - =", [L("100", "+"), L("25", "-"), L("75", "", "*"), BLANK], (0, 0, 0), ("100-25", "exact")),
    ("negative", "25 + 100 - =", [L("25", "+"), L("100", "-"), L("75", "", "*", True), BLANK], (0, 0, 1), ("25-100", "exact")),
    ("sign-key", "12 + 5 S + =", [L("12", "+"), L("5", "+", red=True), L("7", "", "*"), BLANK], (0, 0, 0), ("12-5", "exact")),
    ("subtotal", "5 + 3 + <> 2 + =", [L("5", "+"), L("3", "+"), L("8", "<>"), L("2", "+"), L("10", "", "*"), BLANK],
     (0, 0, 0), ("5+3+2", "exact")),
    ("clear-entry", "5 + 3 CE 4 + =", [L("5", "+"), L("4", "+"), L("9", "", "*"), BLANK], (0, 0, 0), ("5+4", "exact")),
    ("zero-keys", "1 000 + 2 00 + =", [L("1000", "+"), L("200", "+"), L("1200", "", "*"), BLANK], (0, 0, 0), ("1000+200", "exact")),
    ("14-digits", "12345678901234 + 1 + =", [L("12345678901234", "+"), L("1", "+"), L("12345678901235", "", "*"), BLANK],
     (0, 0, 0), ("12345678901234+1", "exact")),
    ("paper-feed", "7 FEED 7 +", [BLANK, L("77", "+")], (0, 0, 0), ("77", "exact")),
    # --- multiply / divide
    ("multiply", "12 * 34 =", [L("12", "X"), L("34", "="), L("408", "", "*"), BLANK], (0, 0, 0), ("12*34", "exact")),
    ("multiply-big", "123456 * 789 =", [L("123456", "X"), L("789", "="), L("97406784", "", "*"), BLANK], (0, 0, 0),
     ("123456*789", "exact")),
    ("multiply-13digit", "1234567 * 7654321 =", [L("1234567", "X"), L("7654321", "="), L("9449772114007", "", "*"), BLANK],
     (0, 0, 0), ("1234567*7654321", "exact")),
    ("multiply-negative", "8 * 25 S =", [L("8", "X"), L("25", "=", red=True), L("200", "", "*", True), BLANK], (0, 0, 1),
     ("8*-25", "exact")),
    ("multiply-decimal", "1.5 * 1.5 =", [L("1.5", "X"), L("1.5", "="), L("2.25", "", "*"), BLANK], (0, 0, 0), ("1.5*1.5", "exact")),
    ("chain", "2 * 3 * 4 =", [L("2", "X"), L("3", "X"), L("4", "="), L("24", "", "*"), BLANK], (0, 0, 0), ("2*3*4", "exact")),
    # listing 4.4: after "24 * 3 =" the constant register keeps 24
    ("constant", "24 * 3 = 5 =", [L("24", "X"), L("3", "="), L("72", "", "*"), BLANK, L("5", "="), L("120", "", "*"), BLANK],
     (0, 0, 0), ("24*5", "exact")),
    ("divide", "7 / 2 =", [L("7", "/"), L("2", "="), L("3.5000000000000", "", "*"), BLANK], (0, 0, 0), ("7/2", "exact")),
    # floating point: a 14-digit quotient whose first digit is 0 when the dividend's leading
    # digits are smaller than the divisor's -> 13 significant digits, truncated
    ("divide-1by3", "1 / 3 =", [L("1", "/"), L("3", "="), L("0.3333333333333", "", "*"), BLANK], (0, 0, 0), ("1/3", ("sig", 13))),
    ("divide-10by3", "10 / 3 =", [L("10", "/"), L("3", "="), L("3.333333333333", "", "*"), BLANK], (0, 0, 0), ("10/3", ("sig", 13))),
    ("divide-100by3", "100 / 3 =", [L("100", "/"), L("3", "="), L("33.33333333333", "", "*"), BLANK], (0, 0, 0),
     ("100/3", ("sig", 13))),
    ("percent", "200 * 15 %", [L("200", "X"), L("15", "%"), L("30.00", "", "*"), BLANK], (0, 0, 0), ("200*15/100", "exact")),
    # --- decimal-point selector and rounding switch
    ("dp2-add", "DP2 1.5 + 2.256 + =", [L("1.50", "+"), L("2.25", "+"), L("3.75", "", "*"), BLANK], (0, 0, 0),
     ("1.50+2.25", "exact")),  # entries are cut to the selected decimals before adding
    ("dp2-negative", "DP2 1.25 S + 3.5 + =", [L("1.25", "+", red=True), L("3.50", "+"), L("2.25", "", "*"), BLANK], (0, 0, 0),
     ("-1.25+3.5", "exact")),
    ("dp2-round", "DP2 ROUND 2 / 3 =", [L("2", "/"), L("3", "="), L("0.67", "^", "*"), BLANK], (0, 0, 0), ("2/3", ("round", 2))),
    ("dp2-trunc", "DP2 TRUNC 2 / 3 =", [L("2", "/"), L("3", "="), L("0.66", "", "*"), BLANK], (0, 0, 0), ("2/3", ("trunc", 2))),
    ("dp2-float", "DP2 2 / 3 =", [L("2", "/"), L("3", "="), L("0.6666666666666", "", "*"), BLANK], (0, 0, 0),
     ("2/3", ("sig", 13))),
    ("dp1-round", "DP1 ROUND 1.5 * 1.5 =", [L("1.5", "X"), L("1.5", "="), L("2.3", "^", "*"), BLANK], (0, 0, 0),
     ("1.5*1.5", ("round", 1))),
    ("dp1-trunc", "DP1 TRUNC 1.5 * 1.5 =", [L("1.5", "X"), L("1.5", "="), L("2.2", "", "*"), BLANK], (0, 0, 0),
     ("1.5*1.5", ("trunc", 1))),
    ("dp4-trunc", "DP4 TRUNC 1 / 7 =", [L("1", "/"), L("7", "="), L("0.1428", "", "*"), BLANK], (0, 0, 0), ("1/7", ("trunc", 4))),
    ("dp6-round", "DP6 ROUND 22 / 7 =", [L("22", "/"), L("7", "="), L("3.142857", "", "*"), BLANK], (0, 0, 0),
     ("22/7", ("round", 6))),
    ("dp8-round", "DP8 ROUND 2 / 3 =", [L("2", "/"), L("3", "="), L("0.66666667", "^", "*"), BLANK], (0, 0, 0),
     ("2/3", ("round", 8))),
    # --- memory
    ("memory", "5 M+ 3 M+ RM CM RM", [L("5", "M+"), L("3", "M+"), L("8", "R", "M"), L("8", "C", "M"), L("0", "R", "M")],
     (0, 0, 0), ("0", "exact")),
    ("memory-minus", "10 M+ 4 M- RM", [L("10", "M+"), L("4", "M-"), L("6", "R", "M")], (1, 0, 0), ("10-4", "exact")),
    ("memory-eq-plus", "6 * 7 M=+ RM", [L("6", "X"), L("7", "="), L("42", "", "M+"), BLANK, L("42", "R", "M")], (1, 0, 0),
     ("6*7", "exact")),
    ("memory-eq-minus", "100 M+ 6 * 7 M=- RM",
     [L("100", "M+"), L("6", "X"), L("7", "="), L("42", "", "M-"), BLANK, L("58", "R", "M")], (1, 0, 0), ("100-6*7", "exact")),
    # --- square root (optional 5th ROM)
    ("sqrt-2", "2 SQRT", [L("2", "SQ"), L("1.4142135623730", "SQ"), BLANK], (0, 0, 0), ("2", ("listing", "1.4142135623730"))),
    ("sqrt-int", "5936123 SQRT", [L("5936123", "SQ"), L("2436.4160153799", "SQ"), BLANK], (0, 0, 0), ("5936123", ("sqrt", 14))),
    ("sqrt-frac", "593.6123 SQRT", [L("593.6123", "SQ"), L("24.364160153799", "SQ"), BLANK], (0, 0, 0),
     ("593.6123", ("sqrt", 14))),
    ("sqrt-negative", "2 S SQRT", [L("2", "SQ", red=True), L("1.4142135623730", "SQ"), BLANK], (0, 0, 0),
     ("2", ("sqrt", 14))),  # listing 4.5: SQRT(X) is SQRT(ABS(X))
    # --- overflow and its recovery (only C and CE are accepted during overflow)
    ("divide-by-zero", "5 / 0 =", [L("5", "/"), L("0", "="), DOTS], (0, 1, 0), (None, "overflow")),
    ("overflow-multiply", "99999999999999 * 10 = C 1 + =",
     [L("99999999999999", "X"), L("10", "="), DOTS, L("0", "C"), L("1", "+"), L("1", "", "*"), BLANK], (0, 0, 0),
     ("1", "exact")),
    ("overflow-add", "99999999999999 + 1 + =", [L("99999999999999", "+"), L("1", "+"), DOTS], (0, 1, 0), (None, "overflow")),
    # --- listing chapter 4.6 "unusual results"
    ("quirk1-ex-divides", "10 EX 3 =", [L("10", "", "Ex"), L("3", "="), L("3.333333333333", "", "*"), BLANK], (0, 0, 0),
     ("10/3", ("sig", 13))),  # the listing's text says "3.3333333333333" (one digit more), see docs
    ("quirk2-equals", "=", [L("0", "="), DOTS], (0, 1, 0), (None, "overflow")),
    ("quirk3a", "10 / 3 = EX <>", [L("10", "/"), L("3", "="), L("3.333333333333", "", "*"), BLANK,
                                   L("3.333333333333", "", "Ex"), L("100000000000000", "", "#")], (0, 0, 0),
     (None, ("listing", "100000000000000"))),
    ("quirk3b", "10.01 / 3 = EX <>", [L("10.01", "/"), L("3", "="), L("3.336666666666", "", "*"), BLANK,
                                      L("3.336666666666", "", "Ex"), L("000000000000.00", "", "#")], (0, 0, 0),
     (None, ("listing", "000000000000.00"))),
    ("quirk3c", "10.01 / 3 = EX / 3 =", [L("10.01", "/"), L("3", "="), L("3.336666666666", "", "*"), BLANK,
                                         L("3.336666666666", "", "Ex"), L("000000000000.00", "/"), L("3", "="),
                                         L("666666666666.6", "", "*"), BLANK], (0, 0, 0), (None, ("listing", "666666666666.6"))),
    ("quirk4-sqrt-ex", "2 SQRT EX <>", [L("2", "SQ"), L("1.4142135623730", "SQ"), BLANK, L("1.4142135623730", "", "Ex"),
                                        L("28284271247460", "", "#")], (0, 0, 0), (None, ("listing", "28284271247460"))),
    ("quirk5-dp-change", "DP0 1 + DP3 2 + =", [L("1", "+"), L("2.000", "+"), L("2.001", "", "*"), BLANK], (0, 0, 0),
     (None, ("listing", "2.001"))),  # mathematically 3: the stored total is not re-aligned
]


def run(args, log=None):
    cmd = [TOOL] + args + (["--log", log] if log else [])
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p, time.time() - t


def tape_of(p):
    return [l for l in p.stdout.splitlines() if l.startswith("|")]


def lamps_of(p):
    for l in p.stderr.splitlines():
        if "lamps:" in l:
            s = l.split("lamps:")[1]
            return tuple(int(s.split(k + "=")[1][0]) for k in ("memory", "overflow", "minus"))
    return None


def cycles_of(p):
    for l in p.stderr.splitlines():
        if " cycles (" in l:
            return int(l.split(":")[1].split()[0])
    return None


def value_of(line):
    digits = line[1:16].strip()
    v = Decimal(digits)
    return -v if line.endswith(" red") else v


def evaluate(expr):
    """Arithmetic on the numbers as exact decimals (no binary floating point)."""
    return eval(re.sub(r"[0-9.]+", lambda m: f"D('{m.group(0)}')", expr), {"__builtins__": {}}, {"D": Decimal})


def check_math(tape, check):
    expr, rule = check
    lines = [l for l in tape if l != BLANK]
    last = lines[-1]
    if rule == "overflow":
        return last == DOTS, "overflow dots"
    if isinstance(rule, tuple) and rule[0] == "listing":
        return last[1:16].strip() == rule[1], f"listing says {rule[1]}"
    got = value_of(last)
    if isinstance(rule, tuple) and rule[0] == "sqrt":
        want = Decimal(expr).sqrt()
        rule = ("sig", rule[1])
    else:
        want = evaluate(expr)
    if rule == "exact":
        return got == want, f"{want}"
    kind, n = rule
    if kind == "trunc":
        w = want.quantize(Decimal(1).scaleb(-n), rounding=ROUND_DOWN)
    elif kind == "round":
        w = want.quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
    else:  # n significant digits, truncated
        w = want.quantize(Decimal(1).scaleb(want.adjusted() - n + 1), rounding=ROUND_DOWN)
    return got == w, f"{w} ({kind} {n} of {want:.20})"


def one_case(case, ref_only, keep):
    name, keys, want_tape, want_lamps, check = case
    k = keys.split()
    problems, info = [], {}
    ref, _ = run(["--ref"] + k, None if ref_only else f"{OUT}/{name}.ref.log")
    tape = tape_of(ref)
    info["cycles"] = cycles_of(ref)
    if ref.returncode != 0:
        problems.append(f"reference run failed ({ref.returncode}): {ref.stderr.strip()}")
    if tape != want_tape:
        problems.append("tape differs from expected:\n    got  " + "\n         ".join(tape) +
                        "\n    want " + "\n         ".join(want_tape))
    if lamps_of(ref) != want_lamps:
        problems.append(f"lamps {lamps_of(ref)} != expected {want_lamps}")
    ok, what = check_math(tape or [BLANK], check) if tape else (False, "no tape")
    info["math"] = what
    if not ok:
        problems.append(f"result line does not match the arithmetic: expected {what}")
    for variant in (["--drum", "pilot"], ["--pulse-ms", "10"]):
        v, _ = run(["--ref"] + variant + k)
        if tape_of(v) != tape:
            problems.append(f"tape differs with {' '.join(variant)}")
    if not ref_only:
        sim, secs = run(k, f"{OUT}/{name}.sim.log")
        info["secs"] = secs
        if sim.returncode != 0 or "UNSTABLE" in sim.stderr:
            problems.append(f"transistor-level run failed: {sim.stderr.strip()}")
        if tape_of(sim) != tape:
            problems.append("transistor-level tape differs from reference")
        a, b = f"{OUT}/{name}.ref.log", f"{OUT}/{name}.sim.log"
        same = filecmp.cmp(a, b, shallow=False)
        with open(b) as f:
            info["lines"] = sum(1 for _ in f)
        if not same:
            problems.append(f"bus logs differ: diff {a} {b}")
        elif not keep:
            os.remove(a); os.remove(b)
    return name, keys, problems, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--ref-only", action="store_true")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    cases = [c for c in CASES if not a.names or c[0] in a.names]
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    fails = 0
    with ThreadPoolExecutor(a.j) as ex:
        for name, keys, problems, info in ex.map(lambda c: one_case(c, a.ref_only, a.keep), cases):
            if problems:
                fails += 1
                print(f"FAIL {name:18} {keys}")
                for p in problems:
                    print("     " + p)
            else:
                extra = "" if a.ref_only else f", {info['lines']} log lines identical, {info['secs']:.0f} s"
                print(f"ok   {name:18} {keys:32} {info['cycles']:>7} cycles{extra}; result = {info['math']}")
            sys.stdout.flush()
    print(f"{len(cases) - fails}/{len(cases)} busicom cases passed in {time.time() - t0:.0f} s"
          + (" (reference only)" if a.ref_only else ""))
    sys.exit(1 if fails else 0)


main()
