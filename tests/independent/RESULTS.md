# Check against an emulator I did not write

The reference emulator in `sim/ref4004.c` was written by the same model that
wrote the simulator, so agreement between the two is a weak check. This is a
stronger one: the 102,400 single-instruction vectors generated from the
transistor netlist (`vectors/v1`) replayed through an independent emulator.

**Emulator:** `i40xx-emu` by Mark Ablovatskii, https://github.com/markablov/i40xx
(MIT), commit `15db96b`. It is a pin- and stage-level JavaScript model of the
4004 and 4040. None of it is copied into this repository.

    git clone https://github.com/markablov/i40xx /tmp/i40xx
    bun tests/independent/check_i40xx.js /tmp/i40xx vectors/v1 report.tsv

The harness uses only that project's CPU class. It sets the registers from the
vector's initial state, plays the ROM and RAM on the data pins as the vector
recorded, and compares the final PC, accumulator, carry, 16 index registers,
return stack and selected CM-RAM lines. It also compares the address the CPU
puts out in each cycle and, for SRC, the two nibbles and the CM-RAM lines on
the bus.

## Result (run on 2026-11-16)

| | Vectors | Identical |
|---|---|---|
| All 256 opcodes | 102,400 | 96,583 |
| The 239 documented 4004 opcodes | 95,600 | 94,056 |
| Documented, excluding JCN with the TEST bit and RDR | 92,000 | 92,000 |

Every difference falls in one of three groups, and each is something the other
emulator does not model. Per-opcode counts are in `i40xx_report.tsv`.

1. **JCN with the TEST condition bit set** (opcodes 11, 13, ... 1F): 1,172 of
   3,200 differ, in the PC only. That emulator's JCN has no TEST term. The
   3,200 JCN vectors without the TEST bit are all identical.
2. **RDR** (EA): 372 of 400 differ, in the accumulator only. That emulator's
   CPU has no ROM-port read. The 28 that match are cases where the value read
   equals the accumulator already.
3. **Opcodes undefined on the 4004** (01-0F, FE, FF): that emulator implements
   01-0F as 4040 instructions (HLT, OR4, AN6 and so on) and throws on the rest.
   The netlist treats all of them as NOPs.

## What this does and does not establish

- For 92,000 vectors covering every documented instruction except RDR and the
  TEST term of JCN, the transistor netlist and an independently written
  emulator agree exactly, including page-boundary cases, the stack, and which
  CM-RAM lines each DCL value selects.
- The TEST term of JCN and RDR are still checked only against my own reference
  and the formula in Intel's manual. The Busicom firmware uses both (printer
  drum timing on TEST, keyboard on ROM ports) and computes correctly, which is
  indirect support.
- An independent emulator and the netlist could share a misreading of the
  manual. Only a real chip rules that out.
- Bus contents in undocumented cycles are not modelled by that emulator, so the
  findings in `vectors/README.md` about them are not checked here.

## Emulators tried and not used

- Pyntel4004 (alshapton): rejects about half the address space and needs its
  own executer and operand decoder to run, so differences could not be
  attributed cleanly.
- K4004 (Kostu96), lpg2709/emulator-Intel-4004, CodeAbbey/intel4004-emu: on
  reading the source, each is incomplete or visibly wrong for some documented
  instructions (10-bit PC, BBL marked TODO, CMA clearing the accumulator, a
  teaching subset), so they are not usable as references.
