# How well does the lesion floorplan hold up?

`figures/floorplan.png` divides the die into zones using only what each
transistor's failure breaks. This note records the attempts to test it
(2026-11-16).

## No published floorplan to compare with

I looked for a labelled floorplan of the 4004 die (block names placed on the
chip) in the 4004.com downloads in `source/`, on Wikimedia Commons and by web
search. I did not find one I could use. So the comparison against "Intel's
floorplan" has not been done, and the zone names remain my reading.

## Check 1: Faggin's description of the schematic (qualitative)

Federico Faggin's page on the original schematics
(http://www.intel4004.com/4004_original_schematics.htm) says the schematic
"mirrored as closely as possible the layout plan of the chip", and that it has
three sheets:

- Memory block: index registers, address stack, program counter with
  incrementer, refresh counters.
- Control logic block: instruction register and decoder, control logic for the
  other two blocks.
- Arithmetic unit block: adder, accumulator and flags, internal bus control,
  system timing.

The lesion floorplan is consistent with that grouping: the index-register zone
and the program-counter-and-stack zone are the two large arrays and sit side
by side (one half of the die); the accumulator and arithmetic zone and most of
the "breaks everything" timing area are on the other half; the single-
instruction groups (decode) lie between them. This is agreement at the level
of "which things are neighbours", nothing finer. I have not registered the
schematic sheets to the die.

## Check 2: blocks identified a different way (quantitative)

The lesion study also labelled transistors from the behaviour of the intact
chip (a node that always equals register R5 bit 2 belongs to the index
registers; see RESULTS.txt section 1). That uses no lesions. It is the same
model and the same author, so it is a consistency check, not outside evidence.

Transistors that directly touch a behaviourally identified node, by lesion zone:

| Behaviour-based block | n | Lesion zone they fall in |
|---|---|---|
| Index registers | 128 | index registers 128 |
| Address stack array | 22 | program counter and stack 22 |
| Program counter path | 22 | program counter and stack 22 |
| DCL / CM-RAM | 26 | command lines 24, reset only 2 |
| Accumulator / carry | 83 | accumulator and arithmetic 44, everything 19, command lines 9, PC 5, other 6 |
| Timing | 300 | everything 154, PC 57, index registers 44, command lines 21, arithmetic 12, other 12 |
| Instruction decode | 1,024 | everything 340, index registers 225, arithmetic 210, PC 140, command lines 39, other 70 |

Reading:

- The storage blocks agree completely.
- Only about half of the accumulator/carry transistors land in the arithmetic
  zone. The rest break more than the accumulator when they fail.
- Decode and timing transistors are spread over every zone. This is the main
  limitation of the floorplan: **a zone means "failure here corrupts this
  state", not "this is that circuit".** Much of each coloured zone outside the
  two arrays is decode and timing logic that serves that block.
