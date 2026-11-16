/* i4004-busicom: the Busicom 141-PF calculator firmware (1971) running on the
 * transistor-level 4004 (sim/board.c + the netlist), or on the instruction-level
 * reference emulator (sim/ref4004.c), with behavioural models of the calculator's
 * other hardware. See docs/BUSICOM.txt for the model, its sources and its limits.
 *
 *   i4004-busicom [options] KEY...          e.g.  i4004-busicom 2 SQRT
 *                                                 i4004-busicom --ref 18 + 42 + =
 *
 * Keys (case-insensitive; a number such as 18 or 3.25 is typed digit by digit):
 *   0-9 . 00 000      digits, decimal point, double and triple zero
 *   +  -              add to / subtract from the accumulator (the 141-PF is an
 *                     adding-machine-style calculator: "18 + 42 + =" gives 60)
 *   *  /  (X x)       multiply, divide; "=" completes them
 *   =                 equals; after + and - it prints and clears the total
 *   %                 percent (completes * or / like "=", see docs)
 *   SQRT  (SQ)        square root (needs the optional 5th ROM, which is included)
 *   S  (SIGN +/-)     change sign of the number being entered
 *   EX                exchange (swap the operands of * and /)
 *   <>  (DIAMOND)     subtotal: print, and after + / - print and clear the subtotal
 *   <>2 (DIAMOND2)    the second diamond key (same scan code meaning as <>)
 *   CE                clear entry          C   clear (all but memory)
 *   M+ M-             add/subtract the entry to/from memory
 *   M=+ M=-           "=" then add/subtract the result to/from memory
 *   RM                recall memory        CM  recall and clear memory
 *   FEED              hold the paper-advance button (prints a blank line)
 * Switches (take effect at the next key press, as on the real machine):
 *   DP0..DP6 DP8      decimal-point selector (number of decimals; 7 does not exist)
 *   FLOAT ROUND TRUNC rounding switch (floating point, round 5/4, truncate)
 *
 * Options:
 *   --ref             use the instruction-level reference emulator
 *   --net FILE        netlist (default netlist/4004.net)
 *   --rom FILE        firmware image (default source/busicom/busicom-141pf.bin)
 *   --cycles N        stop after N instruction cycles at the latest (default 50,000,000)
 *   --log FILE        bus activity log (every fetch, SRC and I/O transfer)
 *   --quiet           print only the paper tape
 *   --verbose         also print key, lamp, hammer and paper events (stderr)
 *   --color           print red lines in red (ANSI) instead of marking them "red"
 *   --hold S --gap S  key held for S sectors (default 3); released at least S sectors
 *                     (default 2) before the next key; the next key is pressed only
 *                     once the firmware is idle again (back at its lamp update, $01D)
 *   --drum MODEL      emu102 (default) or pilot: drum sector polarity, see docs
 *   --sector-ms F --pulse-ms F   drum sector period / sector pulse width (28, 5)
 *
 * The run ends at a well-defined point, identical for both CPUs: after the
 * instruction at $01D (WMP: the main loop's lamp update, reached only when the calculator is
 * idle with an empty key buffer) that follows the last key's release, or at the first
 * instruction boundary at or after --cycles.
 * Exit status: 0 = finished idle, 3 = cycle limit reached first, 1/2 = errors.
 */
#include "../sim/board.h"
#include "../sim/ref4004.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CYCLE_US 10.8              /* 8 clock periods of 1.35 us (listing, chapter 3.1) */
#define IDLE_ADDR 0x01D            /* main loop, WMP to the lamps: only reached when idle */
#define KBD_ADDR 0x0B0             /* keyboard scan routine */

/* Keyboard matrix (listing chapter 3.2): [shifter bit = column][ROM1 input bit = row] */
static const char *keynames[8][4] = {
    {"CM", "RM", "M-", "M+"}, {"SQRT", "%", "M=-", "M=+"}, {"<>", "/", "*", "="}, {"-", "+", "<>2", "000"},
    {"9", "6", "3", "."}, {"8", "5", "2", "00"}, {"7", "4", "1", "0"}, {"S", "EX", "CE", "C"}};
