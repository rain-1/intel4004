/* Wires the transistor-level 4004 to the MCS-4 memory model, pin by pin. */
#ifndef BOARD_H
#define BOARD_H
#include "switchsim.h"
#include "mcs4.h"

typedef struct {
    Chip *chip;
    Mcs4 *mem;
    int phi1, phi2, reset, test, sync, d[4], cm[5];
    int slot;            /* 0..7 = A1 A2 A3 M1 M2 X1 X2 X3; -1 until first SYNC */
    int addr;            /* address being fetched this cycle */
    int io_cm, io_opa;   /* I/O instruction latched at M2 (io_cm == 0: none) */
    int src_cm, src_hi;  /* SRC in progress (latched at X2) */
    int in_reset;        /* RESET is asserted (board-wide) */
    int drive;           /* nibble the board is putting on the bus, or -1 */
    long cycles;         /* completed instruction cycles */
    void (*after_step)(void *user);   /* optional: called after each clock phase settles */
    void *user;
} Board;

void board_init(Board *b, const char *netfile, Mcs4 *mem);
void board_reset(Board *b);          /* power on and hold RESET for a while */
void board_set_test(Board *b, int logic_level);
void board_period(Board *b);         /* one clock period (phi1 pulse, phi2 pulse) */
void board_cycle(Board *b);          /* one full instruction cycle (8 periods) */
int  board_bus(const Board *b);      /* current data bus value */

#endif
