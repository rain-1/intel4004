/* i4004-vectors: single-instruction test vectors from the transistor-level 4004.
 *
 * There is no ROM here. The rig plays the memory chips by script: it feeds whatever
 * opcode it likes on M1/M2 regardless of the address the chip asks for. That lets it
 *   1. set up any CPU state after reset (FIM for registers, JUN/JMS to plant the stack
 *      and program counter, LDM / STC for accumulator and carry),
 *   2. feed the instruction under test and record every pin on every clock period,
 *   3. read the state back out (WRR exposes the accumulator on the bus, BBL exposes
 *      the stack through the next fetch address, and so on).
 * Nothing inside the chip is peeked at or poked: all of it goes through the pins.
 *
 *   i4004-vectors [--net FILE] --opcode HH [--count N] [--seed S]     JSON lines on stdout
 *   i4004-vectors [--net FILE] --lengths        cycle count of all 256 opcodes
 *   i4004-vectors [--net FILE] --test-timing    when is the TEST pin sampled by JCN?
 *   i4004-vectors [--net FILE] --reset-time     how long must RESET be held?
 */
#include "switchsim.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { A1, A2, A3, M1, M2, X1, X2, X3 };

typedef struct {
    Chip *chip;
    int phi1, phi2, reset, test, sync, d[4], cm[5];
    int slot;
    long step;                 /* clock phases since reset release */
    /* optional: flip TEST when `step` reaches this value */
    long test_flip_at;
    int test_flip_to;
} Rig;

typedef struct {
    int addr;
    int bus[8], driven[8], cm[8], sync[8];   /* sampled while phi2 is active in each slot */
} Cycle;

typedef struct {
    int acc, cy, r[16], pc, stack[3], test, dcl, cm_ram;
} State;

static unsigned long long rng_state = 88172645463325252ULL;
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
    r->test_flip_at = -1;
}

static void bus_drive(Rig *r, int nibble) {
    for (int i = 0; i < 4; i++) {
        if (nibble < 0) chip_release(r->chip, r->d[i]);
        else chip_drive(r->chip, r->d[i], (nibble >> i) & 1);
    }
}

static void tick(Rig *r) {
    r->step++;
    if (r->step == r->test_flip_at) {
        chip_drive(r->chip, r->test, r->test_flip_to);
        chip_settle(r->chip);
    }
}

/* One clock period. `next` is what the memory chips put on the bus for the following
 * period (-1: nothing). Returns the SYNC level seen. */
static int rig_period(Rig *r, int next, Cycle *rec) {
    Chip *c = r->chip;
    chip_drive(c, r->phi1, 1); chip_settle(c); tick(r);
    chip_drive(c, r->phi1, 0); chip_settle(c); tick(r);
    chip_drive(c, r->phi2, 1); chip_settle(c);
    int sync = chip_read(c, r->sync);
    if (rec && r->slot >= 0) {
        int bus = 0, drv = 0, cm = 0;
        for (int i = 0; i < 4; i++) {
            bus |= chip_read(c, r->d[i]) << i;
            /* "driven" asks about the CPU, so look past the rig's own driver */
            int ext = c->driven[r->d[i]];
            c->driven[r->d[i]] = 0;
            drv |= chip_driven(c, r->d[i]) << i;
            c->driven[r->d[i]] = (unsigned char)ext;
        }
        for (int i = 0; i < 5; i++) cm |= chip_read(c, r->cm[i]) << i;
        rec->bus[r->slot] = bus; rec->driven[r->slot] = drv; rec->cm[r->slot] = cm; rec->sync[r->slot] = sync;
    }
    tick(r);
    chip_drive(c, r->phi2, 0); chip_settle(c);
    bus_drive(r, next);
    chip_settle(c);
    tick(r);
    if (sync) r->slot = A1;
    else if (r->slot >= 0) r->slot = (r->slot + 1) & 7;
    return sync;
}