static const struct { const char *alias, *key; } aliases[] = {
    {"DIAMOND", "<>"}, {"DIAMOND2", "<>2"}, {"SIGN", "S"}, {"+/-", "S"}, {"X", "*"},
    {"SQ", "SQRT"}};

/* Printer drum (listing chapter 3.3): characters by sector, columns 1-15, 17, 18 */
static const char digit_row[] = "0123456789..-";
static const char col17[13][3] = {"<>", "+", "-", "X", "/", "M+", "M-", "^", "=", "SQ", "%", "C", "R"};
static const char col18[13][4] = {"#", "*", "I", "II", "III", "M+", "M-", "T", "K", "E", "Ex", "C", "M"};

enum { STEP_KEY, STEP_FEED };
typedef struct { int kind, col, row, dp, rnd; char name[16]; } Step;

typedef struct {
    /* configuration */
    long sector, pulse;            /* cycles */
    int pilot;                     /* pilot drum polarity */
    int verbose, color;
    /* 4003 shift registers */
    int kb_sr, pr_sr, last_rom0;
    /* inputs */
    int key_col, key_row, feed, dp, rnd;
    /* outputs */
    int last_ram0, last_ram1;
    char line[19][4];              /* printer columns 1..18 */
    int red, lines;
    long fire_min, fire_max;       /* hammer-fire offset within the sector, cycles */
    int fires;
} Calc;

static Calc P;

static int drum_sector(long cyc) { return (int)((cyc / P.sector) % 13); }
static int in_pulse(long cyc) { return cyc % P.sector < P.pulse; }

/* 4003: serial in, shifts on the rising edge of its clock (in the firmware's logic
 * sense: it raises clock together with the data bit, then drops both). */
static void on_rom_port(Mcs4 *m, int chip, int v) {
    (void)m;
    if (chip != 0) return;
    int d = (v >> 1) & 1;
    if ((v & 1) && !(P.last_rom0 & 1)) P.kb_sr = ((P.kb_sr << 1) | d) & 0x3FF;
    if ((v & 4) && !(P.last_rom0 & 4)) P.pr_sr = ((P.pr_sr << 1) | d) & 0xFFFFF;
    P.last_rom0 = v;
}

static int column_rows(int col) {
    int rows = 0;
    if (col == P.key_col) rows |= 1 << P.key_row;
    if (col == 8) rows |= P.dp;      /* digit-point switch: value in binary on the rows */
    if (col == 9) rows |= P.rnd;     /* rounding switch: 1 = round, 8 = truncate */
    return rows;
}

static void emit_line(long cyc) {
    char digits[16];
    for (int c = 1; c <= 15; c++) digits[c - 1] = P.line[c][0] ? P.line[c][0] : ' ';
    digits[15] = 0;
    if (P.color && P.red) printf("|\033[31m%s  %-2s %-3s\033[0m|\n", digits, P.line[17], P.line[18]);
    else printf("|%s  %-2s %-3s|%s\n", digits, P.line[17], P.line[18], P.red ? " red" : "");
    fflush(stdout);
    if (P.verbose) fprintf(stderr, "[%9ld] paper advance\n", cyc);
    memset(P.line, 0, sizeof P.line);
    P.red = 0;
    P.lines++;
}

/* Set the inputs for the cycle starting now, and react to the outputs written so far.
 * Called before every instruction (reference) or every instruction cycle (board). */
