; Control flow: all 16 JCN conditions under every accumulator/carry state, JMS/BBL
; nesting (including the 4th call that wraps the 3-level stack), JIN, FIN, ISZ, INC,
; and the page-boundary cases of JCN, ISZ, JIN and FIN. Run with --test 0 and --test 1.
        NOP
        FIM P7, $00
        SRC P7
        JMS jcnall
        JMS nest1
        WRR                 ; BBL value from the outermost return
        JMS regs
        JUN pages

nest1:  LDM 1
        WRR
        JMS nest2
        WRR
        BBL 1
nest2:  LDM 2
        WRR
        JMS nest3
        WRR
        BBL 2
nest3:  LDM 3
        WRR
        BBL 3

regs:   FIM P0, $01         ; every register through FIM, INC, LD, XCH
        FIM P1, $23
        FIM P2, $45
        FIM P3, $67
        FIM P4, $89
        FIM P5, $AB
        FIM P6, $CD
        INC R0
        INC R1
        INC R2
        INC R3
        INC R4
        INC R5
        INC R6
        INC R7
        INC R8
        INC R9
        INC R10
        INC R11
        INC R12
        INC R13
        LD R0
        WRR
        LD R1
        WRR
        LD R2
        WRR
        LD R3
        WRR
        LD R4
        WRR
        LD R5
        WRR
        LD R6
        WRR
        LD R7
        WRR
        LD R8
        WRR
        LD R9
        WRR
        LD R10
        WRR
        LD R11
        WRR
        LD R12
        WRR
        LD R13
        WRR
        LDM 9
        XCH R13
        WRR
        XCH R13
        WRR
        BBL 0

        ORG $100
; jcnall: for acc in {0,5}, carry in {0,1}: try each condition; report 1 if taken else 0
jcnall: LDM 0
        XCH R4
        CLC
        JMS jcn16
        LDM 0
        XCH R4
        STC
        JMS jcn16
        LDM 5
        XCH R4
        CLC
        JMS jcn16
        LDM 5
        XCH R4
        STC
        JMS jcn16
        BBL 0

        ORG $200
jcn16:  LD R4
        JCN 0, t0
        JMS nottaken
        JUN c1
t0:     JMS taken
c1:     LD R4
        JCN 1, t1
        JMS nottaken
        JUN c2
t1:     JMS taken
c2:     LD R4
        JCN 2, t2
        JMS nottaken
        JUN c3
t2:     JMS taken
c3:     LD R4
        JCN 3, t3
        JMS nottaken
        JUN c4
t3:     JMS taken
c4:     LD R4
        JCN 4, t4
        JMS nottaken
        JUN c5
t4:     JMS taken
c5:     LD R4
        JCN 5, t5
        JMS nottaken
        JUN c6
t5:     JMS taken
c6:     LD R4
        JCN 6, t6
        JMS nottaken
        JUN c7
t6:     JMS taken
c7:     LD R4
        JCN 7, t7
        JMS nottaken
        JUN c8
t7:     JMS taken
c8:     LD R4
        JCN 8, t8
        JMS nottaken
        JUN c9
t8:     JMS taken
c9:     LD R4
        JCN 9, t9
        JMS nottaken
        JUN c10
t9:     JMS taken
c10:    LD R4
        JCN 10, t10
        JMS nottaken
        JUN c11
t10:    JMS taken
c11:    LD R4
        JCN 11, t11
        JMS nottaken
        JUN c12
t11:    JMS taken
c12:    LD R4
        JCN 12, t12
        JMS nottaken
        JUN c13
t12:    JMS taken
c13:    LD R4
        JCN 13, t13
        JMS nottaken
        JUN c14
t13:    JMS taken
c14:    LD R4
        JCN 14, t14
        JMS nottaken
        JUN c15
t14:    JMS taken
c15:    LD R4
        JCN 15, t15
        JMS nottaken
        BBL 0
t15:    JMS taken
        BBL 0

        ORG $300
; these preserve the carry: report without touching it
taken:  XCH R5
        LDM 1
        WRR
        XCH R5
        BBL 0
nottaken: XCH R5
        LDM 0
        WRR
        XCH R5
        BBL 0

; ---- page-boundary behaviour -------------------------------------------------
pages:  FIM P0, lo(table)   ; FIN in the middle of a page reads this page
        FIN P1
        JMS show1
        FIM P1, lo(jintgt)
        JIN P1
        LDM 15              ; skipped
        WRR
jintgt: LDM 7
        WRR
        JUN edge1
table:  DB $5A
show1:  LD R2
        WRR
        LD R3
        WRR
        BBL 0

        ORG $3EE
edge1:  FIM P0, $10         ; FIN as the LAST byte of a page: which page does it read?
        JUN $3FF
        ORG $3FF
        FIN P1
        ; -- page 4 --
        JMS show4
        FIM P1, $40
        LDM 0
        JUN $4FE
        ORG $410
        DB $C3              ; what FIN finds if it used the next page ($410)
        ORG $420
show4:  LD R2
        WRR
        LD R3
        WRR
        BBL 0
        ORG $440
        LDM 4               ; JIN at the end of page 4 landing in page 4...
        WRR
        JUN edge2
        ORG $4FE
        NOP
        JIN P1              ; ... or, being the last byte of the page, in page 5?
        ORG $540
        LDM 5
        WRR
        JUN edge2
        ORG $560
edge2:  LDM 0
        JUN $5FE
        ORG $5FE
        JCN Z, $605         ; JCN whose 2nd byte ends the page: target is in the NEXT page
        ORG $600
        LDM 14
        WRR
        JUN stackwrap
        LDM 6
        WRR
        JUN stackwrap
        ORG $700
; four nested calls: the 4th overwrites the oldest return address
stackwrap: JMS w1
        LDM 10              ; never reached if the stack wrapped
        WRR
done:   JUN done
w1:     JMS w2
        LDM 11
        WRR
        BBL 0
w2:     JMS w3
        LDM 12
        WRR
        BBL 0
w3:     JMS w4
        LDM 13
        WRR
        BBL 0
w4:     LDM 9
        WRR
        BBL 0
        ; the final BBL in w1 "returns" here: its stack slot was reused as w4's program counter
        LDM 8
        WRR
        JUN done
