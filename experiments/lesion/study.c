/* study: full transistor lesion study on the switch-level Intel 4004.
 *
 * Successor of lesion.c (the pilot). Same rig (adapted from sim/vectors.c: scripted bus,
 * state set up and read back only through the pins), but a deterministic structured test
 * set instead of random tests, failure KINDS per test, and artefact monitors.
 *
 * Test set (built by build_tests(), documented in RESULTS.txt):
 *   6 base states x every one of the 256 opcodes: all-0, all-1, 0101, 1010 patterns, and two
 *   states with distinct register values; page-edge PCs, both TEST levels, both carries,
 *   four stack-pointer positions; plus class-specific extras (JCN condition matrix, ISZ wrap
 *   and page edge, FIN/JIN at a page end, ALU carry patterns, every accumulator value for
 *   the accumulator group, DCL values, I/O input nibbles, stack depth for JMS/BBL), plus
 *   three reset tests (load a state, hold RESET 64 periods, read back).
 * Tests sharing an initial state share one reset + set-up: the chip is snapshotted after
 * set-up and restored before each instruction (exact; the simulator is deterministic).
 *
 * Modes:
 *   study --list-tests                     the test table (one line per test)
 *   study --verify                         intact chip vs the reference emulator (sim/ref4004.c)
 *   study T[o|c] ... | --all-from FILE     one result line per lesion (format below)
 *   study --peek  T[o|c] ...               internal divergence vs the intact chip (lockstep)
 *   study --fuzz N [--minimise] T[o|c] ... N random multi-instruction programs per lesion; with
 *                                          --minimise, shrink the first catching program
 *   study --probe FILE [--probe-random N]  intact chip: node states per test and slot (binary)
 *   study --floatprof                      intact chip: per node, fraction of samples floating
 *
 * Lesion result line (space separated):
 *   T mode nfail_tests nbad_ops reset_mask nosync unstable contention
 *   float_gate float_a float_b n_samples cpu_ms KINDS
 * float_*: samples (phi2 high, every period) in which that node of the lesioned device was not
 * connected to any supply or pin driver (-1 if the node is a supply). KINDS: 4 hex digits per
 * test, in test order, = the 16-bit failure-kind mask (K_* below) of that test.
 */
#include "lesionsim.h"
#include "../../sim/ref4004.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { A1, A2, A3, M1, M2, X1, X2, X3 };

/* failure kinds, one bit each */
enum {
    K_ACC = 1 << 0, K_CY = 1 << 1, K_REG = 1 << 2, K_PC = 1 << 3, K_STACK = 1 << 4, K_CMRAM = 1 << 5,
    K_ADDR = 1 << 6,    /* A1-A3 address nibbles put out during the instruction */
    K_MBUS = 1 << 7,    /* M1/M2 samples (the chip fighting the ROM data) */
    K_X1 = 1 << 8,
    K_XDOC = 1 << 9,    /* X2/X3 where documented: SRC address, I/O-write data */
    K_XUND = 1 << 10,   /* X2/X3 elsewhere: undocumented internal-bus contents (vectors/README.md) */
    K_DRV = 1 << 11,    /* which bus lines the CPU drives */
    K_CM = 1 << 12,     /* CM-ROM / CM-RAM lines during the instruction */
    K_SYNC = 1 << 13,
    K_NOSYNC = 1 << 14, /* SYNC never came during reset (rig gave up waiting) */
    K_UNST = 1 << 15,   /* a settle hit the 400-pass cap during this test */
};

typedef struct {
    Chip *chip;
    int phi1, phi2, reset, test, sync, d[4], cm[5];
    int slot;
    int nosync;
    /* monitors */
    int mon[3], n_mon;              /* nodes whose floating is counted */
    long mon_float[3], mon_samples;
    unsigned char *drv_all;         /* --floatprof */
    long *float_cnt, float_samples;
    unsigned char *snap_buf;        /* --peek: per-period node states (record / compare) */
    long snap_pos, snap_cap;
    int peek_mode;                  /* 0 off, 1 record, 2 compare */
    long *diff_cnt;                 /* --peek compare: per node, samples differing */
    long diff_samples;
    unsigned char *probe_rec;       /* --probe: node states at phi2 of each slot, one test */
    int probe_on;
} Rig;

typedef struct { int addr; int bus[8], driven[8], cm[8], sync[8]; } Cycle;
typedef struct { int acc, cy, r[16], pc, stack[3], test, dcl, cm_ram; } State;
typedef struct { Cycle c[2]; State fin; } Result;

typedef struct { State s; int rot; } Init;                     /* rot = extra JMS before set-up */
typedef struct { int st, op, arg, io; const char *why; } Test;

#define MAXSTATES 512
#define MAXTESTS 4096
static Init states[MAXSTATES];
static int n_states;
static Test tests[MAXTESTS];
static int n_tests;
static int order[MAXTESTS];        /* tests sorted by state */
static int nosnap;                 /* --nosnap: full reset + set-up for every test (check) */
#define N_RESET 3

/* ------------------------------------------------------------------------------------ */
/* rig (from sim/vectors.c, with bounded waits as in the pilot)                          */

static void rig_init(Rig *r, const char *netfile) {
    char names[32][16];
    int nodes[32], np;
    memset(r, 0, sizeof *r);
    r->chip = chip_load(netfile, names, nodes, &np);
    #define PAD(field, name) for (int i = 0; i < np; i++) if (!strcmp(names[i], name)) r->field = nodes[i];
    PAD(phi1, "PHI1") PAD(phi2, "PHI2") PAD(reset, "RESET") PAD(test, "TEST") PAD(sync, "SYNC")
    PAD(d[0], "D0") PAD(d[1], "D1") PAD(d[2], "D2") PAD(d[3], "D3")
    PAD(cm[0], "CMROM") PAD(cm[1], "CMRAM0") PAD(cm[2], "CMRAM1") PAD(cm[3], "CMRAM2") PAD(cm[4], "CMRAM3")
    #undef PAD
}

