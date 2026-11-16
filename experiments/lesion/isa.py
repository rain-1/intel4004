"""4004 instruction set helpers shared by the lesion-study scripts."""

IO = ["WRM", "WMP", "WRR", "WPM", "WR0", "WR1", "WR2", "WR3", "SBM", "RDM", "RDR", "ADM", "RD0", "RD1", "RD2", "RD3"]
ACC = ["CLB", "CLC", "IAC", "CMC", "CMA", "RAL", "RAR", "TCC", "DAC", "TCS", "STC", "DAA", "KBP", "DCL"]


def mnemonic(op):
    """Instruction name of an opcode (operand-free): 46 documented names + 'undef'."""
    h, l = op >> 4, op & 15
    if h == 0:
        return "NOP" if l == 0 else "undef"
    if h == 2:
        return "SRC" if l & 1 else "FIM"
    if h == 3:
        return "JIN" if l & 1 else "FIN"
    if h == 0xE:
        return IO[l]
    if h == 0xF:
        return ACC[l] if l < 14 else "undef"
    return [None, "JCN", None, None, "JUN", "JMS", "INC", "ISZ", "ADD", "SUB", "LD", "XCH", "BBL", "LDM"][h]


# instruction names in a fixed display order
NAMES = ["NOP", "undef", "JCN", "FIM", "SRC", "FIN", "JIN", "JUN", "JMS", "INC", "ISZ", "ADD", "SUB", "LD", "XCH",
         "BBL", "LDM"] + IO + ACC
OPS_OF = {n: [o for o in range(256) if mnemonic(o) == n] for n in NAMES}

# coarse groups (as in the pilot's analyze.py)
GROUPS = [("NOP/undef", lambda o: o < 0x10 or o >= 0xFE), ("JCN", lambda o: o >> 4 == 1),
          ("FIM", lambda o: o >> 4 == 2 and not o & 1), ("SRC", lambda o: o >> 4 == 2 and o & 1),
          ("FIN", lambda o: o >> 4 == 3 and not o & 1), ("JIN", lambda o: o >> 4 == 3 and o & 1),
          ("JUN", lambda o: o >> 4 == 4), ("JMS", lambda o: o >> 4 == 5), ("INC", lambda o: o >> 4 == 6),
          ("ISZ", lambda o: o >> 4 == 7), ("ADD", lambda o: o >> 4 == 8), ("SUB", lambda o: o >> 4 == 9),
          ("LD", lambda o: o >> 4 == 0xA), ("XCH", lambda o: o >> 4 == 0xB), ("BBL", lambda o: o >> 4 == 0xC),
          ("LDM", lambda o: o >> 4 == 0xD), ("IO-write", lambda o: o >> 4 == 0xE and o & 15 < 8),
          ("IO-read", lambda o: o >> 4 == 0xE and o & 15 >= 8),
          ("ACC-group", lambda o: 0xF0 <= o <= 0xFD)]
GROUP_OPS = {g: [o for o in range(256) if p(o)] for g, p in GROUPS}

# failure kinds (bit masks, as in study.c)
KIND_BITS = ["ACC", "CY", "REG", "PC", "STACK", "CMRAM", "ADDR", "MBUS", "X1", "XDOC", "XUND", "DRV", "CM", "SYNC",
             "NOSYNC", "UNST"]
K = {n: 1 << i for i, n in enumerate(KIND_BITS)}
K_STATE_DATA = K["ACC"] | K["CY"] | K["REG"]
K_STATE_FLOW = K["PC"] | K["STACK"]
K_BUS = K["ADDR"] | K["MBUS"] | K["X1"] | K["XDOC"] | K["DRV"]

# the decode signals named on Kintli's schematic (source/analyzer/i4004-signals.txt), as opcode sets
def _ops(*names):
    return frozenset(o for n in names for o in OPS_OF[n])


SCHEMATIC_DECODES = {
    "JCN": _ops("JCN"), "ISZ": _ops("ISZ"), "BBL": _ops("BBL"), "JMS": _ops("JMS"), "FIN+FIM": _ops("FIN", "FIM"),
    "FIM+SRC": _ops("FIM", "SRC"), "JCN+ISZ": _ops("JCN", "ISZ"), "JUN+JMS": _ops("JUN", "JMS"),
    "JIN+FIN": _ops("JIN", "FIN"), "FIN+FIM+SRC+JIN": _ops("FIN", "FIM", "SRC", "JIN"),
    "INC+ISZ+XCH": _ops("INC", "ISZ", "XCH"), "INC+ISZ+ADD+SUB+XCH+LD": _ops("INC", "ISZ", "ADD", "SUB", "XCH", "LD"),
    "LDM/BBL": _ops("LDM", "BBL"), "IO (E0-EF)": frozenset(range(0xE0, 0xF0)), "IOW": _ops(*IO[:8]),
    "IOR": _ops(*IO[8:]), "LD": _ops("LD"), "XCH": _ops("XCH"), "ADD": _ops("ADD"), "SUB": _ops("SUB"),
    "INC/ISZ": _ops("INC", "ISZ"), "SBM": _ops("SBM"), "ADM": _ops("ADM"),
    **{n: _ops(n) for n in ACC},
}