/* One instruction cycle, feeding `byte` as the ROM data and, if x2_in >= 0, driving
 * that nibble during X2 the way a RAM/ROM would for an I/O read. */
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
    while (r->slot != X3) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
    chip_drive(c, r->reset, 0); chip_settle(c);
    rig_period(r, -1, NULL);
    r->step = 0;
    r->test_flip_at = -1;
}

static void feed2(Rig *r, int b1, int b2) { rig_cycle(r, b1, -1, NULL); rig_cycle(r, b2, -1, NULL); }

/* Put the chip into state `s` using only instructions. */
static void setup(Rig *r, const State *s) {
    rig_cycle(r, 0xD0 | s->dcl, -1, NULL);                 /* LDM dcl */
    rig_cycle(r, 0xFD, -1, NULL);                          /* DCL */
    for (int p = 0; p < 8; p++) feed2(r, 0x20 | (p << 1), (s->r[2 * p] << 4) | s->r[2 * p + 1]);   /* FIM */
    rig_cycle(r, s->cy ? 0xFA : 0xF1, -1, NULL);           /* STC / CLC */
    rig_cycle(r, 0xD0 | s->acc, -1, NULL);                 /* LDM acc */
    for (int i = 2; i >= 0; i--) {                         /* plant three return addresses */
        int from = (s->stack[i] - 2) & 0xFFF;
        feed2(r, 0x40 | (from >> 8), from & 0xFF);         /* JUN ret-2 */
        feed2(r, 0x50, 0x00);                              /* JMS: pushes ret */
    }
    feed2(r, 0x40 | (s->pc >> 8), s->pc & 0xFF);           /* JUN pc */
    chip_drive(r->chip, r->test, s->test);
    chip_settle(r->chip);
}

/* Read the state back out through the pins. */
static void readout(Rig *r, State *s) {
    Cycle c;
    rig_cycle(r, 0xE2, -1, &c);                            /* WRR: acc on the bus at X2 */
    s->pc = c.addr;
    s->acc = c.bus[X2];
    s->cm_ram = c.cm[M2] >> 1;
    rig_cycle(r, 0xF7, -1, NULL);                          /* TCC */
    rig_cycle(r, 0xE2, -1, &c);
    s->cy = c.bus[X2];
    for (int i = 0; i < 16; i++) {
        rig_cycle(r, 0xA0 | i, -1, NULL);                  /* LD Ri */
        rig_cycle(r, 0xE2, -1, &c);
        s->r[i] = c.bus[X2];
    }
    for (int i = 0; i < 3; i++) {
        rig_cycle(r, 0xC0, -1, NULL);                      /* BBL: the next fetch shows the return address */
        rig_cycle(r, 0x00, -1, &c);
        s->stack[i] = (c.addr) & 0xFFF;
        /* the NOP advanced the popped PC by one; nothing else depends on it */
    }
    s->test = chip_read(r->chip, r->test);
    s->dcl = -1;
}

static void random_state(State *s) {
    s->acc = (int)rnd(16); s->cy = (int)rnd(2); s->test = (int)rnd(2); s->dcl = (int)rnd(8);
    for (int i = 0; i < 16; i++) s->r[i] = (int)rnd(16);
    s->pc = (int)rnd(4096);
    /* a quarter of the tests sit at a page edge, where FIN/JIN/JCN/ISZ get interesting */
    if (rnd(4) == 0) s->pc = (s->pc & 0xF00) | (0xFC + (int)rnd(4));
    for (int i = 0; i < 3; i++) s->stack[i] = (int)rnd(4096);
    s->cm_ram = 0;
}

/* Is the opcode one or two cycles long? Feed WRR as the following byte: if it is
 * executed as an instruction the chip raises CM-ROM at M2 of that cycle. */
static int opcode_cycles(Rig *r, int opcode) {
    int seen = 0;
    for (int trial = 0; trial < 6; trial++) {
        State s;
        Cycle c;
        random_state(&s);
        rig_reset_for(r, 96);
        setup(r, &s);
        rig_cycle(r, opcode, -1, NULL);
        rig_cycle(r, 0xE2, -1, &c);
        seen |= (c.cm[M2] & 1) ? 1 : 2;
    }
    return seen == 3 ? 0 : seen;    /* 0: it varied (never observed) */
}