static void bus_drive(Rig *r, int nibble) {
    for (int i = 0; i < 4; i++) {
        if (nibble < 0) chip_release(r->chip, r->d[i]);
        else chip_drive(r->chip, r->d[i], (nibble >> i) & 1);
    }
}

static void monitors(Rig *r) {
    Chip *c = r->chip;
    if (r->n_mon) {
        r->mon_samples++;
        for (int i = 0; i < r->n_mon; i++)
            if (r->mon[i] >= 0 && !chip_driven(c, r->mon[i])) r->mon_float[i]++;
    }
    if (r->float_cnt) {
        chip_mark_driven(c, r->drv_all);
        r->float_samples++;
        for (int i = 0; i < c->n_nodes; i++) r->float_cnt[i] += !r->drv_all[i];
    }
    if (r->peek_mode) {
        int n = c->n_nodes;
        if (r->peek_mode == 1) {
            if (r->snap_pos + n > r->snap_cap) {
                r->snap_cap = (r->snap_cap + n) * 2;
                r->snap_buf = realloc(r->snap_buf, (size_t)r->snap_cap);
            }
            memcpy(r->snap_buf + r->snap_pos, c->state, (size_t)n);
        } else if (r->snap_pos + n <= r->snap_cap) {
            const unsigned char *g = r->snap_buf + r->snap_pos;
            r->diff_samples++;
            for (int i = 0; i < n; i++) r->diff_cnt[i] += g[i] != c->state[i];
        }
        r->snap_pos += n;
    }
    if (r->probe_on && r->slot >= 0) memcpy(r->probe_rec + (size_t)r->slot * c->n_nodes, c->state, (size_t)c->n_nodes);
}

static int rig_period(Rig *r, int next, Cycle *rec) {
    Chip *c = r->chip;
    chip_drive(c, r->phi1, 1); chip_settle(c);
    chip_drive(c, r->phi1, 0); chip_settle(c);
    chip_drive(c, r->phi2, 1); chip_settle(c);
    int sync = chip_read(c, r->sync);
    monitors(r);
    if (rec && r->slot >= 0) {
        int bus = 0, drv = 0, cm = 0;
        for (int i = 0; i < 4; i++) {
            bus |= chip_read(c, r->d[i]) << i;
            int ext = c->driven[r->d[i]];
            c->driven[r->d[i]] = 0;
            drv |= chip_driven(c, r->d[i]) << i;
            c->driven[r->d[i]] = (unsigned char)ext;
        }
        for (int i = 0; i < 5; i++) cm |= chip_read(c, r->cm[i]) << i;
        rec->bus[r->slot] = bus; rec->driven[r->slot] = drv; rec->cm[r->slot] = cm; rec->sync[r->slot] = sync;
    }
    chip_drive(c, r->phi2, 0); chip_settle(c);
    bus_drive(r, next);
    chip_settle(c);
    if (sync) r->slot = A1;
    else if (r->slot >= 0) r->slot = (r->slot + 1) & 7;
    return sync;
}

static void rig_cycle(Rig *r, int byte, int x2_in, Cycle *rec) {
    Cycle scratch;
    if (!rec) rec = &scratch;
    for (int s = 0; s < 8; s++) {
        int next = -1;
        if (s == A3) next = byte >> 4;
        else if (s == M1) next = byte & 15;
        else if (s == X1) next = x2_in;
        rig_period(r, next, rec);
    }
    rec->addr = rec->bus[A1] | (rec->bus[A2] << 4) | (rec->bus[A3] << 8);
}

static void rig_reset_for(Rig *r, int periods) {
    Chip *c = r->chip;
    chip_power_on(c);
    chip_drive(c, r->phi1, 0); chip_drive(c, r->phi2, 0);
    chip_drive(c, r->test, 0); chip_drive(c, r->reset, 1);
    chip_settle(c);
    r->slot = -1;
    for (int i = 0; i < periods; i++) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    int guard = 0;
    while (r->slot != X3 && guard++ < 64) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    if (r->slot != X3) { r->nosync = 1; r->slot = X3; }
    chip_drive(c, r->reset, 0); chip_settle(c);
    rig_period(r, -1, NULL);
}

static void feed2(Rig *r, int b1, int b2) { rig_cycle(r, b1, -1, NULL); rig_cycle(r, b2, -1, NULL); }

static void setup(Rig *r, const Init *in) {
    const State *s = &in->s;
    for (int i = 0; i < in->rot; i++) feed2(r, 0x50, 0x00);      /* move the stack pointer */
    rig_cycle(r, 0xD0 | s->dcl, -1, NULL);
    rig_cycle(r, 0xFD, -1, NULL);
    for (int p = 0; p < 8; p++) feed2(r, 0x20 | (p << 1), (s->r[2 * p] << 4) | s->r[2 * p + 1]);
    rig_cycle(r, s->cy ? 0xFA : 0xF1, -1, NULL);
    rig_cycle(r, 0xD0 | s->acc, -1, NULL);
    for (int i = 2; i >= 0; i--) {
        int from = (s->stack[i] - 2) & 0xFFF;
        feed2(r, 0x40 | (from >> 8), from & 0xFF);
        feed2(r, 0x50, 0x00);
    }
    feed2(r, 0x40 | (s->pc >> 8), s->pc & 0xFF);
    chip_drive(r->chip, r->test, s->test);
    chip_settle(r->chip);
}

