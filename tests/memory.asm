; RAM: main characters, status characters, output ports, all four banks via DCL,
; plus ADM / SBM and ROM port input (RDR).
        NOP
        LDM 0
        XCH R8              ; R8 = bank counter (DCL value 0..7)
bank:   LD R8
        DCL
        FIM P0, $00         ; P0 = RAM address (chip/register, character)
fill:   SRC P0
        LD R1
        ADD R8
        WRM                 ; main character = char index + bank (+ carry)
        LD R0
        WR0
        CMA
        WR1
        LD R8
        WR2
        LD R1
        WR3
        LD R0
        WMP
        ISZ R1, fill
        ISZ R0, fill
        ISZ R8, nextb
        JUN verify
nextb:  LD R8
        RAR                 ; only DCL values 0..7 matter, but run all 16
        JUN bank

        ORG $100
verify: LDM 0
        XCH R8
vbank:  LD R8
        DCL
        FIM P0, $00
        FIM P7, $30
check:  SRC P0
        RDM
        XCH R4
        CLC
        ADM
        XCH R5
        TCC
        XCH R6
        STC
        SBM
        XCH R7
        RD0
        XCH R9
        RD1
        XCH R10
        RD2
        XCH R11
        RD3
        XCH R12
        SRC P7              ; report through ROM port 3
        LD R4
        WRR
        LD R5
        WRR
        LD R6
        WRR
        LD R7
        WRR
        TCC
        WRR
        LD R9
        WRR
        LD R10
        WRR
        LD R11
        WRR
        LD R12
        WRR
        ISZ R1, check
        ISZ R0, check
        ISZ R8, vnext
        JUN ports
vnext:  JUN vbank

        ORG $200
ports:  LDM 0
        DCL
        FIM P0, $00         ; read every ROM input port
rdport: SRC P0
        RDR
        XCH R2
        SRC P7
        LD R2
        WRR
        ISZ R0, rdport
done:   JUN done
