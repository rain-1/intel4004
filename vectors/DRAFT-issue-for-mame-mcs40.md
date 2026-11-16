# Draft: issue for mamedev/mame (mcs40 core)

Not sent. Line numbers are from a copy of `mcs40.cpp` fetched in November 2026;
check them against master before posting. The vectors need hosting somewhere
public first (6.4 MB).

---

**Title: mcs40: netlist-derived answers to the 4004 FIXMEs (X1/X2/X3 bus contents, TEST sampling, reset)**

`src/devices/cpu/mcs40/mcs40.cpp` has several FIXME/TODO comments asking what a
real 4004 does. I have candidate answers from a transistor-level simulation and
would like to offer them, with the caveat up front: **they come from a netlist,
not from measurements on a chip.**

**Source.** A switch-level simulation of a 4004 netlist extracted from the
mask-layer tracings published at 4004.com (1100 nodes, 2242 transistors). The
simulated chip passes exhaustive ADD/SUB, all accumulator operations, RAM and
port access across banks, control flow including page-boundary cases, and
random-program fuzzing, all with identical bus activity to an instruction-level
reference. From it I generated 102,400 single-instruction test vectors (400 per
opcode, SingleStepTests style, state set and read only through the pins).
All 95,600 vectors for the 239 documented opcodes agree with the MCS-4 manual.

**Answers to the comments**

1. *"is 4004 output on the second cycle of two-cycle instruction OPA or low
   nybble of the argument?"* (X1) The low nibble of the second byte. In every
   cycle X1 repeats what was on the bus at M2.

2. *"what appears on the bus if it isn't SRC, I/O or program memory access?"*
   (X2) and *"what appears on the bus if it isn't SRC?"* (X3) The core currently
   outputs the last SRC address. In the netlist there is no such latch on the
   bus; X2/X3 show the internal bus:

   | instruction | X2 | X3 |
   |---|---|---|
   | NOP, JCN, undefined, second cycle of FIM/FIN/ISZ | F | F |
   | SRC, JIN | pair high | pair low |
   | FIM (first cycle) | pair high (old) | pair low (old) |
   | FIN (first cycle) | R0 | R1 |
   | JUN, JMS (both cycles), BBL, LDM | OPA | F |
   | INC, ISZ (first cycle) | register before | register after |
   | ADD, SUB, LD | register | F |
   | XCH | register before | accumulator before |
   | I/O writes | accumulator | E + carry |
   | I/O reads | (memory drives) | the nibble just read |
   | CLB CLC IAC CMC CMA RAL RAR TCC | 0 | F |
   | DAC, STC, DCL | F | F |
   | TCS | 9 | F |
   | DAA | 6 if it corrects, else 0 | F |
   | KBP | accumulator after | F |

3. *"on which cycle is TEST sampled?"* (JCN) At the end of the first cycle: the
   level present when phi2 falls in X3 of the opcode cycle decides the jump, and
   later changes are ignored. The core samples in the second cycle.

4. *"it actually takes multiple cycles with reset asserted for everything to get
   cleared"* PC, accumulator and carry clear within two clock periods. The stack
   clears one level per instruction cycle and the index registers one pair per
   instruction cycle, so a fully loaded chip needs 58 clock periods in the
   simulation (the data sheet asks for 64).

5. Undefined opcodes `01`-`0F`, `FE`, `FF` are one-cycle NOPs with no CM
   activity, which matches what the core already does in effect.

**Limits**

- None of the bus-content, TEST or reset findings has been compared with a real
  4004. I could find no published hardware capture that covers them. (Frank
  Buss's 2012 captures show the CPU driving the bus in X1, which is consistent,
  but nothing about X2/X3 contents.)
- Switch-level only: no drive strength, no timing within a clock phase.
- The comparison with the core was made by reading the source, not by running
  MAME against the vectors.
- Every test is preceded by the same instruction (JUN), so behaviour depending
  on some other hidden state would not show up.

**What I can provide**

- The vectors (gzip JSON, one file per opcode) and the generator.
- The netlist, the simulator and the extraction scripts, so the results can be
  reproduced or the method criticised.

If someone with a 4004 and a logic analyser could capture X2/X3 for a handful of
instructions and the TEST timing, that would settle whether these are worth
acting on. I am not proposing a code change before that.

Credit: mask-layer tracings from the Intel 4004 35th Anniversary Project,
4004.com (Tim McNerney, Lajos Kintli, Fred Huettig, Barry and Brian Silverman,
Christopher Tarnovsky), CC BY-NC-SA 3.0. The netlist and vectors are derived
from them and carry the same non-commercial terms, which matters for whether
MAME could ship anything derived from them.

[link to vectors and code]