/* Read the state back through the pins: WRR shows the accumulator at X2 (and the PC as its
 * address, the CM-RAM selection at M2); TCC + WRR the carry; SRC Pn shows register pair n at
 * X2/X3 (documented: that is the address it sends); three BBL pop the stack, the fetch after
 * each shows a return address. 17 instruction cycles. (The pilot read registers with LD + WRR,
 * 41 cycles; both are verified against the reference emulator by --verify.) */
static void readout(Rig *r, State *s) {
    Cycle c;
    memset(&c, 0, sizeof c);
    rig_cycle(r, 0xE2, -1, &c);
    s->pc = c.addr; s->acc = c.bus[X2]; s->cm_ram = c.cm[M2] >> 1;
    rig_cycle(r, 0xF7, -1, NULL);
    rig_cycle(r, 0xE2, -1, &c);
    s->cy = c.bus[X2];
    for (int p = 0; p < 8; p++) {
        rig_cycle(r, 0x21 | (p << 1), -1, &c);
        s->r[2 * p] = c.bus[X2]; s->r[2 * p + 1] = c.bus[X3];
    }
    for (int i = 0; i < 3; i++) {
        rig_cycle(r, 0xC0, -1, NULL);
        rig_cycle(r, 0x00, -1, &c);
        s->stack[i] = c.addr & 0xFFF;
    }
    s->test = chip_read(r->chip, r->test);
    s->dcl = -1;
}

static int two_cycle(int op) {
    int h = op >> 4;
    if (h == 1 || h == 4 || h == 5 || h == 7) return 1;
    if ((h == 2 || h == 3) && !(op & 1)) return 1;  /* FIM, FIN */
    return 0;
}
static int io_read(int op) { return (op >> 4) == 0xE && (op & 15) >= 8; }

/* ------------------------------------------------------------------------------------ */
/* the structured test set                                                               */

static int add_state(const State *s, int rot) {
    Init in;
    memset(&in, 0, sizeof in);
    in.s = *s; in.s.cm_ram = 0; in.rot = rot;
    for (int i = 0; i < n_states; i++) if (!memcmp(&states[i], &in, sizeof in)) return i;
    if (n_states == MAXSTATES) { fprintf(stderr, "too many states\n"); exit(2); }
    states[n_states] = in;
    return n_states++;
}

static void add_test(const State *s, int rot, int op, int arg, int io, const char *why) {
    if (n_tests == MAXTESTS) { fprintf(stderr, "too many tests\n"); exit(2); }
    tests[n_tests++] = (Test){add_state(s, rot), op, arg & 0xFF, io_read(op) ? (io & 15) : -1, why};
}

static void fill(State *s, int acc, int cy, int test, int dcl, int pc, int s0, int s1, int s2) {
    memset(s, 0, sizeof *s);
    s->acc = acc; s->cy = cy; s->test = test; s->dcl = dcl; s->pc = pc & 0xFFF;
    s->stack[0] = s0 & 0xFFF; s->stack[1] = s1 & 0xFFF; s->stack[2] = s2 & 0xFFF;
}

