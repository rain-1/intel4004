/* A conventional instruction-level 4004 emulator, written from the MCS-4 manual.
 * It exists only as an independent yardstick for the transistor-level simulation. */
#ifndef REF4004_H
#define REF4004_H
#include "mcs4.h"

typedef struct {
    Mcs4 *mem;
    int acc, cy, r[16];
    int stack[4], sp;     /* stack[sp] is the program counter */
    int cm_ram;           /* CM-RAM lines selected by DCL (mask in "cm" format) */
    int test;             /* logic level on the TEST pin */
    long cycles;
} Ref4004;

void ref_reset(Ref4004 *c, Mcs4 *mem);
void ref_step(Ref4004 *c);   /* one instruction (1 or 2 cycles) */

#endif
