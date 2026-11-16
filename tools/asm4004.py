#!/usr/bin/env python3
"""A small Intel 4004 assembler.

    label:  FIM P0, $2A        ; comment
            JCN NZ, label      ; conditions: C NC Z NZ T NT, or a number
            DB  1, 2, "text", 0
            ORG $100
    name    =   expr

Numbers: 123, $7B, 0x7B, %1010. Registers R0..R15 (or 0..15), pairs P0..P7.
lo(x) / hi(x) give the low / high byte of an address.
"""
import re
import sys

NO_ARG = {"NOP": 0x00, "WRM": 0xE0, "WMP": 0xE1, "WRR": 0xE2, "WPM": 0xE3, "WR0": 0xE4,
          "WR1": 0xE5, "WR2": 0xE6, "WR3": 0xE7, "SBM": 0xE8, "RDM": 0xE9, "RDR": 0xEA,
          "ADM": 0xEB, "RD0": 0xEC, "RD1": 0xED, "RD2": 0xEE, "RD3": 0xEF, "CLB": 0xF0,
          "CLC": 0xF1, "IAC": 0xF2, "CMC": 0xF3, "CMA": 0xF4, "RAL": 0xF5, "RAR": 0xF6,
          "TCC": 0xF7, "DAC": 0xF8, "TCS": 0xF9, "STC": 0xFA, "DAA": 0xFB, "KBP": 0xFC,
          "DCL": 0xFD}
REG = {"INC": 0x60, "ADD": 0x80, "SUB": 0x90, "LD": 0xA0, "XCH": 0xB0}
IMM = {"BBL": 0xC0, "LDM": 0xD0}
PAIR = {"SRC": 0x21, "FIN": 0x30, "JIN": 0x31}
ADDR12 = {"JUN": 0x40, "JMS": 0x50}
COND = {"NT": 0x9, "T": 0x1, "C": 0x2, "NC": 0xA, "Z": 0x4, "NZ": 0xC}
SIZE2 = {"JCN", "FIM", "JUN", "JMS", "ISZ"}


class AsmError(Exception):
    pass


def split_args(text):
    """Split on commas that are not inside a string literal."""
    args, cur, quote = [], "", None
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def strip_comment(line):
    out, quote = "", None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ";":
            break
        out += ch
    return out.rstrip()


def assemble(source):
    symbols = {f"R{i}": i for i in range(16)}
    symbols.update({f"P{i}": i for i in range(8)})

    def value(expr):
        e = re.sub(r"\$([0-9A-Fa-f]+)", r"0x\1", expr)
        e = re.sub(r"%([01]+)", r"0b\1", e)
        env = dict(symbols, lo=lambda x: x & 0xFF, hi=lambda x: (x >> 8) & 0xFF)
        try:
            return int(eval(e, {"__builtins__": {}}, env))
        except NameError as err:
            raise AsmError(f"undefined symbol in '{expr}': {err}")
        except Exception as err:
            raise AsmError(f"bad expression '{expr}': {err}")

    def data_bytes(args, final):
        out = []
        for a in args:
            if a[:1] in "\"'":
                out += list(a[1:-1].encode("latin-1"))
            else:
                out.append(value(a) & 0xFF if final else 0)
        return out

    lines = []
    for num, raw in enumerate(source.splitlines(), 1):
        text = strip_comment(raw).strip()
        label = None
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", text)
        if m:
            lines.append((num, raw, None, "=", [m.group(1), m.group(2)]))
            continue
        m = re.match(r"^([A-Za-z_]\w*):\s*(.*)$", text)
        if m:
            label, text = m.group(1), m.group(2)
        op, _, rest = text.partition(" ")
        lines.append((num, raw, label, op.upper(), split_args(rest)))

    image, listing = {}, []
    for final in (False, True):
        pc = 0
        for num, raw, label, op, args in lines:
            try:
                if label and not final:
                    if label in symbols:
                        raise AsmError(f"duplicate label {label}")
                    symbols[label] = pc
                start, code = pc, []
                if op == "=":
                    if not final:
                        symbols[args[0]] = value(args[1])
                elif op == "ORG":
                    pc = start = value(args[0])
                elif op == "DB":
                    code = data_bytes(args, final)
                elif op == "":
                    pass
                elif op in NO_ARG:
                    code = [NO_ARG[op]]
                elif not final:
                    code = [0, 0] if op in SIZE2 else [0]
                    if op not in SIZE2 | set(REG) | set(IMM) | set(PAIR):
                        raise AsmError(f"unknown instruction {op}")
                elif op in REG:
                    code = [REG[op] | (value(args[0]) & 15)]
                elif op in IMM:
                    code = [IMM[op] | (value(args[0]) & 15)]
                elif op in PAIR:
                    code = [PAIR[op] | ((value(args[0]) & 7) << 1)]
                elif op == "FIM":
                    code = [0x20 | ((value(args[0]) & 7) << 1), value(args[1]) & 0xFF]
                elif op in ADDR12:
                    a = value(args[0])
                    code = [ADDR12[op] | ((a >> 8) & 15), a & 0xFF]
                elif op in ("JCN", "ISZ"):
                    first = COND[args[0].upper()] if op == "JCN" and args[0].upper() in COND else value(args[0]) & 15
                    target = value(args[1])
                    if (target >> 8) != ((pc + 2) >> 8):
                        raise AsmError(f"{op} target ${target:03X} is not in the page of ${pc + 2:03X}")
                    code = [(0x10 if op == "JCN" else 0x70) | first, target & 0xFF]
                pc += len(code)
                if final:
                    for i, b in enumerate(code):
                        if start + i in image:
                            raise AsmError(f"address ${start + i:03X} assembled twice")
                        image[start + i] = b
                    hexs = " ".join(f"{b:02X}" for b in code[:4])
                    listing.append(f"{start:03X}  {hexs:<11}  {raw.rstrip()}")
            except AsmError as err:
                raise SystemExit(f"line {num}: {err}\n    {raw.strip()}")
            except IndexError:
                raise SystemExit(f"line {num}: missing operand\n    {raw.strip()}")
    size = max(image) + 1 if image else 0
    rom = bytes(image.get(i, 0) for i in range(size))
    return rom, "\n".join(listing), symbols


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: asm4004.py program.asm program.bin [program.lst]")
    rom, listing, _ = assemble(open(sys.argv[1]).read())
    open(sys.argv[2], "wb").write(rom)
    if len(sys.argv) > 3:
        open(sys.argv[3], "w").write(listing + "\n")
    print(f"{sys.argv[2]}: {len(rom)} bytes", file=sys.stderr)
