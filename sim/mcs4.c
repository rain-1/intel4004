#include "mcs4.h"
#include <string.h>

void mcs4_init(Mcs4 *m) { memset(m, 0, sizeof *m); }

int mcs4_load_rom(Mcs4 *m, const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    int n = (int)fread(m->rom, 1, sizeof m->rom, f);
    fclose(f);
    return n;
}

void mcs4_fetch(Mcs4 *m, int addr) {
    if (m->log) fprintf(m->log, "@%03X\n", addr);
}

void mcs4_src(Mcs4 *m, int cm, int hi, int lo) {
    int v = (hi << 4) | lo;
    if (cm & CM_ROM) m->src_rom = (unsigned char)v;
    for (int b = 0; b < 4; b++)
        if (cm & (2 << b)) m->src_ram[b] = (unsigned char)v;
    if (m->log) fprintf(m->log, "SRC cm=%02X %02X\n", cm, v);
}

int mcs4_io_is_read(int opa) { return opa >= 8; }

/* first RAM bank whose command line is active, or -1 */
static int first_bank(int cm) {
    for (int b = 0; b < 4; b++) if (cm & (2 << b)) return b;
    return -1;
}

int mcs4_io_read(Mcs4 *m, int cm, int opa) {
    int v = 0, b = first_bank(cm);
    if (opa == 0xA) {                                   /* RDR: ROM input port */
        v = (cm & CM_ROM) ? m->rom_in[m->src_rom >> 4] : 0;
    } else if (b >= 0) {
        int s = m->src_ram[b], chip = s >> 6, reg = (s >> 4) & 3, ch = s & 15;
        if (opa >= 0xC) v = m->status[b][chip][reg][opa - 0xC];   /* RD0..RD3 */
        else v = m->ram[b][chip][reg][ch];                         /* SBM RDM ADM */
    }
    if (m->log) fprintf(m->log, "RD  cm=%02X E%X -> %X\n", cm, opa, v);
    return v;
}

void mcs4_io_write(Mcs4 *m, int cm, int opa, int value) {
    if (m->log) fprintf(m->log, "WR  cm=%02X E%X <- %X\n", cm, opa, value);
    if (opa == 2) {                                     /* WRR: ROM output port */
        if (cm & CM_ROM) {
            int chip = m->src_rom >> 4;
            m->rom_port[chip] = (unsigned char)value;
            if (m->on_rom_port) m->on_rom_port(m, chip, value);
        }
        return;
    }
    for (int b = 0; b < 4; b++) {
        if (!(cm & (2 << b))) continue;
        int s = m->src_ram[b], chip = s >> 6, reg = (s >> 4) & 3, ch = s & 15;
        if (opa == 0) m->ram[b][chip][reg][ch] = (unsigned char)value;      /* WRM */
        else if (opa == 1) m->ram_port[b][chip] = (unsigned char)value;     /* WMP */
        else if (opa >= 4 && opa <= 7) m->status[b][chip][reg][opa - 4] = (unsigned char)value;
        /* opa 3 (WPM) needs extra hardware; ignored */
    }
}