static void build_tests(void) {
    State b[6];
    int rot[6] = {0, 1, 2, 3, 0, 2}, arg[6] = {0x00, 0xFF, 0x55, 0xAA, 0x5A, 0xA5}, io[6] = {0, 15, 5, 10, 3, 12};
    /* base states: all-0, all-1, 0101, 1010 everywhere; then distinct register values */
    fill(&b[0], 0x0, 0, 0, 0, 0x000, 0x000, 0x000, 0x000);
    fill(&b[1], 0xF, 1, 1, 7, 0xFFF, 0xFFF, 0xFFF, 0xFFF);
    fill(&b[2], 0x5, 0, 1, 5, 0x555, 0x555, 0x555, 0x555);
    fill(&b[3], 0xA, 1, 0, 2, 0xAAA, 0xAAA, 0xAAA, 0xAAA);
    fill(&b[4], 0xA, 1, 0, 3, 0x7FE, 0x123, 0x456, 0x789);   /* page edge -2 */
    fill(&b[5], 0x5, 0, 1, 4, 0x8FF, 0xEDC, 0xBA9, 0x876);   /* page edge -1 */
    for (int i = 0; i < 16; i++) {
        b[0].r[i] = 0; b[1].r[i] = 15; b[2].r[i] = 5; b[3].r[i] = 10;
        b[4].r[i] = i; b[5].r[i] = 15 - i;
    }
    static const char *bw[6] = {"base all-0", "base all-1", "base 0101", "base 1010", "base distinct-up pc=xFE", "base distinct-down pc=xFF"};
    for (int op = 0; op < 256; op++)
        for (int k = 0; k < 6; k++) add_test(&b[k], rot[k], op, arg[k], io[k], bw[k]);

    State s;
    /* JCN: every condition input combination (acc zero?, carry, TEST), mid-page and page edge */
    for (int op = 0x10; op < 0x20; op++)
        for (int m = 0; m < 8; m++) {
            s = b[4];
            s.acc = (m & 1) ? 0 : 6; s.cy = (m >> 1) & 1; s.test = (m >> 2) & 1;
            s.pc = (m & 1) ? 0x3FE : 0x3A4;
            add_test(&s, m & 3, op, 0x69 ^ (m * 0x11), 0, "JCN condition matrix");
        }
    /* ISZ: register wraps (no jump) / does not, at a page edge and mid-page */
    for (int op = 0x70; op < 0x80; op++) {
        int rv[3] = {15, 14, 0}, pc[3] = {0x2FE, 0x2FE, 0x2A0};
        for (int k = 0; k < 3; k++) {
            s = b[4 + (k & 1)];
            s.r[op & 15] = rv[k]; s.pc = pc[k];
            add_test(&s, k, op, 0x3C, 0, "ISZ wrap/page edge");
        }
    }
    /* FIN/JIN: instruction in the last byte of a page */
    for (int op = 0x30; op < 0x40; op++)
        for (int k = 0; k < 2; k++) {
            s = b[4 + k]; s.pc = k ? 0x4FF : 0xBFF;
            add_test(&s, k + 1, op, 0xC3, 0, "FIN/JIN page end");
        }
    /* ALU carry patterns (acc, operand, carry in): no carry, full ripple, alternating bits */
    static const int alu[8][3] = {{0, 0, 1}, {15, 15, 0}, {5, 10, 1}, {10, 5, 0}, {5, 5, 1}, {10, 10, 0}, {15, 1, 0}, {0, 15, 1}};
    for (int op = 0x80; op < 0xA0; op++)
        for (int k = 0; k < 2; k++) {
            const int *a = alu[((op & 15) * 2 + k + (op >= 0x90)) & 7];
            s = b[4 + k];
            s.acc = a[0]; s.cy = a[2];
            for (int i = 0; i < 16; i++) s.r[i] = a[1];
            add_test(&s, k, op, 0, 0, "ADD/SUB carry pattern");
        }
    for (int k = 0; k < 8; k++) {
        s = b[4]; s.acc = alu[k][0]; s.cy = alu[k][2];
        add_test(&s, k & 3, 0xE8, 0, alu[k][1], "SBM carry pattern");
        add_test(&s, k & 3, 0xEB, 0, alu[k][1], "ADM carry pattern");
    }
    /* I/O reads: more input nibbles */
    for (int op = 0xE9; op <= 0xEF; op++) {
        if (op == 0xEB) continue;
        int in[3] = {6, 9, 1};
        for (int k = 0; k < 3; k++) { s = b[k + 1]; add_test(&s, k, op, 0, in[k], "I/O read nibble"); }
    }
    /* accumulator group: every acc value for KBP, DAA (both carries), DCL; four more for the rest */
    for (int v = 0; v < 16; v++) {
        s = b[4]; s.acc = v; s.cy = v & 1;
        add_test(&s, v & 3, 0xFC, 0, 0, "KBP every acc");
        add_test(&s, v & 3, 0xFD, 0, 0, "DCL every acc");
        for (int cy = 0; cy < 2; cy++) { s.cy = cy; add_test(&s, v & 3, 0xFB, 0, 0, "DAA every acc x carry"); }
    }
    for (int op = 0xF0; op <= 0xFA; op++) {
        int av[4] = {7, 8, 3, 12};
        for (int k = 0; k < 4; k++) {
            s = b[4 + (k & 1)]; s.acc = av[k]; s.cy = k >> 1;
            add_test(&s, k, op, 0, 0, "acc group values");
        }
    }
    /* stack depth: JMS and BBL with the stack pointer in every position */
    for (int op = 0x50; op < 0x60; op++)
        for (int k = 0; k < 2; k++) { s = b[4 + k]; add_test(&s, 2 * k + 1, op, 0x96, 0, "JMS stack depth"); }
    for (int op = 0xC0; op < 0xD0; op++)
        for (int k = 0; k < 4; k++) { s = b[4 + (k & 1)]; add_test(&s, k, op, 0, 0, "BBL stack depth"); }

    /* group tests by initial state */
    int n = 0;
    for (int st = 0; st < n_states; st++)
        for (int t = 0; t < n_tests; t++) if (tests[t].st == st) order[n++] = t;
}

/* reset tests: three loaded states, RESET held 64 periods, read back */
static void reset_state(int k, State *s) {
    memset(s, 0, sizeof *s);
    s->acc = 15; s->cy = 1; s->dcl = 7; s->pc = 0xABC; s->test = 1;
    for (int i = 0; i < 16; i++) s->r[i] = 15 - (i % 3);
    s->stack[0] = 0x123; s->stack[1] = 0x456; s->stack[2] = 0x789;
    if (k == 1) { s->acc = 15; s->pc = 0xFFF; for (int i = 0; i < 16; i++) s->r[i] = 15; s->stack[0] = s->stack[1] = s->stack[2] = 0xFFF; }
    if (k == 2) { s->acc = 5; s->cy = 0; s->dcl = 5; s->pc = 0x555; for (int i = 0; i < 16; i++) s->r[i] = (i & 1) ? 5 : 10; s->stack[0] = 0xAAA; s->stack[1] = 0x555; s->stack[2] = 0xAAA; }
}

static void reset_test(Rig *r, int k, State *out) {
    Init in;
    memset(&in, 0, sizeof in);
    reset_state(k, &in.s);
    in.rot = k;
    rig_reset_for(r, 96);
    setup(r, &in);
    chip_drive(r->chip, r->test, 0);
    chip_drive(r->chip, r->reset, 1); chip_settle(r->chip);
    for (int i = 0; i < 64; i++) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    chip_drive(r->chip, r->reset, 0); chip_settle(r->chip);
    int guard = 0;
    while (r->slot != A1 && guard++ < 16) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    readout(r, out);
}

/* ------------------------------------------------------------------------------------ */
/* running the set                                                                       */

typedef struct { unsigned char *state, *on, *driven; int slot, nosync; } Snap;

static void snap_take(Rig *r, Snap *s) {
    Chip *c = r->chip;
    if (!s->state) { s->state = malloc(c->n_nodes); s->driven = malloc(c->n_nodes); s->on = malloc(c->n_trans); }
    memcpy(s->state, c->state, c->n_nodes); memcpy(s->driven, c->driven, c->n_nodes);
    memcpy(s->on, c->on, c->n_trans);
    s->slot = r->slot; s->nosync = r->nosync;
}

static void snap_restore(Rig *r, const Snap *s) {
    Chip *c = r->chip;
    memcpy(c->state, s->state, c->n_nodes); memcpy(c->driven, s->driven, c->n_nodes);
    memcpy(c->on, s->on, c->n_trans);
    r->slot = s->slot; r->nosync = s->nosync;
}

