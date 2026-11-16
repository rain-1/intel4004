; Every accumulator-group instruction on every accumulator value with carry clear and set.
        NOP
        FIM P7, $00
        SRC P7
        FIM P0, $00         ; R0 = accumulator value under test
loop:   JMS run
        ISZ R0, loop
done:   JUN done

        ORG $100
run:    LD R0
        CLC
        CLB
        JMS dump
        LD R0
        STC
        CLB
        JMS dump
        LD R0
        CLC
        CLC
        JMS dump
        LD R0
        STC
        CLC
        JMS dump
        LD R0
        CLC
        IAC
        JMS dump
        LD R0
        STC
        IAC
        JMS dump
        LD R0
        CLC
        CMC
        JMS dump
        LD R0
        STC
        CMC
        JMS dump
        LD R0
        CLC
        CMA
        JMS dump
        LD R0
        STC
        CMA
        JMS dump
        LD R0
        CLC
        RAL
        JMS dump
        LD R0
        STC
        RAL
        JMS dump
        LD R0
        CLC
        RAR
        JMS dump
        LD R0
        STC
        RAR
        JMS dump
        LD R0
        CLC
        TCC
        JMS dump
        LD R0
        STC
        TCC
        JMS dump
        LD R0
        CLC
        DAC
        JMS dump
        LD R0
        STC
        DAC
        JMS dump
        LD R0
        CLC
        TCS
        JMS dump
        LD R0
        STC
        TCS
        JMS dump
        LD R0
        CLC
        STC
        JMS dump
        LD R0
        CLC
        DAA
        JMS dump
        LD R0
        STC
        DAA
        JMS dump
        LD R0
        CLC
        KBP
        JMS dump
        LD R0
        STC
        KBP
        JMS dump
        BBL 0

dump:   WRR                 ; accumulator, then carry
        TCC
        WRR
        BBL 0