static void update_io(Mcs4 *m, long cyc, int *test) {
    int pulse = in_pulse(cyc);
    *test = P.pilot ? !pulse : pulse;
    m->rom_in[2] = (unsigned char)((drum_sector(cyc) == 0) | (P.feed << 3));
    int rows = 0;
    for (int c = 0; c < 10; c++)
        if (!((P.kb_sr >> c) & 1)) rows |= column_rows(c);   /* a 0 selects a column */
    m->rom_in[1] = (unsigned char)rows;

    int r0 = m->ram_port[0][0], r1 = m->ram_port[0][1];
    if (r0 & 1) P.red = 1;                                   /* ribbon colour, latched per line */
    if ((r0 & 2) && !(P.last_ram0 & 2)) {                    /* fire hammers */
        int s = P.pilot ? (drum_sector(cyc) + 12) % 13 : drum_sector(cyc);
        long off = cyc % P.sector;
        if (!P.fires || off < P.fire_min) P.fire_min = off;
        if (!P.fires || off > P.fire_max) P.fire_max = off;
        P.fires++;
        if (P.verbose) fprintf(stderr, "[%9ld] hammers %05X row %d (%.1f ms into the sector)\n",
                               cyc, P.pr_sr, s, off * CYCLE_US / 1000);
        for (int bit = 0; bit < 20; bit++) {
            if (!((P.pr_sr >> bit) & 1)) continue;
            /* bit 0 is the last bit shifted in: column 17; bit 1: column 18; bit 2 unused;
             * bits 3..17: columns 1..15 (listing chapter 3.3) */
            if (bit == 0) strcpy(P.line[17], col17[s]);
            else if (bit == 1) strcpy(P.line[18], col18[s]);
            else if (bit >= 3 && bit <= 17) { P.line[bit - 2][0] = digit_row[s]; P.line[bit - 2][1] = 0; }
        }
    }
    if ((r0 & 8) && !(P.last_ram0 & 8)) emit_line(cyc);    /* paper advance */
    P.last_ram0 = r0;
    if (r1 != P.last_ram1) {
        if (P.verbose) fprintf(stderr, "[%9ld] lamps: memory=%d overflow=%d minus=%d\n",
                               cyc, r1 & 1, (r1 >> 1) & 1, (r1 >> 2) & 1);
        P.last_ram1 = r1;
    }
}

static int streq_ci(const char *a, const char *b) {
    for (; *a && *b; a++, b++) if (toupper((unsigned char)*a) != toupper((unsigned char)*b)) return 0;
    return *a == *b;
}

static int find_key(const char *name, int *col, int *row) {
    for (size_t i = 0; i < sizeof aliases / sizeof *aliases; i++)
        if (streq_ci(name, aliases[i].alias)) name = aliases[i].key;
    for (int c = 0; c < 8; c++)
        for (int r = 0; r < 4; r++)
            if (streq_ci(keynames[c][r], name)) { *col = c; *row = r; return 1; }
    return 0;
}

/* Parse one token into steps; switches change the state used by the following keys. */
static int parse_token(const char *tok, Step *st, int *n, int max, int *dp, int *rnd) {
    int col, row;
    if (toupper((unsigned char)tok[0]) == 'D' && toupper((unsigned char)tok[1]) == 'P' && tok[2] >= '0' &&
        tok[2] <= '8' && tok[2] != '7' && !tok[3]) { *dp = tok[2] - '0'; return 0; }
    if (streq_ci(tok, "FLOAT")) { *rnd = 0; return 0; }
    if (streq_ci(tok, "ROUND")) { *rnd = 1; return 0; }
    if (streq_ci(tok, "TRUNC")) { *rnd = 8; return 0; }
    const char *one[2] = {tok, NULL};
    char split[64][2];
    int nk = 1, number = strcmp(tok, "00") && strcmp(tok, "000") && strcmp(tok, ".") && strlen(tok) < 64;
    for (const char *p = tok; *p && number; p++) if (!isdigit((unsigned char)*p) && *p != '.') number = 0;
    if (number) {                                    /* "18" -> 1 8, "3.25" -> 3 . 2 5 */
        nk = 0;
        for (const char *p = tok; *p; p++) { split[nk][0] = *p; split[nk][1] = 0; nk++; }
    }
    for (int i = 0; i < nk; i++) {
        const char *k = number ? split[i] : one[0];
        if (*n >= max) { fprintf(stderr, "too many keys\n"); return -1; }
        Step *s = &st[*n];
        memset(s, 0, sizeof *s);
        if (streq_ci(k, "FEED")) s->kind = STEP_FEED;
        else if (find_key(k, &col, &row)) { s->kind = STEP_KEY; s->col = col; s->row = row; }
        else { fprintf(stderr, "unknown key or switch '%s' (see the comment at the top of busicom.c)\n", k); return -1; }
        snprintf(s->name, sizeof s->name, "%.15s", k);
        s->dp = *dp; s->rnd = *rnd;
        (*n)++;
    }
    return 0;
}