static void run_instr(Rig *r, const Test *t, Result *res) {
    memset(res, 0, sizeof *res);
    rig_cycle(r, t->op, t->io, &res->c[0]);
    if (two_cycle(t->op)) rig_cycle(r, t->arg, -1, &res->c[1]);
    readout(r, &res->fin);
}

static Result golden[MAXTESTS];
static State golden_reset[N_RESET];

static int compare(const Test *t, const Result *a, const Result *g) {
    int k = 0;
    const State *x = &a->fin, *y = &g->fin;
    if (x->acc != y->acc) k |= K_ACC;
    if (x->cy != y->cy) k |= K_CY;
    if (memcmp(x->r, y->r, sizeof x->r)) k |= K_REG;
    if (x->pc != y->pc) k |= K_PC;
    if (memcmp(x->stack, y->stack, sizeof x->stack)) k |= K_STACK;
    if (x->cm_ram != y->cm_ram) k |= K_CMRAM;
    int op = t->op, src = (op >> 4) == 2 && (op & 1), iow = (op >> 4) == 0xE && (op & 15) < 8;
    for (int cyc = 0; cyc < 1 + two_cycle(op); cyc++) {
        const Cycle *p = &a->c[cyc], *q = &g->c[cyc];
        for (int sl = 0; sl < 8; sl++) {
            if (p->bus[sl] != q->bus[sl]) {
                if (sl <= A3) k |= K_ADDR;
                else if (sl <= M2) k |= K_MBUS;
                else if (sl == X1) k |= K_X1;
                else if (cyc == 0 && (src || (iow && sl == X2))) k |= K_XDOC;
                else k |= K_XUND;
            }
            if (p->driven[sl] != q->driven[sl]) k |= K_DRV;
            if (p->cm[sl] != q->cm[sl]) k |= K_CM;
            if (p->sync[sl] != q->sync[sl]) k |= K_SYNC;
        }
    }
    return k;
}

/* Run the whole set on r. If kinds != NULL compare with golden[] and store kind masks;
 * else store into golden[]. If twin != NULL (peek mode) the twin (intact chip) runs each
 * piece first in record mode and r compares against it. */
static void run_set(Rig *r, unsigned short *kinds, int *reset_mask, Rig *twin) {
    static Snap snap, tsnap;
    Chip *c = r->chip;
    int cur = -1;
    for (int i = 0; i < n_tests; i++) {
        const Test *t = &tests[order[i]];
        if (t->st != cur || nosnap) {
            cur = t->st;
            if (twin) { twin->peek_mode = 1; twin->snap_pos = 0; rig_reset_for(twin, 96); setup(twin, &states[cur]); snap_take(twin, &tsnap);
                        twin->peek_mode = 0; r->snap_buf = twin->snap_buf; r->snap_cap = twin->snap_pos; r->snap_pos = 0; r->peek_mode = 2; }
            r->nosync = 0;
            rig_reset_for(r, 96);
            setup(r, &states[cur]);
            snap_take(r, &snap);
        }
        int u0 = c->unstable;
        Result res;
        if (twin) { snap_restore(twin, &tsnap); twin->peek_mode = 1; twin->snap_pos = 0; Result tr; run_instr(twin, t, &tr);
                    twin->peek_mode = 0; r->snap_buf = twin->snap_buf; r->snap_cap = twin->snap_pos; r->snap_pos = 0; }
        snap_restore(r, &snap);
        run_instr(r, t, &res);
        if (kinds) {
            int k = compare(t, &res, &golden[order[i]]);
            if (r->nosync) k |= K_NOSYNC;
            if (c->unstable != u0) k |= K_UNST;
            kinds[order[i]] = (unsigned short)k;
        } else golden[order[i]] = res;
    }
    if (twin) { r->peek_mode = 0; }
    for (int k = 0; k < N_RESET; k++) {
        State f;
        r->nosync = 0;
        reset_test(r, k, &f);
        if (reset_mask) { if (memcmp(&f, &golden_reset[k], sizeof f)) *reset_mask |= 1 << k; }
        else golden_reset[k] = f;
    }
}

/* ------------------------------------------------------------------------------------ */

static int parse_lesion(const char *s, int *t, int *mode) {
    char m = 0;
    if (sscanf(s, "%d%c", t, &m) != 2 || (m != 'o' && m != 'c')) return 0;
    *mode = m == 'c';
    return 1;
}

static void run_lesion(Rig *r, int t, int mode) {
    Chip *c = r->chip;
    static unsigned short kinds[MAXTESTS];
    clock_t t0 = clock();
    c->force[t] = (signed char)mode;
    c->lesion = t;
    c->unstable = 0; c->contention = 0;
    Transistor *q = &c->tr[t];
    int nodes[3] = {q->gate, q->a, q->b};
    r->n_mon = 3;
    for (int i = 0; i < 3; i++) {
        r->mon[i] = (nodes[i] == c->vss || nodes[i] == c->vdd) ? -1 : nodes[i];
        r->mon_float[i] = 0;
    }
    r->mon_samples = 0;
    int rmask = 0;
    run_set(r, kinds, &rmask, NULL);
    int nfail = 0, nbad = 0;
    unsigned char bad[256] = {0};
    for (int i = 0; i < n_tests; i++) if (kinds[i]) { nfail++; bad[tests[i].op] = 1; }
    for (int i = 0; i < 256; i++) nbad += bad[i];
    int nosync = 0;
    for (int i = 0; i < n_tests; i++) nosync |= (kinds[i] & K_NOSYNC) != 0;
    printf("%d %c %d %d %d %d %d %ld", t, mode ? 'c' : 'o', nfail, nbad, rmask, nosync, c->unstable, c->contention);
    for (int i = 0; i < 3; i++) printf(" %ld", r->mon[i] < 0 ? -1L : r->mon_float[i]);
    printf(" %ld %ld ", r->mon_samples, (long)((clock() - t0) * 1000 / CLOCKS_PER_SEC));
    for (int i = 0; i < n_tests; i++) printf("%04x", kinds[i]);
    printf("\n");
    fflush(stdout);
    c->force[t] = -1;
    c->lesion = -1;
    r->n_mon = 0;
}

