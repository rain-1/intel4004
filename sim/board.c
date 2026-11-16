#include "board.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

enum { A1, A2, A3, M1, M2, X1, X2, X3 };

void board_init(Board *b, const char *netfile, Mcs4 *mem) {
    char names[32][16];
    int nodes[32], np;
    memset(b, 0, sizeof *b);
    b->chip = chip_load(netfile, names, nodes, &np);
    b->mem = mem;
    #define PAD(field, name) for (int i = 0; i < np; i++) if (!strcmp(names[i], name)) b->field = nodes[i];
    PAD(phi1, "PHI1") PAD(phi2, "PHI2") PAD(reset, "RESET") PAD(test, "TEST") PAD(sync, "SYNC")
    PAD(d[0], "D0") PAD(d[1], "D1") PAD(d[2], "D2") PAD(d[3], "D3")
    PAD(cm[0], "CMROM") PAD(cm[1], "CMRAM0") PAD(cm[2], "CMRAM1") PAD(cm[3], "CMRAM2") PAD(cm[4], "CMRAM3")
    #undef PAD
    b->slot = -1;
    b->drive = -1;
}

int board_bus(const Board *b) {
    int v = 0;
    for (int i = 0; i < 4; i++) v |= chip_read(b->chip, b->d[i]) << i;
    return v;
}

static int cm_lines(const Board *b) {
    int v = 0;
    for (int i = 0; i < 5; i++) v |= chip_read(b->chip, b->cm[i]) << i;
    return v;
}

static void bus_drive(Board *b, int nibble) {
    b->drive = nibble;
    for (int i = 0; i < 4; i++) {
        if (nibble < 0) chip_release(b->chip, b->d[i]);
        else chip_drive(b->chip, b->d[i], (nibble >> i) & 1);
    }
}

void board_set_test(Board *b, int level) {
    chip_drive(b->chip, b->test, level);
    chip_settle(b->chip);
}

/* What the memory chips do with the bus. Sampling happens while phi2 is active; whatever
 * the board will drive in the NEXT period is switched on after phi2 ends, which is also
 * when the CPU itself changes what it drives. */
static void sample(Board *b) {
    int bus = board_bus(b), cm = cm_lines(b);
    Mcs4 *m = b->mem;
    switch (b->slot) {
    case A1: b->addr = bus; break;
    case A2: b->addr |= bus << 4; break;
    case A3: b->addr |= bus << 8; mcs4_fetch(m, b->addr); break;
    case M2:
        b->io_cm = cm;
        b->io_opa = bus;
        break;
    case X2:
        if (b->io_cm) {
            if (!mcs4_io_is_read(b->io_opa)) mcs4_io_write(m, b->io_cm, b->io_opa, bus);
        } else if (cm) {
            b->src_cm = cm;
            b->src_hi = bus;
        }
        break;
    case X3:
        if (b->src_cm) mcs4_src(m, b->src_cm, b->src_hi, bus);
        b->src_cm = 0;
        break;
    }
}

static int next_drive(Board *b) {
    switch (b->slot) {   /* slot that just finished */
    case A3: return b->in_reset ? 0 : b->mem->rom[b->addr] >> 4;
    case M1: return b->in_reset ? 0 : b->mem->rom[b->addr] & 15;
    case X1:
        if (b->io_cm && mcs4_io_is_read(b->io_opa)) return mcs4_io_read(b->mem, b->io_cm, b->io_opa);
        return -1;
    default: return -1;
    }
}

void board_period(Board *b) {
    Chip *c = b->chip;
    #define STEP_DONE() do { if (b->after_step) b->after_step(b->user); } while (0)
    chip_drive(c, b->phi1, 1); chip_settle(c); STEP_DONE();
    chip_drive(c, b->phi1, 0); chip_settle(c); STEP_DONE();
    chip_drive(c, b->phi2, 1); chip_settle(c);
    int sync = chip_read(c, b->sync);
    if (b->slot >= 0) sample(b);
    STEP_DONE();
    chip_drive(c, b->phi2, 0); chip_settle(c);
    if (b->slot >= 0) {
        bus_drive(b, next_drive(b));
        chip_settle(c);
        if (b->slot == X3) b->cycles++;
    }
    STEP_DONE();
    #undef STEP_DONE
    /* SYNC is active through X3, so the period after it is A1 */
    if (sync) b->slot = A1;
    else if (b->slot >= 0) b->slot = (b->slot + 1) & 7;
}

void board_cycle(Board *b) {
    do board_period(b); while (b->slot != A1);
}

void board_reset(Board *b) {
    Chip *c = b->chip;
    chip_power_on(c);
    chip_drive(c, b->phi1, 0);
    chip_drive(c, b->phi2, 0);
    chip_drive(c, b->test, 0);
    chip_drive(c, b->reset, 1);
    chip_settle(c);
    b->slot = -1;
    b->in_reset = 1;                          /* the ROMs are in reset too: they feed NOPs */
    FILE *log = b->mem->log;
    b->mem->log = NULL;                       /* don't log garbage during reset */
    for (int i = 0; i < 96; i++) board_period(b);
    while (b->slot != X3) board_period(b);    /* release RESET just before a cycle starts */
    chip_drive(c, b->reset, 0);
    chip_settle(c);
    while (b->slot != A1) board_period(b);
    b->in_reset = 0;
    b->io_cm = b->src_cm = 0;
    b->cycles = 0;
    b->mem->log = log;
}