static int two_cycle(int op) {
    int h = op >> 4;
    return h == 1 || h == 4 || h == 5 || h == 7 || ((h == 2 || h == 3) && !(op & 1));
}

int main(int argc, char **argv) {
    const char *net = "netlist/4004.net", *rom = "source/busicom/busicom-141pf.bin", *logfile = NULL;
    long max_cycles = 50000000;
    int use_ref = 0, quiet = 0, dp = 0, rnd = 0, nsteps = 0;
    double hold = 3, gap = 2, sector_ms = 28, pulse_ms = 5;
    static Step steps[4096];
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--help") || !strcmp(a, "-h")) {
            puts("usage: i4004-busicom [options] KEY...        e.g. i4004-busicom 2 SQRT\n"
                 "keys:     0-9 . 00 000 + - * (X) / = % SQRT S(ign) EX <> <>2 CE C M+ M- M=+ M=- RM CM FEED\n"
                 "switches: DP0..DP6 DP8 (decimals), FLOAT ROUND TRUNC (rounding switch)\n"
                 "options:  --ref --cycles N --log FILE --quiet --verbose --color --hold S --gap S\n"
                 "          --drum emu102|pilot --sector-ms F --pulse-ms F --net FILE --rom FILE\n"
                 "see docs/BUSICOM.txt");
            return 0;
        }
        else if (!strcmp(a, "--ref")) use_ref = 1;
        else if (!strcmp(a, "--net") && i + 1 < argc) net = argv[++i];
        else if (!strcmp(a, "--rom") && i + 1 < argc) rom = argv[++i];
        else if (!strcmp(a, "--cycles") && i + 1 < argc) max_cycles = atol(argv[++i]);
        else if (!strcmp(a, "--log") && i + 1 < argc) logfile = argv[++i];
        else if (!strcmp(a, "--hold") && i + 1 < argc) hold = atof(argv[++i]);
        else if (!strcmp(a, "--gap") && i + 1 < argc) gap = atof(argv[++i]);
        else if (!strcmp(a, "--sector-ms") && i + 1 < argc) sector_ms = atof(argv[++i]);
        else if (!strcmp(a, "--pulse-ms") && i + 1 < argc) pulse_ms = atof(argv[++i]);
        else if (!strcmp(a, "--drum") && i + 1 < argc) {
            const char *d = argv[++i];
            if (!strcmp(d, "pilot")) P.pilot = 1;
            else if (!strcmp(d, "emu102")) P.pilot = 0;
            else { fprintf(stderr, "--drum: emu102 or pilot\n"); return 2; }
        }
        else if (!strcmp(a, "--quiet")) quiet = 1;
        else if (!strcmp(a, "--verbose")) P.verbose = 1;
        else if (!strcmp(a, "--color")) P.color = 1;
        else if (a[0] == '-' && a[1] == '-') { fprintf(stderr, "unknown option %s\n", a); return 2; }
        else {                                       /* keys: one per word, or a quoted list */
            char buf[1024];
            snprintf(buf, sizeof buf, "%s", a);
            for (char *tok = strtok(buf, " \t,"); tok; tok = strtok(NULL, " \t,"))
                if (parse_token(tok, steps, &nsteps, 4096, &dp, &rnd) < 0) return 2;
        }
    }
    P.sector = (long)(sector_ms * 1000 / CYCLE_US + 0.5);   /* 28 ms -> 2593 cycles */
    P.pulse = (long)(pulse_ms * 1000 / CYCLE_US + 0.5);     /*  5 ms ->  463 cycles */
    if (P.pulse < 1 || P.pulse >= P.sector) { fprintf(stderr, "bad drum timing\n"); return 2; }
    long hold_c = (long)(hold * P.sector), gap_c = (long)(gap * P.sector);

    static Mcs4 mem;
    mcs4_init(&mem);
    if (mcs4_load_rom(&mem, rom) < 0) { perror(rom); return 1; }
    mem.on_rom_port = on_rom_port;
    P.key_col = -1;
    /* switch positions before the first key */
    if (nsteps) { P.dp = steps[0].dp; P.rnd = steps[0].rnd; } else { P.dp = dp; P.rnd = rnd; }

    FILE *log = NULL;
    if (logfile && !(log = fopen(logfile, "w"))) { perror(logfile); return 1; }
    static Ref4004 cpu;
    static Board b;
    if (use_ref) ref_reset(&cpu, &mem);
    else { board_init(&b, net, &mem); board_reset(&b); }
    mem.log = log;

    /* Key schedule, decided as the run goes (identically for both CPUs as long as their
     * bus activity is identical): the first key one drum turn after power-on, each later
     * key once the previous one has been released for "gap" and the firmware is idle. */
    int next = 0, held = 0, done = 0;
    long press_at = 13L * P.sector, release_at = 0, wait_from = 13L * P.sector;
    long cyc = 0, kbd_calls = 0;
    int mid = 0;                                     /* board: next cycle is an instruction's 2nd */
    clock_t t0 = clock();
    for (;;) {
        if (!mid && cyc >= max_cycles) break;
        if (held && cyc >= release_at) {
            held = 0; P.key_col = -1; P.feed = 0;
            if (P.verbose) fprintf(stderr, "[%9ld] release %s\n", cyc, steps[next - 1].name);
            wait_from = cyc + gap_c;
            press_at = -1;
        }
        if (!held && press_at >= 0 && cyc >= press_at && next < nsteps) {
            Step *s = &steps[next++];
            P.dp = s->dp; P.rnd = s->rnd;
            if (s->kind == STEP_FEED) P.feed = 1;
            else { P.key_col = s->col; P.key_row = s->row; }
            held = 1; release_at = cyc + hold_c; press_at = -1;
            if (P.verbose) fprintf(stderr, "[%9ld] press %s\n", cyc, s->name);
        }
        int test, at_idle = 0;
        long fetch_cyc;
        update_io(&mem, cyc, &test);
        if (use_ref) {
            int pc = cpu.stack[cpu.sp];
            cpu.test = test;
            fetch_cyc = cpu.cycles;
            ref_step(&cpu);
            cyc = cpu.cycles;
            at_idle = pc == IDLE_ADDR;
            kbd_calls += pc == KBD_ADDR;
        } else {
            int first = !mid;
            board_set_test(&b, test);
            board_cycle(&b);
            cyc = b.cycles;
            fetch_cyc = cyc - 1;
            mid = first && two_cycle(mem.rom[b.addr]);
            at_idle = first && b.addr == IDLE_ADDR;
            kbd_calls += first && b.addr == KBD_ADDR;
        }
        if (at_idle && !held && fetch_cyc >= wait_from) {
            if (next < nsteps) { if (press_at < 0 || press_at > fetch_cyc + 1) press_at = fetch_cyc + 1; }
            else { done = 1; break; }                /* idle after the last key: stop here */
        }
    }
    double secs = (double)(clock() - t0) / CLOCKS_PER_SEC;
    if (log) fclose(log);
    if (!quiet) {
        int r1 = mem.ram_port[0][1];
        fprintf(stderr, "%s: %ld cycles (%.2f s of calculator time) in %.1f s, %.0f cycles/s; "
                "%d lines printed; lamps: memory=%d overflow=%d minus=%d%s\n",
                use_ref ? "reference" : "transistor-level", cyc, cyc * CYCLE_US * 1e-6, secs,
                cyc / (secs > 0 ? secs : 1e-9), P.lines, r1 & 1, (r1 >> 1) & 1, (r1 >> 2) & 1,
                (!use_ref && b.chip->unstable) ? "; UNSTABLE SETTLES" : "");
        if (P.verbose)
            fprintf(stderr, "keyboard routine entered %ld times; %d hammer fires, %.1f-%.1f ms into "
                    "their sector\n", kbd_calls, P.fires, P.fire_min * CYCLE_US / 1000,
                    P.fire_max * CYCLE_US / 1000);
    }
    if (!done) {
        fprintf(stderr, "stopped at the cycle limit (%ld)%s\n", cyc,
                next < nsteps || held ? " before all keys were pressed" : "");
        return 3;
    }
    return 0;
}