/* --peek: lockstep against an intact twin; per node, how many samples differ */
static void peek_lesion(Rig *r, Rig *twin, int t, int mode) {
    Chip *c = r->chip;
    static unsigned short kinds[MAXTESTS];
    c->force[t] = (signed char)mode;
    c->lesion = t;
    if (!r->diff_cnt) r->diff_cnt = calloc(c->n_nodes, sizeof(long));
    memset(r->diff_cnt, 0, c->n_nodes * sizeof(long));
    r->diff_samples = 0;
    int rmask = 0;
    run_set(r, kinds, &rmask, twin);
    int nfail = 0, ndiff = 0;
    for (int i = 0; i < n_tests; i++) nfail += kinds[i] != 0;
    for (int i = 0; i < c->n_nodes; i++) ndiff += r->diff_cnt[i] > 0;
    printf("%d %c nfail=%d reset=%d samples=%ld nodes_differing=%d", t, mode ? 'c' : 'o', nfail, rmask, r->diff_samples, ndiff);
    for (int i = 0; i < c->n_nodes; i++) if (r->diff_cnt[i]) printf(" %d:%ld", i, r->diff_cnt[i]);
    printf("\n");
    fflush(stdout);
    c->force[t] = -1;
    c->lesion = -1;
}

/* --fuzz: random programs (random state, 24 random instructions, random TEST and I/O
 * inputs), all pin samples of every cycle and the final state compared with the twin. */
static unsigned long long rng_state;
static unsigned rnd(unsigned n) {
    rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17;
    return (unsigned)((rng_state >> 11) % n);
}

static void random_state(State *s) {
    s->acc = (int)rnd(16); s->cy = (int)rnd(2); s->test = (int)rnd(2); s->dcl = (int)rnd(8);
    for (int i = 0; i < 16; i++) s->r[i] = (int)rnd(16);
    s->pc = (int)rnd(4096);
    if (rnd(4) == 0) s->pc = (s->pc & 0xF00) | (0xFC + (int)rnd(4));
    for (int i = 0; i < 3; i++) s->stack[i] = (int)rnd(4096);
    s->cm_ram = 0;
}

#define FUZZ_LEN 24
typedef struct { Init in; int bytes[2 * FUZZ_LEN + 1], io[2 * FUZZ_LEN + 1], test[2 * FUZZ_LEN + 1], n; } Prog;

static void make_prog(Prog *p, unsigned long long seed) {
    rng_state = seed * 0x9E3779B97F4A7C15ULL + 12345;
    memset(p, 0, sizeof *p);
    random_state(&p->in.s);
    p->in.rot = (int)rnd(4);
    p->n = 0;
    for (int i = 0; i < FUZZ_LEN; i++) {
        int op = (int)rnd(256);
        p->test[p->n] = (int)rnd(2);
        p->io[p->n] = io_read(op) ? (int)rnd(16) : -1;
        p->bytes[p->n++] = op;
        if (two_cycle(op)) { p->test[p->n] = (int)rnd(2); p->io[p->n] = -1; p->bytes[p->n++] = (int)rnd(256); }
    }
}

static int run_prog(Rig *r, const Prog *p, Cycle *rec, State *fin) {
    rig_reset_for(r, 96);
    setup(r, &p->in);
    for (int i = 0; i < p->n; i++) {
        chip_drive(r->chip, r->test, p->test[i]); chip_settle(r->chip);
        memset(&rec[i], 0, sizeof rec[i]);
        rig_cycle(r, p->bytes[i], p->io[i], &rec[i]);
    }
    readout(r, fin);
    return p->n;
}

static int prog_differs(Rig *r, Rig *twin, const Prog *p, int t, int mode) {
    Cycle a[2 * FUZZ_LEN + 1], g[2 * FUZZ_LEN + 1];
    State fa, fg;
    int n = run_prog(twin, p, g, &fg);
    r->chip->force[t] = (signed char)mode;
    run_prog(r, p, a, &fa);
    r->chip->force[t] = -1;
    int diff = memcmp(&fa, &fg, sizeof fa) != 0;
    for (int i = 0; i < n && !diff; i++) diff = memcmp(&a[i], &g[i], sizeof a[i]) != 0;
    return diff;
}

/* Shrink a catching program: drop whole instructions (and then simplify the state) as long
 * as the lesion is still detected. Prints the result as a readable test. */
static void minimise(Rig *r, Rig *twin, Prog *p, int t, int mode) {
    int changed = 1;
    while (changed) {
        changed = 0;
        for (int i = 0; i < p->n; ) {
            int len = (i + 1 < p->n && two_cycle(p->bytes[i])) ? 2 : 1;
            Prog q = *p;
            memmove(&q.bytes[i], &q.bytes[i + len], (size_t)(q.n - i - len) * sizeof(int));
            memmove(&q.io[i], &q.io[i + len], (size_t)(q.n - i - len) * sizeof(int));
            memmove(&q.test[i], &q.test[i + len], (size_t)(q.n - i - len) * sizeof(int));
            q.n -= len;
            if (prog_differs(r, twin, &q, t, mode)) { *p = q; changed = 1; } else i += len;
        }
    }
    printf("   minimal test: state acc=%X cy=%d dcl=%d pc=%03X stack=%03X,%03X,%03X rot=%d r=",
           p->in.s.acc, p->in.s.cy, p->in.s.dcl, p->in.s.pc, p->in.s.stack[0], p->in.s.stack[1], p->in.s.stack[2], p->in.rot);
    for (int k = 0; k < 16; k++) printf("%X", p->in.s.r[k]);
    printf(" ; program:");
    for (int i = 0; i < p->n; i++) {
        printf(" %02X", p->bytes[i]);
        if (p->io[i] >= 0) printf("(in=%X)", p->io[i]);
        printf("[T%d]", p->test[i]);
    }
    printf("\n");
}