static void print_state(const char *key, const State *s, int with_inputs) {
    printf("\"%s\":{\"pc\":%d,\"acc\":%d,\"cy\":%d,\"r\":[", key, s->pc, s->acc, s->cy);
    for (int i = 0; i < 16; i++) printf("%d%s", s->r[i], i < 15 ? "," : "");
    printf("],\"stack\":[%d,%d,%d]", s->stack[0], s->stack[1], s->stack[2]);
    if (with_inputs) printf(",\"dcl\":%d,\"test\":%d", s->dcl, s->test);
    else printf(",\"cm_ram\":%d", s->cm_ram);
    printf("}");
}

static void print_cycle(const Cycle *c) {
    printf("{\"addr\":%d,\"bus\":[", c->addr);
    for (int i = 0; i < 8; i++) printf("%d%s", c->bus[i], i < 7 ? "," : "");
    printf("],\"driven\":[");
    for (int i = 0; i < 8; i++) printf("%d%s", c->driven[i], i < 7 ? "," : "");
    printf("],\"cm\":[");
    for (int i = 0; i < 8; i++) printf("%d%s", c->cm[i], i < 7 ? "," : "");
    printf("],\"sync\":[");
    for (int i = 0; i < 8; i++) printf("%d%s", c->sync[i], i < 7 ? "," : "");
    printf("]}");
}

static void run_vectors(Rig *r, int opcode, int count) {
    int cycles = opcode_cycles(r, opcode);
    int io_read = (opcode >> 4) == 0xE && (opcode & 15) >= 8;
    for (int n = 0; n < count; n++) {
        State init, fin;
        Cycle c[2];
        random_state(&init);
        int arg = (int)rnd(256), io_in = io_read ? (int)rnd(16) : -1;
        rig_reset_for(r, 96);
        setup(r, &init);
        rig_cycle(r, opcode, io_in, &c[0]);
        if (cycles == 2) rig_cycle(r, arg, -1, &c[1]);
        readout(r, &fin);
        printf("{\"name\":\"%02X #%d\",\"opcode\":%d,\"length\":%d,", opcode, n, opcode, cycles);
        print_state("initial", &init, 1);
        printf(",\"fed\":[%d", opcode);
        if (cycles == 2) printf(",%d", arg);
        printf("],\"io_in\":");
        if (io_in >= 0) printf("%d", io_in); else printf("null");
        printf(",");
        print_state("final", &fin, 0);
        printf(",\"cycles\":[");
        print_cycle(&c[0]);
        if (cycles == 2) { printf(","); print_cycle(&c[1]); }
        printf("]}\n");
    }
}

/* JCN on TEST: flip the pin at every possible clock phase and see where the outcome
 * changes. The instruction starts at step 0 here. */
static void test_timing(Rig *r) {
    static const char *slot[] = {"A1", "A2", "A3", "M1", "M2", "X1", "X2", "X3"};
    static const char *phase[] = {"phi1 rises", "phi1 falls", "phi2 rises", "phi2 falls"};
    for (int from = 0; from < 2; from++) {
        int prev = -1;
        printf("TEST goes %d -> %d at step k; JCN 1 (jump if TEST = 0) to $80 from $010:\n", from, !from);
        for (int k = -8; k <= 72; k++) {
            State s;
            Cycle c;
            random_state(&s);
            s.pc = 0x010; s.test = from;
            rig_reset_for(r, 96);
            setup(r, &s);
            r->step = 0;
            r->test_flip_at = k > 0 ? k : -1;
            r->test_flip_to = !from;
            if (k <= 0) { chip_drive(r->chip, r->test, !from); chip_settle(r->chip); }
            rig_cycle(r, 0x11, -1, NULL);
            rig_cycle(r, 0x80, -1, NULL);
            r->test_flip_at = -1;
            rig_cycle(r, 0x00, -1, &c);
            int jumped = c.addr == 0x080;
            if (jumped != prev) {
                if (prev >= 0) {
                    int st = k - 1;   /* the flip happened after step k-1 completed */
                    printf("  outcome changes when the flip moves to after: cycle %d, %s, %s (step %d)\n",
                           st / 32 + 1, slot[(st / 4) % 8], phase[st % 4], k);
                }
                printf("  flip at step %3d or later -> %s\n", k, jumped ? "jumps" : "falls through");
                prev = jumped;
            }
        }
    }
}

