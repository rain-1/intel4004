/* Switch-level simulator for a pMOS netlist (the Intel 4004, extracted from its masks).
 *
 * Every node holds one bit: 1 = pulled negative (towards VDD, -10V), 0 = at VSS (+5V).
 * In the 4004's negative logic a negative node is a logical 1, and a pMOS transistor
 * conducts when its gate is negative -- so "1" conveniently means both. */
#ifndef LESIONSIM_H
#define LESIONSIM_H

typedef struct {
    int gate, a, b;
} Transistor;

typedef struct {
    int n_nodes, n_trans;
    Transistor *tr;
    unsigned char *on;       /* per transistor: conducting? */
    signed char *force;      /* per transistor: -1 normal, 0 stuck open, 1 stuck closed */
    unsigned char *state;    /* per node: 1 = negative */
    unsigned char *driven;   /* per node: held by a supply or an external pin driver */
    int *area;               /* per node: conductor area, stands in for capacitance */
    int **gates, *n_gates;   /* per node: transistors it gates */
    int **chans, *n_chans;   /* per node: transistors it is a source/drain of */
    int vss, vdd;
    /* scratch */
    int *list, *next, *group, n_next;
    unsigned char *in_next, *in_group;
    long settle_passes;      /* statistics */
    int unstable;            /* set if a settle hit the iteration cap */
    int lesion;              /* the forced transistor (for the contention counter), or -1 */
    long contention;         /* settles in which the forced-ON device, naturally off, joined a group
                                that saw VSS and a strong (non-load) path to VDD at once */
} Chip;

Chip *chip_load(const char *netfile, char pad_names[][16], int *pad_nodes, int *n_pads);
void chip_power_on(Chip *c);              /* all nodes to VSS, then settle */
void chip_drive(Chip *c, int node, int v);/* external driver forces a pin */
void chip_release(Chip *c, int node);     /* external driver lets go (pin floats) */
void chip_settle(Chip *c);                /* propagate until stable */
int  chip_driven(Chip *c, int node);       /* is the node connected to a supply or pin driver right now? */
void chip_mark_driven(Chip *c, unsigned char *out); /* out[n] = chip_driven(n) for every node, one pass */
static inline int chip_read(const Chip *c, int node) { return c->state[node]; }

#endif