static void fuzz_lesion(Rig *r, Rig *twin, int t, int mode, int nprog, int do_min) {
    int caught = 0, first = -1;
    Prog firstp;
    for (int k = 0; k < nprog; k++) {
        Prog p;
        make_prog(&p, (unsigned long long)k + 1);
        if (prog_differs(r, twin, &p, t, mode)) { if (first < 0) { first = k; firstp = p; } caught++; }
    }
    printf("%d %c fuzz=%d caught=%d first=%d\n", t, mode ? 'c' : 'o', nprog, caught, first);
    if (do_min && first >= 0) minimise(r, twin, &firstp, t, mode);
    fflush(stdout);
}

/* --verify: intact chip vs the instruction-level reference emulator */
static int verify(void) {
    static const int lines[8] = {1, 2, 4, 6, 8, 10, 12, 14};
    static Mcs4 mem;
    int bad = 0;
    for (int i = 0; i < n_tests; i++) {
        const Test *t = &tests[i];
        const State *s = &states[t->st].s;
        Ref4004 ref;
        mcs4_init(&mem);
        memset(mem.rom, t->arg, sizeof mem.rom);
        mem.rom[s->pc] = (unsigned char)t->op;
        /* the rig feeds the second byte whatever the address: FIN's table read may hit the
         * opcode's own address (e.g. R0R1 = 55 at PC 555); then the fed byte is what counts */
        int fin_self = 0;
        if ((t->op & 0xF1) == 0x30) {
            int a = ((s->pc + 1) & 0xF00) | (s->r[0] << 4) | s->r[1];
            if (a == s->pc) fin_self = 1; else mem.rom[a] = (unsigned char)t->arg;
        }
        if (t->io >= 0) {
            memset(mem.ram, t->io, sizeof mem.ram); memset(mem.status, t->io, sizeof mem.status);
            memset(mem.rom_in, t->io, sizeof mem.rom_in);
        }
        ref_reset(&ref, &mem);
        ref.acc = s->acc; ref.cy = s->cy; memcpy(ref.r, s->r, sizeof ref.r);
        ref.sp = 3; ref.stack[3] = s->pc; ref.stack[2] = s->stack[0]; ref.stack[1] = s->stack[1]; ref.stack[0] = s->stack[2];
        ref.cm_ram = lines[s->dcl] << 1; ref.test = s->test;
        ref_step(&ref);
        if (fin_self) { ref.r[t->op & 0xE] = t->arg >> 4; ref.r[(t->op & 0xE) + 1] = t->arg & 15; }
        const State *g = &golden[i].fin;
        int ok = g->acc == ref.acc && g->cy == ref.cy && !memcmp(g->r, ref.r, sizeof ref.r) &&
                 g->pc == ref.stack[ref.sp] && g->cm_ram == ref.cm_ram >> 1 &&
                 g->stack[0] == ref.stack[(ref.sp - 1) & 3] && g->stack[1] == ref.stack[(ref.sp - 2) & 3];
        /* the third readout pop reaches the row that held the PC before a BBL: the bottom
         * entry is not architecturally defined after BBL (vectors/README.md, Limits) */
        if ((t->op >> 4) != 0xC) ok = ok && g->stack[2] == ref.stack[(ref.sp - 3) & 3];
        if (!ok) {
            bad++;
            if (bad <= 10)
                printf("MISMATCH test %d op %02X (%s): chip pc=%03X acc=%X cy=%d st=%03X,%03X,%03X cm=%d  ref pc=%03X acc=%X cy=%d st=%03X,%03X,%03X cm=%d\n",
                       i, t->op, t->why, g->pc, g->acc, g->cy, g->stack[0], g->stack[1], g->stack[2], g->cm_ram,
                       ref.stack[ref.sp], ref.acc, ref.cy, ref.stack[(ref.sp - 1) & 3], ref.stack[(ref.sp - 2) & 3],
                       ref.stack[(ref.sp - 3) & 3], ref.cm_ram >> 1);
        }
    }
    /* reset tests: everything cleared (PC may already be 0 or 1, as in vectors.c --reset-time) */
    for (int k = 0; k < N_RESET; k++) {
        const State *f = &golden_reset[k];
        int regs = 0;
        for (int i = 0; i < 16; i++) regs += f->r[i] != 0;
        int clean = f->pc <= 1 && f->acc == 0 && f->cy == 0 && regs == 0 && f->cm_ram == 1 &&
                    f->stack[0] == 0 && f->stack[1] == 0 && f->stack[2] == 0;
        printf("reset test %d: pc=%03X acc=%X cy=%d cm_ram=%d stack=%03X,%03X,%03X regs-set=%d -> %s\n", k, f->pc, f->acc,
               f->cy, f->cm_ram, f->stack[0], f->stack[1], f->stack[2], regs, clean ? "clean" : "NOT CLEAN");
        bad += !clean;
    }
    printf("%d tests + %d reset tests checked against the reference emulator: %d mismatches\n", n_tests, N_RESET, bad);
    return bad != 0;
}

