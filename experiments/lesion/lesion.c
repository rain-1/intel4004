/* lesion: transistor lesion study on the switch-level 4004.
 *
 * Rig code adapted from sim/vectors.c (scripted bus, state set up and read back through
 * the pins only). For every lesion (one transistor forced stuck open or stuck closed) it
 * replays K single-instruction tests per opcode -- the same tests as the first K of each
 * vectors/v1/XX.json.gz file (same RNG stream) -- plus a reset test, and compares every
 * recorded pin sample and the read-back final state with the intact chip.
 *
 *   lesion [--net FILE] [--k K] --golden            JSON lines for the intact chip (check vs v1)
 *   lesion [--net FILE] [--k K] T[o|c] ...          one result line per lesion, e.g. 17o 17c
 *   lesion [--net FILE] [--k K] --all-from FILE     lesions listed one per line in FILE
 *
 * Output line: T mode n_bad_opcodes reset_bad nosync unstable bitmap(64 hex, bit op = opcode
 * op failed) cyclemask(64 hex: bus/pin mismatch) statemask(64 hex: final state mismatch)
 */
#include "lesionsim.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { A1, A2, A3, M1, M2, X1, X2, X3 };
#define MAXK 16

typedef struct {
    Chip *chip;
    int phi1, phi2, reset, test, sync, d[4], cm[5];
    int slot;
    int nosync;
} Rig;

typedef struct { int addr; int bus[8], driven[8], cm[8], sync[8]; } Cycle;
typedef struct { int acc, cy, r[16], pc, stack[3], test, dcl, cm_ram; } State;
typedef struct { Cycle c[2]; State fin; } Result;

static unsigned long long rng_state;
static unsigned rnd(unsigned n) {
    rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17;
    return (unsigned)((rng_state >> 11) % n);
}

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

