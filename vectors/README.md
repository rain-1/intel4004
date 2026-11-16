# Intel 4004 single-instruction test vectors

102,400 tests (400 for each of the 256 opcodes) generated from the transistor-level
netlist in this repository, in the style of the SingleStepTests suites. Nothing inside the
chip is peeked or poked: state is set up, and read back, entirely through the pins.

    make vectors                         # regenerate vectors/v1 (about 2.5 minutes on 12 cores)
    python3 tools/analyze_vectors.py vectors/v1

## Format

`v1/XX.json.gz` is a JSON array of tests for opcode `XX`:

    {
      "name": "8A #0", "opcode": 138, "length": 1,          // length in instruction cycles
      "initial": {"pc": 1995, "acc": 12, "cy": 1, "r": [16 values], "stack": [3 return addresses, most recent first],
                  "dcl": 4,                                 // value last given to DCL
                  "test": 0},                               // logic level on the TEST pin
      "fed": [138],                                         // ROM bytes supplied, one per cycle
      "io_in": null,                                        // nibble supplied at X2 for I/O reads
      "final": {"pc": ..., "acc": ..., "cy": ..., "r": [...], "stack": [...],
                "cm_ram": 8},                               // CM-RAM lines selected (bit n = CM-RAMn)
      "cycles": [{"addr": 1995,                             // address the chip put out
                  "bus":    [8 nibbles],                    // data bus in A1 A2 A3 M1 M2 X1 X2 X3
                  "driven": [8 masks],                      // which bus lines the CPU itself was driving
                  "cm":     [8 masks],                      // bit0 CM-ROM, bits1-4 CM-RAM0-3
                  "sync":   [8 bits]}]
    }

All values are logic levels (1 = the negative voltage). Pins are sampled while phi2 is
active in each period. A quarter of the tests start within four bytes of a page end.

## What the vectors show

Documented instructions: all 95,600 vectors for the 239 documented opcodes match the
MCS-4 manual, including the page-boundary cases of JCN, ISZ, FIN and JIN. MAME's
`mcs40.cpp` implements the same semantics (compared by reading the source, not by running it).

The rest answers questions that MAME's source leaves open as FIXME/TODO comments
(`src/devices/cpu/mcs40/mcs40.cpp`, as of November 2026):

**Undefined opcodes.** `01`-`0F`, `FE` and `FF` are all one-cycle NOPs: no state change,
no CM lines. MAME already treats `01`-`0F` as NOP; it logs `FE`/`FF` as unhandled, which
has the same effect.

**"Is 4004 output on the second cycle of two-cycle instruction OPA or low nybble of the
argument?"** (X1). The low nibble of the second byte. In every cycle X1 simply repeats
what was on the bus at M2.

**"What appears on the bus if it isn't SRC, I/O or program memory access?"** (X2). MAME
outputs the high nibble of the last SRC address. The chip has no such register; it shows
whatever is on its internal bus:

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
| I/O reads | (floating: memory drives) | the nibble just read |
| CLB CLC IAC CMC CMA RAL RAR TCC | 0 | F |
| DAC, STC, DCL | F | F |
| TCS | 9 | F |
| DAA | 6 if it corrects, else 0 | F |
| KBP | accumulator after | F |

**"What appears on the bus if it isn't SRC?"** (X3). MAME outputs the low nibble of the
last SRC address; see the X3 column. Outside M1, M2 and the X2 of an I/O read, the CPU
drives all four lines in every period.

**"On which cycle is TEST sampled?"** (JCN). At the end of the FIRST cycle: the level
present when phi2 falls in X3 of the opcode cycle decides the jump. Changes after that are
ignored. MAME samples during the second cycle. (`./i4004-vectors --test-timing`)

**"It actually takes multiple cycles with reset asserted for everything to get cleared."**
PC, accumulator and carry clear within two clock periods; the stack clears one level per
instruction cycle; the index registers clear one pair per instruction cycle, so a chip
with all registers loaded needs 58 clock periods here. Intel's data sheet asks for 64.
(`./i4004-vectors --reset-time`)

## Limits

- This is a switch-level simulation of a netlist taken from layer tracings. It has passed
  every functional check thrown at it, but none of the bus-content findings above has
  been compared with a real 4004. They want confirming on hardware before being treated
  as fact.
- "Driven" means a conducting path to a supply exists in the model. It says nothing about
  drive strength or timing within a clock phase.
- The fourth stack slot cannot be observed through the pins without disturbing it, so
  after BBL the bottom stack entry is not checked.
- Initial states are random; the instruction before every test is the same (`JUN`), so
  behaviour that depended on some other hidden latch would not show up.