/* How long must RESET be held for a fully loaded chip to come out clean? */
static void reset_time(Rig *r) {
    printf("RESET held for N clock periods after loading every register with a non-zero value:\n");
    int last_bad = -1;
    for (int periods = 1; periods <= 160; periods++) {
        State s, f;
        random_state(&s);
        s.acc = 15; s.cy = 1; s.dcl = 7; s.pc = 0xABC;
        for (int i = 0; i < 16; i++) s.r[i] = 15 - (i % 3);
        s.stack[0] = 0x123; s.stack[1] = 0x456; s.stack[2] = 0x789;
        rig_reset_for(r, 96);
        setup(r, &s);
        chip_drive(r->chip, r->test, 0);
        chip_drive(r->chip, r->reset, 1); chip_settle(r->chip);
        for (int i = 0; i < periods; i++) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
        chip_drive(r->chip, r->reset, 0); chip_settle(r->chip);
        while (r->slot != A1) rig_period(r, (r->slot == A3 || r->slot == M1) ? 0 : -1, NULL);
        readout(r, &f);
        int regs = 0;
        for (int i = 0; i < 16; i++) regs += f.r[i] != 0;
        int clean = f.pc <= 1 && f.acc == 0 && f.cy == 0 && regs == 0 && f.cm_ram == 1 &&
                    f.stack[0] == 0 && f.stack[1] == 0 && f.stack[2] == 0;
        if (!clean) {
            last_bad = periods;
            if (periods <= 4 || periods % 8 == 0)
                printf("  N=%3d: pc=%03X acc=%X cy=%d cm_ram=%X stack=%03X,%03X,%03X registers still set: %d\n",
                       periods, f.pc, f.acc, f.cy, f.cm_ram, f.stack[0], f.stack[1], f.stack[2], regs);
        }
    }
    printf("  longest hold that still left something uncleared: %d periods (%.1f instruction cycles)\n",
           last_bad, last_bad / 8.0);
}

int main(int argc, char **argv) {
    const char *net = "netlist/4004.net";
    int opcode = -1, count = 100, mode = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--net") && i + 1 < argc) net = argv[++i];
        else if (!strcmp(argv[i], "--opcode") && i + 1 < argc) opcode = (int)strtol(argv[++i], NULL, 16);
        else if (!strcmp(argv[i], "--count") && i + 1 < argc) count = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--seed") && i + 1 < argc) rng_state ^= strtoull(argv[++i], NULL, 10) * 0x9E3779B97F4A7C15ULL;
        else if (!strcmp(argv[i], "--lengths")) mode = 1;
        else if (!strcmp(argv[i], "--test-timing")) mode = 2;
        else if (!strcmp(argv[i], "--reset-time")) mode = 3;
        else { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
    }
    static Rig rig;
    rig_init(&rig, net);
    if (mode == 1) {
        for (int op = 0; op < 256; op++) printf("%02X %d\n", op, opcode_cycles(&rig, op));
    } else if (mode == 2) {
        test_timing(&rig);
    } else if (mode == 3) {
        reset_time(&rig);
    } else if (opcode >= 0) {
        run_vectors(&rig, opcode, count);
    } else {
        fprintf(stderr, "usage: i4004-vectors --opcode HH [--count N] [--seed S] | --lengths | --test-timing | --reset-time\n");
        return 2;
    }
    if (rig.chip->unstable) fprintf(stderr, "warning: %d settles did not converge\n", rig.chip->unstable);
    return 0;
}