static int rig_period(Rig *r, int next, Cycle *rec) {
    Chip *c = r->chip;
    chip_drive(c, r->phi1, 1); chip_settle(c);
    chip_drive(c, r->phi1, 0); chip_settle(c);
    chip_drive(c, r->phi2, 1); chip_settle(c);
    int sync = chip_read(c, r->sync);
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

/* Like vectors.c, but gives up waiting for SYNC (a lesion can kill it). */
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

static void setup(Rig *r, const State *s) {
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

static void readout(Rig *r, State *s) {
    Cycle c;
    memset(&c, 0, sizeof c);
    rig_cycle(r, 0xE2, -1, &c);
    s->pc = c.addr; s->acc = c.bus[X2]; s->cm_ram = c.cm[M2] >> 1;
    rig_cycle(r, 0xF7, -1, NULL);
    rig_cycle(r, 0xE2, -1, &c);
    s->cy = c.bus[X2];
    for (int i = 0; i < 16; i++) {
        rig_cycle(r, 0xA0 | i, -1, NULL);
        rig_cycle(r, 0xE2, -1, &c);
        s->r[i] = c.bus[X2];
    }
    for (int i = 0; i < 3; i++) {
        rig_cycle(r, 0xC0, -1, NULL);
        rig_cycle(r, 0x00, -1, &c);
        s->stack[i] = c.addr & 0xFFF;
    }
    s->test = chip_read(r->chip, r->test);
    s->dcl = -1;
}

static void random_state(State *s) {
    s->acc = (int)rnd(16); s->cy = (int)rnd(2); s->test = (int)rnd(2); s->dcl = (int)rnd(8);
    for (int i = 0; i < 16; i++) s->r[i] = (int)rnd(16);
    s->pc = (int)rnd(4096);
    if (rnd(4) == 0) s->pc = (s->pc & 0xF00) | (0xFC + (int)rnd(4));
    for (int i = 0; i < 3; i++) s->stack[i] = (int)rnd(4096);
    s->cm_ram = 0;
}

/* Intact-chip instruction lengths (from vectors/v1): two-cycle opcodes. */
static int two_cycle(int op) {
    int h = op >> 4;
    if (h == 1 || h == 4 || h == 5 || h == 7) return 1;
    if ((h == 2 || h == 3) && !(op & 1)) return 1;  /* FIM, FIN */
    return 0;
}

/* Run test n of opcode op (the RNG is already positioned). */
static void run_test(Rig *r, int op, Result *res, State *init_out, int *arg_out, int *io_out) {
    int io_read = (op >> 4) == 0xE && (op & 15) >= 8;
    State init;
    memset(res, 0, sizeof *res);
    memset(&init, 0, sizeof init);
    random_state(&init);
    int arg = (int)rnd(256), io_in = io_read ? (int)rnd(16) : -1;
    rig_reset_for(r, 96);
    setup(r, &init);
    rig_cycle(r, op, io_in, &res->c[0]);
    if (two_cycle(op)) rig_cycle(r, arg, -1, &res->c[1]);
    readout(r, &res->fin);
    if (init_out) *init_out = init;
    if (arg_out) *arg_out = arg;
    if (io_out) *io_out = io_in;
}

static void seed_for(int op) {
    rng_state = 88172645463325252ULL;
    rng_state ^= (unsigned long long)(op + 1) * 0x9E3779B97F4A7C15ULL;
    State dummy;
    for (int i = 0; i < 6; i++) random_state(&dummy);   /* what opcode_cycles() consumed */
}

/* Reset test: load a full state, hold RESET 64 periods, read back. */
static void reset_test(Rig *r, Result *res) {
    State s;
    memset(res, 0, sizeof *res);
    memset(&s, 0, sizeof s);
    rng_state = 12345;
    random_state(&s);
    s.acc = 15; s.cy = 1; s.dcl = 7; s.pc = 0xABC;
    for (int i = 0; i < 16; i++) s.r[i] = 15 - (i % 3);
    s.stack[0] = 0x123; s.stack[1] = 0x456; s.stack[2] = 0x789;
    rig_reset_for(r, 96);
    setup(r, &s);
    chip_drive(r->chip, r->test, 0);
    chip_drive(r->chip, r->reset, 1); chip_settle(r->chip);
    for (int i = 0; i < 64; i++) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    chip_drive(r->chip, r->reset, 0); chip_settle(r->chip);
    int guard = 0;
    while (r->slot != A1 && guard++ < 16) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    readout(r, &res->fin);
}

static int K = 2;
static Result golden[256][MAXK], golden_reset;

static void print_golden(int op, int n, const State *s, int arg, int io, const Result *g) {
    printf("{\"op\":%d,\"n\":%d,\"pc\":%d,\"acc\":%d,\"arg\":%d,\"io\":%d,\"final\":{\"pc\":%d,\"acc\":%d,\"cy\":%d,\"r\":[",
           op, n, s->pc, s->acc, arg, io, g->fin.pc, g->fin.acc, g->fin.cy);
    for (int i = 0; i < 16; i++) printf("%d%s", g->fin.r[i], i < 15 ? "," : "");
    printf("],\"stack\":[%d,%d,%d],\"cm_ram\":%d},\"bus\":[", g->fin.stack[0], g->fin.stack[1], g->fin.stack[2], g->fin.cm_ram);
    for (int c = 0; c < 1 + two_cycle(op); c++)
        for (int i = 0; i < 8; i++) printf("%s%d", (c || i) ? "," : "", g->c[c].bus[i]);
    printf("]}\n");
}

static void hex256(const unsigned char *bits) {
    for (int i = 63; i >= 0; i--) {
        int v = 0;
        for (int b = 0; b < 4; b++) v |= bits[i * 4 + b] << b;
        printf("%x", v);
    }
}

static void run_lesion(Rig *r, int t, int mode) {
    Chip *c = r->chip;
    unsigned char bad[256] = {0}, cyc[256] = {0}, st[256] = {0};
    if (t >= 0) c->force[t] = (signed char)mode;
    c->unstable = 0;
    r->nosync = 0;
    int nbad = 0;
    for (int op = 0; op < 256; op++) {
        seed_for(op);
        for (int n = 0; n < K; n++) {
            Result res;
            run_test(r, op, &res, NULL, NULL, NULL);
            int cm = memcmp(res.c, golden[op][n].c, sizeof res.c) != 0;
            int sm = memcmp(&res.fin, &golden[op][n].fin, sizeof res.fin) != 0;
            cyc[op] |= cm; st[op] |= sm; bad[op] |= cm | sm;
        }
        nbad += bad[op];
    }
    Result rr;
    reset_test(r, &rr);
    int rbad = memcmp(&rr.fin, &golden_reset.fin, sizeof rr.fin) != 0;
    printf("%d %c %d %d %d %d ", t, mode ? 'c' : 'o', nbad, rbad, r->nosync, c->unstable);
    hex256(bad); printf(" "); hex256(cyc); printf(" "); hex256(st); printf("\n");
    fflush(stdout);
    if (t >= 0) c->force[t] = -1;
}

int main(int argc, char **argv) {
    const char *net = "netlist/4004.net", *list = NULL;
    int dump = 0, first = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--net") && i + 1 < argc) net = argv[++i];
        else if (!strcmp(argv[i], "--k") && i + 1 < argc) K = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--golden")) dump = 1;
        else if (!strcmp(argv[i], "--all-from") && i + 1 < argc) list = argv[++i];
        else { first = i; break; }
    }
    if (K < 1 || K > MAXK) { fprintf(stderr, "bad --k\n"); return 2; }
    static Rig rig;
    rig_init(&rig, net);
    clock_t t0 = clock();
    for (int op = 0; op < 256; op++) {
        seed_for(op);
        for (int n = 0; n < K; n++) {
            State s; int arg, io;
            run_test(&rig, op, &golden[op][n], &s, &arg, &io);
            if (dump) print_golden(op, n, &s, arg, io, &golden[op][n]);
        }
    }
    reset_test(&rig, &golden_reset);
    fprintf(stderr, "golden: %.2f s cpu, unstable=%d nosync=%d\n", (double)(clock() - t0) / CLOCKS_PER_SEC,
            rig.chip->unstable, rig.nosync);
    if (dump) return 0;
    if (list) {
        FILE *f = fopen(list, "r");
        if (!f) { perror(list); return 1; }
        int t; char m;
        while (fscanf(f, "%d%c", &t, &m) == 2) run_lesion(&rig, t, m == 'c');
        fclose(f);
    }
    for (int i = first; first && i < argc; i++) {
        int t = atoi(argv[i]);
        char m = argv[i][strlen(argv[i]) - 1];
        run_lesion(&rig, t, m == 'c');
    }
    return 0;
}
