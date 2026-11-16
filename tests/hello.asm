; smallest possible sign of life: print "HI" on the teletype
        FIM P0, $00     ; ROM chip 0 = low nibble latch
        FIM P1, $10     ; ROM chip 1 = high nibble + print
        SRC P0
        LDM $8          ; 'H' = $48
        WRR
        SRC P1
        LDM $4
        WRR
        SRC P0
        LDM $9          ; 'I' = $49
        WRR
        SRC P1
        LDM $4
        WRR
        SRC P0
        LDM $A          ; newline = $0A
        WRR
        SRC P1
        LDM $0
        WRR
done:   JUN done
