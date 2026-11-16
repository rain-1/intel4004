#include "ref4004.h"
#include <string.h>

void ref_reset(Ref4004 *c, Mcs4 *mem) {
    memset(c, 0, sizeof *c);
    c->mem = mem;
    c->cm_ram = 2;   /* CM-RAM0 */
}

static int fetch(Ref4004 *c) {
    int pc = c->stack[c->sp];
    mcs4_fetch(c->mem, pc);
    c->stack[c->sp] = (pc + 1) & 0xFFF;
    c->cycles++;
    return c->mem->rom[pc];
}

static void add(Ref4004 *c, int value, int carry_in) {
    int sum = c->acc + value + carry_in;
    c->acc = sum & 15;
    c->cy = sum >> 4;
}

void ref_step(Ref4004 *c) {
    Mcs4 *m = c->mem;
    int op = fetch(c), opr = op >> 4, opa = op & 15;
    int *pc = &c->stack[c->sp];
    int pair = opa & 0xE, cm = CM_ROM | c->cm_ram;
    switch (opr) {
    case 0x0: break;                                             /* NOP */
    case 0x1: {                                                  /* JCN */
        int target = fetch(c);
        int cond = ((opa & 4) && c->acc == 0) || ((opa & 2) && c->cy) || ((opa & 1) && !c->test);
        if (opa & 8) cond = !cond;
        if (cond) *pc = (*pc & 0xF00) | target;
        break;
    }
    case 0x2:
        if (opa & 1) {                                           /* SRC */
            mcs4_src(m, cm, c->r[pair], c->r[pair + 1]);
        } else {                                                 /* FIM */
            int d = fetch(c);
            c->r[pair] = d >> 4; c->r[pair + 1] = d & 15;
        }
        break;
    case 0x3:
        if (opa & 1) {                                           /* JIN */
            *pc = (*pc & 0xF00) | (c->r[pair] << 4) | c->r[pair + 1];
        } else {                                                 /* FIN */
            int a = (*pc & 0xF00) | (c->r[0] << 4) | c->r[1];
            mcs4_fetch(m, a);
            c->cycles++;
            c->r[pair] = m->rom[a] >> 4; c->r[pair + 1] = m->rom[a] & 15;
        }
        break;
    case 0x4: *pc = (opa << 8) | fetch(c); break;                /* JUN */
    case 0x5: {                                                  /* JMS */
        int target = (opa << 8) | fetch(c);
        c->sp = (c->sp + 1) & 3;
        c->stack[c->sp] = target;
        break;
    }
    case 0x6: c->r[opa] = (c->r[opa] + 1) & 15; break;           /* INC */
    case 0x7: {                                                  /* ISZ */
        int target = fetch(c);
        c->r[opa] = (c->r[opa] + 1) & 15;
        if (c->r[opa]) *pc = (*pc & 0xF00) | target;
        break;
    }
    case 0x8: add(c, c->r[opa], c->cy); break;                   /* ADD */
    case 0x9: add(c, c->r[opa] ^ 15, !c->cy); break;             /* SUB */
    case 0xA: c->acc = c->r[opa]; break;                         /* LD  */
    case 0xB: { int t = c->acc; c->acc = c->r[opa]; c->r[opa] = t; break; } /* XCH */
    case 0xC: c->sp = (c->sp - 1) & 3; c->acc = opa; break;      /* BBL */
    case 0xD: c->acc = opa; break;                               /* LDM */
    case 0xE:
        switch (opa) {
        case 0x8: add(c, mcs4_io_read(m, cm, opa) ^ 15, !c->cy); break;   /* SBM */
        case 0xB: add(c, mcs4_io_read(m, cm, opa), c->cy); break;         /* ADM */
        case 0x9: case 0xA: case 0xC: case 0xD: case 0xE: case 0xF:
            c->acc = mcs4_io_read(m, cm, opa); break;                     /* RDM RDR RD0-3 */
        default: mcs4_io_write(m, cm, opa, c->acc); break;                /* WRM WMP WRR WPM WR0-3 */
        }
        break;
    case 0xF:
        switch (opa) {
        case 0x0: c->acc = 0; c->cy = 0; break;                  /* CLB */
        case 0x1: c->cy = 0; break;                              /* CLC */
        case 0x2: add(c, 1, 0); break;                           /* IAC */
        case 0x3: c->cy = !c->cy; break;                         /* CMC */
        case 0x4: c->acc ^= 15; break;                           /* CMA */
        case 0x5: { int v = (c->acc << 1) | c->cy; c->acc = v & 15; c->cy = v >> 4; break; } /* RAL */
        case 0x6: { int v = c->acc | (c->cy << 4); c->cy = v & 1; c->acc = v >> 1; break; }  /* RAR */
        case 0x7: c->acc = c->cy; c->cy = 0; break;              /* TCC */
        case 0x8: add(c, 15, 0); break;                          /* DAC */
        case 0x9: c->acc = c->cy ? 10 : 9; c->cy = 0; break;     /* TCS */
        case 0xA: c->cy = 1; break;                              /* STC */
        case 0xB:                                                /* DAA */
            if (c->acc > 9 || c->cy) {
                int sum = c->acc + 6;
                c->acc = sum & 15;
                if (sum > 15) c->cy = 1;
            }
            break;
        case 0xC: {                                              /* KBP */
            static const int k[16] = {0, 1, 2, 15, 3, 15, 15, 15, 4, 15, 15, 15, 15, 15, 15, 15};
            c->acc = k[c->acc];
            break;
        }
        case 0xD: {                                              /* DCL */
            static const int lines[8] = {1, 2, 4, 6, 8, 10, 12, 14};
            c->cm_ram = lines[c->acc & 7] << 1;
            break;
        }
        default: break;
        }
        break;
    }
}
