; ---------------------------------------------------------------------------
;  HAPPY BIRTHDAY, 4004
;
;  A birthday card computed by the Intel 4004 itself. The chip is told two
;  years, works out its own age with the BCD arithmetic it was built for
;  (it was designed to run a desk calculator), and puts one candle on the
;  cake for every year.
;
;  Output device: a teletype on two 4001 ROM output ports. Write the low
;  nibble of a character to ROM 0, then the high nibble to ROM 1 to print.
; ---------------------------------------------------------------------------

; registers:  P0 (R0,R1)   text pointer        P1 (R2,R3)  character to print
;             R4..R7       1971, low digit first (later: loop counter in R4)
;             R8..R11      this year, low digit first; becomes the age
;             P6, P7       addresses of the two teletype ports

        ORG $000
        NOP
        FIM P6, $00             ; ROM 0 port: low nibble
        FIM P7, $10             ; ROM 1 port: high nibble + print
        FIM P4, $62             ; this year: 2 0 2 6
        FIM P5, $02
        FIM P2, $17             ; born:      1 9 7 1
        FIM P3, $91

        FIM P0, lo(banner)
        JMS puts1

        LD R11                  ; print "2026 - 1971 = "
        JMS putdigit
        LD R10
        JMS putdigit
        LD R9
        JMS putdigit
        LD R8
        JMS putdigit
        FIM P0, lo(minus)
        JMS puts1
        LD R7
        JMS putdigit
        LD R6
        JMS putdigit
        LD R5
        JMS putdigit
        LD R4
        JMS putdigit
        FIM P0, lo(equals)
        JMS puts1

; age = year - 1971, one decimal digit at a time. TCS loads 9 or 10 depending
; on whether the previous digit borrowed, DAA pulls the sum back into decimal.
        STC                     ; no borrow into the first digit
        TCS
        SUB R4
        CLC
        ADD R8
        DAA
        XCH R8                  ; ones
        TCS
        SUB R5
        CLC
        ADD R9
        DAA
        XCH R9                  ; tens
        TCS
        SUB R6
        CLC
        ADD R10
        DAA
        XCH R10
        TCS
        SUB R7
        CLC
        ADD R11
        DAA
        XCH R11

        LD R9
        JMS putdigit
        LD R8
        JMS putdigit
        FIM P0, lo(years)
        JMS puts1

; candles: one row of ten for each ten years ...
        LD R9
        JCN Z, ones
        CMA
        IAC
        XCH R4                  ; R4 = -tens, counts up to zero
row:    FIM P0, lo(tenrow)
        JMS puts1
        ISZ R4, row
; ... and a last row for the odd years
ones:   LD R8
        JCN Z, cake
        CMA
        IAC
        XCH R4
        FIM P0, lo(indent)
        JMS puts1
candle: FIM P0, lo(one)
        JMS puts1
        ISZ R4, candle
        FIM P0, lo(newline)
        JMS puts1

cake:   FIM P0, lo(caketop)
        JMS puts2
        LD R9
        JMS putdigit
        LD R8
        JMS putdigit
        FIM P0, lo(cakerest)
        JMS puts2
done:   JUN done                ; the 4004 has no HALT; it just waits here

; print the decimal digit in the accumulator
putdigit:
        XCH R3
        LDM 3                   ; ASCII '0'..'9' = $30..$39
        XCH R2
; print the character in R2 (high nibble), R3 (low nibble)
putchar:
        SRC P6
        LD R3
        WRR
        SRC P7
        LD R2
        WRR
        BBL 0

; ---------------------------------------------------------------------------
; Text lives in ROM, and FIN can only read the page it executes in, so each
; page of text carries its own copy of the print loop.
; ---------------------------------------------------------------------------
        ORG $100
puts1:  FIN P1                  ; character at (this page):R0R1 -> R2,R3
        LD R2
        JCN NZ, p1out
        LD R3
        JCN Z, p1end            ; a zero byte ends the string
p1out:  JMS putchar
        ISZ R1, puts1           ; next character
        INC R0
        JUN puts1
p1end:  BBL 0

banner: DB 10, "INTEL 4004 MICROPROCESSOR", 10
        DB "ANNOUNCED 15 NOVEMBER 1971", 10, 10, "  ", 0
minus:  DB " - ", 0
equals: DB " = ", 0
years:  DB " YEARS", 10, 10, 0
tenrow: DB "     i i i i i i i i i i", 10, 0
indent: DB "          ", 0
one:    DB "i ", 0
newline: DB 10, 0

        ORG $200
puts2:  FIN P1
        LD R2
        JCN NZ, p2out
        LD R3
        JCN Z, p2end
p2out:  JMS putchar
        ISZ R1, puts2
        INC R0
        JUN puts2
p2end:  BBL 0

caketop:  DB "  .-----------------------.", 10
          DB "  |  HAPPY ", 0
cakerest: DB "TH BIRTHDAY  |", 10
          DB "  |   2300 TRANSISTORS,   |", 10
          DB "  |    STILL COUNTING.    |", 10
          DB "  '-----------------------'", 10, 0
