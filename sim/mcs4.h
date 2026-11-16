/* The rest of an MCS-4 system, modelled behaviourally: 4001 ROMs (with I/O ports) and
 * 4002 RAMs (with output ports). Both the transistor-level CPU and the reference
 * emulator talk to this same model, so their activity logs can be compared line by line. */
#ifndef MCS4_H
#define MCS4_H
#include <stdio.h>

/* "cm" arguments are bit masks of command lines: bit0 = CM-ROM, bits1..4 = CM-RAM0..3 */
#define CM_ROM 1

typedef struct Mcs4 {
    unsigned char rom[4096];
    unsigned char ram[4][4][4][16];   /* [bank][chip][register][character] */
    unsigned char status[4][4][4][4]; /* [bank][chip][register][0..3] */
    unsigned char ram_port[4][4];     /* 4002 output ports */
    unsigned char rom_port[16];       /* 4001 output latches */
    unsigned char rom_in[16];         /* 4001 input pins */
    unsigned char src_rom;            /* last SRC address seen by the ROMs */
    unsigned char src_ram[4];         /* last SRC address seen by each RAM bank */
    FILE *log;                        /* optional activity log */
    void (*on_rom_port)(struct Mcs4 *, int chip, int value);
    void *user;
} Mcs4;

void mcs4_init(Mcs4 *m);
int  mcs4_load_rom(Mcs4 *m, const char *path);
void mcs4_fetch(Mcs4 *m, int addr);                 /* log only */
void mcs4_src(Mcs4 *m, int cm, int hi, int lo);     /* SRC: latch chip/register/character */
int  mcs4_io_is_read(int opa);                      /* does I/O instruction 0xE<opa> read the bus? */
int  mcs4_io_read(Mcs4 *m, int cm, int opa);
void mcs4_io_write(Mcs4 *m, int cm, int opa, int value);

#endif
