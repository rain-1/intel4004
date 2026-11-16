#include "switchsim.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PASSES 400

static void *xcalloc(size_t n, size_t sz) {
    void *p = calloc(n ? n : 1, sz);
    if (!p) { perror("calloc"); exit(1); }
    return p;
}

Chip *chip_load(const char *netfile, char pad_names[][16], int *pad_nodes, int *n_pads) {
    FILE *f = fopen(netfile, "r");
    if (!f) { perror(netfile); exit(1); }
    Chip *c = xcalloc(1, sizeof *c);
    int np;
    if (fscanf(f, "%d %d %d", &c->n_nodes, &c->n_trans, &np) != 3) goto bad;
    c->vss = c->vdd = -1;
    for (int i = 0; i < np; i++) {
        char name[16]; int node;
        if (fscanf(f, "%15s %d", name, &node) != 2) goto bad;
        if (!strcmp(name, "VSS")) c->vss = node;
        if (!strcmp(name, "VDD")) c->vdd = node;
        if (pad_names) { strcpy(pad_names[i], name); pad_nodes[i] = node; }
    }
    if (n_pads) *n_pads = np;
    int n = c->n_nodes, t = c->n_trans;
    c->area = xcalloc(n, sizeof(int));
    for (int i = 0; i < n; i++) if (fscanf(f, "%d", &c->area[i]) != 1) goto bad;
    c->tr = xcalloc(t, sizeof(Transistor));
    c->n_gates = xcalloc(n, sizeof(int));
    c->n_chans = xcalloc(n, sizeof(int));
    for (int i = 0; i < t; i++) {
        Transistor *q = &c->tr[i];
        if (fscanf(f, "%d %d %d", &q->gate, &q->a, &q->b) != 3) goto bad;
        c->n_gates[q->gate]++; c->n_chans[q->a]++; c->n_chans[q->b]++;
    }
    fclose(f);
    c->gates = xcalloc(n, sizeof(int *));
    c->chans = xcalloc(n, sizeof(int *));
    for (int i = 0; i < n; i++) {
        c->gates[i] = xcalloc(c->n_gates[i], sizeof(int));
        c->chans[i] = xcalloc(c->n_chans[i], sizeof(int));
        c->n_gates[i] = c->n_chans[i] = 0;
    }
    for (int i = 0; i < t; i++) {
        Transistor *q = &c->tr[i];
        c->gates[q->gate][c->n_gates[q->gate]++] = i;
        c->chans[q->a][c->n_chans[q->a]++] = i;
        c->chans[q->b][c->n_chans[q->b]++] = i;
    }
    c->on = xcalloc(t, 1);
    c->state = xcalloc(n, 1);
    c->driven = xcalloc(n, 1);
    c->list = xcalloc(n, sizeof(int));
    c->next = xcalloc(n, sizeof(int));
    c->group = xcalloc(n, sizeof(int));
    c->in_next = xcalloc(n, 1);
    c->in_group = xcalloc(n, 1);
    return c;
bad:
    fprintf(stderr, "%s: malformed netlist\n", netfile);
    exit(1);
}

static void enqueue(Chip *c, int node) {
    if (c->driven[node] || c->in_next[node]) return;
    c->in_next[node] = 1;
    c->next[c->n_next++] = node;
}

/* A node changed: switch the transistors it gates and re-examine their terminals. */
static void set_node(Chip *c, int node, int v) {
    if (c->state[node] == v) return;
    c->state[node] = (unsigned char)v;
    for (int i = 0; i < c->n_gates[node]; i++) {
        int t = c->gates[node][i];
        c->on[t] = (unsigned char)v;
        enqueue(c, c->tr[t].a);
        enqueue(c, c->tr[t].b);
    }
}

/* Find everything connected to `start` through conducting transistors and decide the
 * level of that whole group:
 *   - any path to VSS (or a pin driven positive) wins: ratioed logic, drivers beat loads
 *   - else any path to VDD (or a pin driven negative) makes it negative
 *   - else the group is floating and keeps its charge (shared by capacitance) */
static void recalc(Chip *c, int start) {
    int n = 0, head = 0, pos = 0, neg = 0;
    long q_neg = 0, q_pos = 0;
    c->group[n++] = start;
    c->in_group[start] = 1;
    while (head < n) {
        int node = c->group[head++];
        if (c->state[node]) q_neg += c->area[node]; else q_pos += c->area[node];
        for (int i = 0; i < c->n_chans[node]; i++) {
            int t = c->chans[node][i];
            if (!c->on[t]) continue;
            int other = c->tr[t].a == node ? c->tr[t].b : c->tr[t].a;
            if (c->driven[other]) {
                if (c->state[other]) neg = 1; else pos = 1;
            } else if (!c->in_group[other]) {
                c->in_group[other] = 1;
                c->group[n++] = other;
            }
        }
    }
    int v = pos ? 0 : neg ? 1 : (q_neg > q_pos);
    for (int i = 0; i < n; i++) c->in_group[c->group[i]] = 0;
    for (int i = 0; i < n; i++) set_node(c, c->group[i], v);
}

void chip_settle(Chip *c) {
    int pass = 0;
    while (c->n_next) {
        if (++pass > MAX_PASSES) { c->unstable++; break; }
        int n = c->n_next;
        int *tmp = c->list; c->list = c->next; c->next = tmp;
        c->n_next = 0;
        for (int i = 0; i < n; i++) c->in_next[c->list[i]] = 0;
        for (int i = 0; i < n; i++) recalc(c, c->list[i]);
        c->settle_passes++;
    }
    for (int i = 0; i < c->n_next; i++) c->in_next[c->next[i]] = 0;
    c->n_next = 0;
}

static void touch_neighbours(Chip *c, int node) {
    for (int i = 0; i < c->n_chans[node]; i++) {
        Transistor *q = &c->tr[c->chans[node][i]];
        enqueue(c, q->a == node ? q->b : q->a);
    }
}

void chip_drive(Chip *c, int node, int v) {
    c->driven[node] = 1;
    if (c->state[node] != v) set_node(c, node, v);
    touch_neighbours(c, node);
}

void chip_release(Chip *c, int node) {
    if (!c->driven[node]) return;
    c->driven[node] = 0;
    enqueue(c, node);
}

void chip_power_on(Chip *c) {
    memset(c->state, 0, c->n_nodes);
    memset(c->driven, 0, c->n_nodes);
    memset(c->on, 0, c->n_trans);
    c->driven[c->vss] = c->driven[c->vdd] = 1;
    set_node(c, c->vdd, 1);
    for (int i = 0; i < c->n_nodes; i++) enqueue(c, i);
    chip_settle(c);
}

/* Does anything hold this node, or is it floating on its stored charge? */
int chip_driven(Chip *c, int node) {
    if (c->driven[node]) return 1;
    int n = 0, head = 0, found = 0;
    c->group[n++] = node;
    c->in_group[node] = 1;
    while (head < n && !found) {
        int cur = c->group[head++];
        for (int i = 0; i < c->n_chans[cur]; i++) {
            int t = c->chans[cur][i];
            if (!c->on[t]) continue;
            int other = c->tr[t].a == cur ? c->tr[t].b : c->tr[t].a;
            if (c->driven[other]) { found = 1; break; }
            if (!c->in_group[other]) { c->in_group[other] = 1; c->group[n++] = other; }
        }
    }
    for (int i = 0; i < n; i++) c->in_group[c->group[i]] = 0;
    return found;
}
