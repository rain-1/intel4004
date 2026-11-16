; Exhaustive adder check: every accumulator x register x carry-in combination
; through ADD and SUB, results and carry-out written to a ROM port.
        NOP
        FIM P7, $00
        SRC P7              ; all WRR below go to ROM port 0
        FIM P0, $00         ; R0 = a, R1 = b
loop:   LD R0
        CLC
        ADD R1
        WRR
        TCC
        WRR
        LD R0
        STC
        ADD R1
        WRR
        TCC
        WRR
        LD R0
        CLC
        SUB R1
        WRR
        TCC
        WRR
        LD R0
        STC
        SUB R1
        WRR
        TCC
        WRR
        ISZ R1, loop
        ISZ R0, loop
done:   JUN done