int main(int argc, char **argv) {
    const char *net = "netlist/4004.net", *list = NULL, *probe = NULL;
    int do_min = 0, probe_random = 0, mode_list = 0, mode_verify = 0, mode_peek = 0, mode_float = 0, fuzz = 0, first = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--net") && i + 1 < argc) net = argv[++i];
        else if (!strcmp(argv[i], "--list-tests")) mode_list = 1;
        else if (!strcmp(argv[i], "--verify")) mode_verify = 1;
        else if (!strcmp(argv[i], "--nosnap")) nosnap = 1;
        else if (!strcmp(argv[i], "--minimise")) do_min = 1;
        else if (!strcmp(argv[i], "--peek")) mode_peek = 1;
        else if (!strcmp(argv[i], "--floatprof")) mode_float = 1;
        else if (!strcmp(argv[i], "--fuzz") && i + 1 < argc) fuzz = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--probe") && i + 1 < argc) probe = argv[++i];
        else if (!strcmp(argv[i], "--probe-random") && i + 1 < argc) probe_random = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--all-from") && i + 1 < argc) list = argv[++i];
        else { first = i; break; }
    }
    build_tests();
    if (mode_list) {
        printf("# idx op arg io state rot acc cy test dcl pc stack0 stack1 stack2 r0..r15 why\n");
        for (int i = 0; i < n_tests; i++) {
            const Test *t = &tests[i];
            const Init *in = &states[t->st];
            const State *s = &in->s;
            printf("%d %02X %02X %d %d %d %X %d %d %d %03X %03X %03X %03X ", i, t->op, t->arg, t->io, t->st, in->rot,
                   s->acc, s->cy, s->test, s->dcl, s->pc, s->stack[0], s->stack[1], s->stack[2]);
            for (int k = 0; k < 16; k++) printf("%X", s->r[k]);
            printf(" %s\n", t->why);
        }
        fprintf(stderr, "%d tests, %d distinct initial states, %d reset tests\n", n_tests, n_states, N_RESET);
        return 0;
    }
    static Rig rig, twin;
    rig_init(&rig, net);
    clock_t t0 = clock();
    if (probe) {
        /* Node states at phi2 of each of the 8 slots of the instruction's first cycle, per test:
         * the structured tests, then `probe_random` NOP tests from random states (to tell
         * register cells apart). Record: int32 idx, op, rot, acc, cy, test, dcl, pc, stack[3],
         * r[16] (28 int32), then 8 x n_nodes bytes. */
        FILE *f = fopen(probe, "wb");
        Chip *c = rig.chip;
        rig.probe_rec = calloc(8, c->n_nodes);
        static Snap snap;
        int cur = -1;
        for (int i = 0; i < n_tests + probe_random; i++) {
            Test tt, *t = &tt;
            Init in;
            int idx;
            if (i < n_tests) { idx = order[i]; tt = tests[idx]; in = states[tt.st]; }
            else {
                idx = 100000 + i - n_tests;
                rng_state = 777 + (unsigned long long)idx * 0x9E3779B97F4A7C15ULL;
                memset(&in, 0, sizeof in);
                random_state(&in.s); in.rot = (int)rnd(4);
                tt = (Test){-1, 0x00, 0, -1, "probe random"};
            }
            if (i >= n_tests || t->st != cur) {
                cur = i < n_tests ? t->st : -1;
                rig_reset_for(&rig, 96); setup(&rig, &in); snap_take(&rig, &snap);
            }
            snap_restore(&rig, &snap);
            Result res;
            rig.probe_on = 1;
            rig_cycle(&rig, t->op, t->io, &res.c[0]);
            rig.probe_on = 0;
            int hdr[28] = {idx, t->op, in.rot, in.s.acc, in.s.cy, in.s.test, in.s.dcl, in.s.pc,
                           in.s.stack[0], in.s.stack[1], in.s.stack[2]};
            for (int k = 0; k < 16; k++) hdr[11 + k] = in.s.r[k];
            hdr[27] = t->io;
            fwrite(hdr, sizeof hdr, 1, f);
            fwrite(rig.probe_rec, 1, (size_t)8 * c->n_nodes, f);
        }
        fclose(f);
        fprintf(stderr, "probe: %d tests x 8 slots x %d nodes written to %s\n", n_tests + probe_random, c->n_nodes, probe);
        return 0;
    }
    if (mode_float) {
        Chip *c = rig.chip;
        rig.drv_all = malloc(c->n_nodes);
        rig.float_cnt = calloc(c->n_nodes, sizeof(long));
    }
    if (!fuzz) run_set(&rig, NULL, NULL, NULL);
    if (!fuzz) fprintf(stderr, "golden: %d tests + %d reset tests, %.2f s cpu, unstable=%d nosync=%d\n", n_tests, N_RESET,
            (double)(clock() - t0) / CLOCKS_PER_SEC, rig.chip->unstable, rig.nosync);
    if (mode_float) {
        for (int i = 0; i < rig.chip->n_nodes; i++) printf("%d %ld %ld\n", i, rig.float_cnt[i], rig.float_samples);
        return 0;
    }
    if (mode_verify) return verify();
    if (mode_peek || fuzz) rig_init(&twin, net);

    int t, m;
    #define DO(t, m) do { if (mode_peek) peek_lesion(&rig, &twin, t, m); else if (fuzz) fuzz_lesion(&rig, &twin, t, m, fuzz, do_min); else run_lesion(&rig, t, m); } while (0)
    if (list) {
        FILE *f = fopen(list, "r");
        if (!f) { perror(list); return 1; }
        char buf[64];
        while (fscanf(f, "%63s", buf) == 1) if (parse_lesion(buf, &t, &m)) DO(t, m);
        fclose(f);
    }
    for (int i = first; first && i < argc; i++) if (parse_lesion(argv[i], &t, &m)) DO(t, m);
    return 0;
}
