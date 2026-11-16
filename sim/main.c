/* i4004: run an MCS-4 program on the transistor-level 4004 (or on the reference emulator).
 *
 *   i4004 [options] program.bin
 *     --net FILE      netlist to simulate (default netlist/4004.net)
 *     --ref           use the instruction-level reference emulator instead
 *     --log FILE      write an activity log (fetches, SRC, I/O) for comparison
 *     --cycles N      stop after N instruction cycles (default 2,000,000)
 *     --test N        logic level on the TEST pin (default 0)
 *     --quiet         don't print teletype output
 *     --stats         print simulation statistics at the end
 *     --dump PREFIX   record the run for rendering: PREFIX.states holds every node's
 *                     level after each clock phase (one byte per node), PREFIX.events
 *                     lists fetches and printed characters with their phase number
 *     --extra N       keep running N cycles after the halt (with --dump)
 *
 * Output device ("teletype"): the program writes the low nibble of a character to the
 * output port of ROM chip 0, then the high nibble to ROM chip 1, which prints it.
 * The run stops when the program reaches a jump-to-self. */
#include "board.h"
#include "ref4004.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int quiet;
static FILE *dump_states, *dump_events;
static long dump_step;
static Chip *dump_chip;

static void teletype(Mcs4 *m, int chip, int value) {
    if (chip != 1) return;
    int ch = (value << 4) | m->rom_port[0];
    if (dump_events) fprintf(dump_events, "%ld P %d\n", dump_step, ch);
    if (!quiet) {
        putchar(ch);
        fflush(stdout);
    }
}

static void dump_state(void *user) {
    (void)user;
    fwrite(dump_chip->state, 1, (size_t)dump_chip->n_nodes, dump_states);
    dump_step++;
}

static int is_halt(const Mcs4 *m, int addr) {
    return (m->rom[addr] & 0xF0) == 0x40 &&
           (((m->rom[addr] & 15) << 8) | m->rom[(addr + 1) & 0xFFF]) == addr;
}

int main(int argc, char **argv) {
    const char *net = "netlist/4004.net", *prog = NULL, *logfile = NULL, *dump = NULL;
    long extra = 0;
    int use_ref = 0, test = 0, stats = 0;
    long max_cycles = 2000000;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--net") && i + 1 < argc) net = argv[++i];
        else if (!strcmp(argv[i], "--log") && i + 1 < argc) logfile = argv[++i];
        else if (!strcmp(argv[i], "--cycles") && i + 1 < argc) max_cycles = atol(argv[++i]);
        else if (!strcmp(argv[i], "--test") && i + 1 < argc) test = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--dump") && i + 1 < argc) dump = argv[++i];
        else if (!strcmp(argv[i], "--extra") && i + 1 < argc) extra = atol(argv[++i]);
        else if (!strcmp(argv[i], "--ref")) use_ref = 1;
        else if (!strcmp(argv[i], "--quiet")) quiet = 1;
        else if (!strcmp(argv[i], "--stats")) stats = 1;
        else if (argv[i][0] != '-') prog = argv[i];
        else { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
    }
    if (!prog) { fprintf(stderr, "usage: i4004 [options] program.bin\n"); return 2; }

    static Mcs4 mem;
    mcs4_init(&mem);
    if (mcs4_load_rom(&mem, prog) < 0) { perror(prog); return 1; }
    mem.on_rom_port = teletype;
    for (int i = 0; i < 16; i++) mem.rom_in[i] = (unsigned char)((i * 7 + 3) & 15);  /* something to read back */
    if (logfile && !(mem.log = fopen(logfile, "w"))) { perror(logfile); return 1; }

    clock_t t0 = clock();
    long cycles = 0;
    int halted = 0;
    if (use_ref) {
        Ref4004 cpu;
        ref_reset(&cpu, &mem);
        cpu.test = test;
        while (cpu.cycles < max_cycles && !(halted = is_halt(&mem, cpu.stack[cpu.sp]))) ref_step(&cpu);
        if (halted) {            /* mirror what the pin-level run sees before it stops */
            ref_step(&cpu);
            mcs4_fetch(&mem, cpu.stack[cpu.sp]);
        }
        cycles = cpu.cycles;
    } else {
        static Board b;
        board_init(&b, net, &mem);
        board_reset(&b);
        board_set_test(&b, test);
        if (dump) {
            char path[512];
            snprintf(path, sizeof path, "%s.states", dump);
            dump_states = fopen(path, "wb");
            snprintf(path, sizeof path, "%s.events", dump);
            dump_events = fopen(path, "w");
            if (!dump_states || !dump_events) { perror(dump); return 1; }
            dump_chip = b.chip;
            b.after_step = dump_state;
        }
        int last = -1;
        while (b.cycles < max_cycles) {
            board_cycle(&b);
            if (dump_events) fprintf(dump_events, "%ld F %d\n", dump_step, b.addr);
            /* b.addr is the address just fetched; a jump-to-self fetches a, a+1, a, ... */
            if (!halted && is_halt(&mem, b.addr) && last == ((b.addr + 1) & 0xFFF)) {
                halted = 1;
                if (dump_events) fprintf(dump_events, "%ld H 0\n", dump_step);
            }
            if (halted && --extra < 0) break;
            last = b.addr;
        }
        if (dump) { fclose(dump_states); fclose(dump_events); }
        cycles = b.cycles;
        if (stats) {
            double s = (double)(clock() - t0) / CLOCKS_PER_SEC;
            fprintf(stderr, "%ld cycles, %ld settle passes, %d unstable settles, %.2fs (%.0f cycles/s; a real 4004 does 92,500)\n",
                    cycles, b.chip->settle_passes, b.chip->unstable, s, cycles / (s > 0 ? s : 1));
        }
    }
    if (mem.log) fclose(mem.log);
    if (!halted) fprintf(stderr, "stopped after %ld cycles without reaching a halt\n", cycles);
    return halted ? 0 : 3;
}
