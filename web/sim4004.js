// Switch-level simulation of the Intel 4004, running the netlist extracted from the
// chip's mask layers, plus a behavioural MCS-4 board (4001 ROM + ports, 4002 RAM).
// A direct port of sim/switchsim.c, sim/board.c and sim/mcs4.c.
//
// Node value 1 = pulled negative (towards VDD). That is a logical 1 in the 4004's
// negative logic, and also what makes a pMOS transistor conduct.
"use strict";

function Chip(net) {
  const n = net.nodes, tr = net.transistors, t = tr.length / 3;
  this.n = n;
  this.t = t;
  this.gate = new Int32Array(t);
  this.ta = new Int32Array(t);
  this.tb = new Int32Array(t);
  for (let i = 0; i < t; i++) {
    this.gate[i] = tr[3 * i];
    this.ta[i] = tr[3 * i + 1];
    this.tb[i] = tr[3 * i + 2];
  }
  this.area = Int32Array.from(net.area);
  // adjacency in compressed rows: transistors gated by a node / with a terminal on it
  const build = (lists) => {
    const start = new Int32Array(n + 1);
    for (const l of lists) for (let i = 0; i < t; i++) start[l[i] + 1]++;
    for (let i = 0; i < n; i++) start[i + 1] += start[i];
    const fill = start.slice(0, n), items = new Int32Array(start[n]);
    for (const l of lists) for (let i = 0; i < t; i++) items[fill[l[i]]++] = i;
    return [start, items];
  };
  [this.gStart, this.gItems] = build([this.gate]);
  [this.cStart, this.cItems] = build([this.ta, this.tb]);
  this.on = new Uint8Array(t);
  this.state = new Uint8Array(n);
  this.driven = new Uint8Array(n);
  this.list = new Int32Array(n);
  this.next = new Int32Array(n);
  this.nNext = 0;
  this.inNext = new Uint8Array(n);
  this.group = new Int32Array(n);
  this.inGroup = new Uint8Array(n);
  this.vss = net.pads.VSS;
  this.vdd = net.pads.VDD;
  this.unstable = 0;
}

Chip.prototype.enqueue = function (node) {
  if (this.driven[node] || this.inNext[node]) return;
  this.inNext[node] = 1;
  this.next[this.nNext++] = node;
};

Chip.prototype.setNode = function (node, v) {
  if (this.state[node] === v) return;
  this.state[node] = v;
  for (let i = this.gStart[node], e = this.gStart[node + 1]; i < e; i++) {
    const t = this.gItems[i];
    this.on[t] = v;
    this.enqueue(this.ta[t]);
    this.enqueue(this.tb[t]);
  }
};

// Everything reachable from `start` through conducting transistors takes one level:
// VSS wins (drivers beat loads), else VDD, else the floating group keeps its charge.
Chip.prototype.recalc = function (start) {
  const group = this.group, inGroup = this.inGroup, state = this.state, driven = this.driven;
  let n = 0, head = 0, pos = 0, neg = 0, qNeg = 0, qPos = 0;
  group[n++] = start;
  inGroup[start] = 1;
  while (head < n) {
    const node = group[head++];
    if (state[node]) qNeg += this.area[node]; else qPos += this.area[node];
    for (let i = this.cStart[node], e = this.cStart[node + 1]; i < e; i++) {
      const t = this.cItems[i];
      if (!this.on[t]) continue;
      const other = this.ta[t] === node ? this.tb[t] : this.ta[t];
      if (driven[other]) {
        if (state[other]) neg = 1; else pos = 1;
      } else if (!inGroup[other]) {
        inGroup[other] = 1;
        group[n++] = other;
      }
    }
  }
  const v = pos ? 0 : neg ? 1 : (qNeg > qPos ? 1 : 0);
  for (let i = 0; i < n; i++) inGroup[group[i]] = 0;
  for (let i = 0; i < n; i++) this.setNode(group[i], v);
};

Chip.prototype.settle = function () {
  let pass = 0;
  while (this.nNext) {
    if (++pass > 400) { this.unstable++; break; }
    const n = this.nNext, list = this.next;
    this.next = this.list;
    this.list = list;
    this.nNext = 0;
    for (let i = 0; i < n; i++) this.inNext[list[i]] = 0;
    for (let i = 0; i < n; i++) this.recalc(list[i]);
  }
  for (let i = 0; i < this.nNext; i++) this.inNext[this.next[i]] = 0;
  this.nNext = 0;
};

Chip.prototype.drive = function (node, v) {
  this.driven[node] = 1;
  if (this.state[node] !== v) this.setNode(node, v);
  for (let i = this.cStart[node], e = this.cStart[node + 1]; i < e; i++) {
    const t = this.cItems[i];
    this.enqueue(this.ta[t] === node ? this.tb[t] : this.ta[t]);
  }
};

Chip.prototype.release = function (node) {
  if (!this.driven[node]) return;
  this.driven[node] = 0;
  this.enqueue(node);
};

Chip.prototype.powerOn = function () {
  this.state.fill(0);
  this.driven.fill(0);
  this.on.fill(0);
  this.driven[this.vss] = this.driven[this.vdd] = 1;
  this.setNode(this.vdd, 1);
  for (let i = 0; i < this.n; i++) this.enqueue(i);
  this.settle();
};

// ---------------------------------------------------------------------------------
// MCS-4 memory chips. "cm" masks: bit0 = CM-ROM, bits 1..4 = CM-RAM0..3.
function Memory(rom) {
  this.rom = new Uint8Array(4096);
  this.rom.set(rom);
  this.ram = new Uint8Array(4 * 4 * 4 * 16);
  this.status = new Uint8Array(4 * 4 * 4 * 4);
  this.ramPort = new Uint8Array(16);
  this.romPort = new Uint8Array(16);
  this.romIn = new Uint8Array(16);
  this.srcRom = 0;
  this.srcRam = new Uint8Array(4);
  this.log = null;          // optional array of log lines
  this.onRomPort = null;    // (chip, value)
}
const hex = (v, w) => v.toString(16).toUpperCase().padStart(w, "0");
Memory.prototype.fetch = function (addr) { if (this.log) this.log.push("@" + hex(addr, 3)); };
Memory.prototype.src = function (cm, hi, lo) {
  const v = (hi << 4) | lo;
  if (cm & 1) this.srcRom = v;
  for (let b = 0; b < 4; b++) if (cm & (2 << b)) this.srcRam[b] = v;
  if (this.log) this.log.push("SRC cm=" + hex(cm, 2) + " " + hex(v, 2));
};
Memory.isRead = (opa) => opa >= 8;
Memory.prototype.ioRead = function (cm, opa) {
  let v = 0, b = -1;
  for (let i = 3; i >= 0; i--) if (cm & (2 << i)) b = i;
  if (opa === 0xA) v = (cm & 1) ? this.romIn[this.srcRom >> 4] : 0;
  else if (b >= 0) {
    const s = this.srcRam[b], cr = (b << 4) | (s >> 4);
    v = opa >= 0xC ? this.status[(cr << 2) | (opa - 0xC)] : this.ram[(cr << 4) | (s & 15)];
  }
  if (this.log) this.log.push("RD  cm=" + hex(cm, 2) + " E" + hex(opa, 1) + " -> " + hex(v, 1));
  return v;
};
Memory.prototype.ioWrite = function (cm, opa, value) {
  if (this.log) this.log.push("WR  cm=" + hex(cm, 2) + " E" + hex(opa, 1) + " <- " + hex(value, 1));
  if (opa === 2) {
    if (cm & 1) {
      const chip = this.srcRom >> 4;
      this.romPort[chip] = value;
      if (this.onRomPort) this.onRomPort(chip, value);
    }
    return;
  }
  for (let b = 0; b < 4; b++) {
    if (!(cm & (2 << b))) continue;
    const s = this.srcRam[b], cr = (b << 4) | (s >> 4);
    if (opa === 0) this.ram[(cr << 4) | (s & 15)] = value;
    else if (opa === 1) this.ramPort[(b << 2) | (s >> 6)] = value;
    else if (opa >= 4 && opa <= 7) this.status[(cr << 2) | (opa - 4)] = value;
  }
};

// ---------------------------------------------------------------------------------
// The board: clocks the chip and plays the part of the memory chips on its pins.
const SLOT_NAMES = ["A1", "A2", "A3", "M1", "M2", "X1", "X2", "X3"];
const A1 = 0, A2 = 1, A3 = 2, M1 = 3, M2 = 4, X1 = 5, X2 = 6, X3 = 7;

function Board(net, rom) {
  this.chip = new Chip(net);
  this.mem = new Memory(rom);
  const p = net.pads;
  this.pins = { phi1: p.PHI1, phi2: p.PHI2, reset: p.RESET, test: p.TEST, sync: p.SYNC };
  this.d = [p.D0, p.D1, p.D2, p.D3];
  this.cm = [p.CMROM, p.CMRAM0, p.CMRAM1, p.CMRAM2, p.CMRAM3];
  this.reset();
}

Board.prototype.bus = function () {
  const s = this.chip.state, d = this.d;
  return s[d[0]] | (s[d[1]] << 1) | (s[d[2]] << 2) | (s[d[3]] << 3);
};
Board.prototype.cmLines = function () {
  let v = 0;
  for (let i = 0; i < 5; i++) v |= this.chip.state[this.cm[i]] << i;
  return v;
};
Board.prototype.busDrive = function (nibble) {
  this.driving = nibble;
  for (let i = 0; i < 4; i++) {
    if (nibble < 0) this.chip.release(this.d[i]);
    else this.chip.drive(this.d[i], (nibble >> i) & 1);
  }
};

Board.prototype.sample = function () {
  const bus = this.bus(), cm = this.cmLines(), m = this.mem;
  switch (this.slot) {
    case A1: this.addr = bus; break;
    case A2: this.addr |= bus << 4; break;
    case A3: this.addr |= bus << 8; this.fetchAddr = this.addr; m.fetch(this.addr); break;
    case M2: this.ioCm = cm; this.ioOpa = bus; break;
    case X2:
      if (this.ioCm) { if (!Memory.isRead(this.ioOpa)) m.ioWrite(this.ioCm, this.ioOpa, bus); }
      else if (cm) { this.srcCm = cm; this.srcHi = bus; }
      break;
    case X3:
      if (this.srcCm) m.src(this.srcCm, this.srcHi, bus);
      this.srcCm = 0;
      break;
  }
};

Board.prototype.nextDrive = function () {
  const rom = this.mem.rom;
  switch (this.slot) {
    case A3: return this.inReset ? 0 : rom[this.addr] >> 4;
    case M1: return this.inReset ? 0 : rom[this.addr] & 15;
    case X1:
      return this.ioCm && Memory.isRead(this.ioOpa) ? this.mem.ioRead(this.ioCm, this.ioOpa) : -1;
    default: return -1;
  }
};

// One quarter of a clock period: phi1 on, phi1 off, phi2 on, phi2 off.
Board.prototype.step = function () {
  const c = this.chip, pins = this.pins;
  switch (this.phase) {
    case 0: c.drive(pins.phi1, 1); c.settle(); break;
    case 1: c.drive(pins.phi1, 0); c.settle(); break;
    case 2:
      c.drive(pins.phi2, 1); c.settle();
      this.syncSeen = c.state[pins.sync];
      if (this.slot >= 0) this.sample();
      break;
    case 3:
      c.drive(pins.phi2, 0); c.settle();
      if (this.slot >= 0) {
        this.busDrive(this.nextDrive());
        c.settle();
        if (this.slot === X3) this.cycles++;
      }
      if (this.syncSeen) this.slot = A1;
      else if (this.slot >= 0) this.slot = (this.slot + 1) & 7;
      break;
  }
  this.phase = (this.phase + 1) & 3;
};
Board.prototype.period = function () { do this.step(); while (this.phase !== 0); };
Board.prototype.cycle = function () { do this.period(); while (this.slot !== A1); };

Board.prototype.reset = function () {
  const c = this.chip, pins = this.pins;
  this.mem.ram.fill(0); this.mem.status.fill(0);
  this.mem.ramPort.fill(0); this.mem.romPort.fill(0);
  this.mem.srcRom = 0; this.mem.srcRam.fill(0);
  c.powerOn();
  c.drive(pins.phi1, 0); c.drive(pins.phi2, 0); c.drive(pins.test, 0); c.drive(pins.reset, 1);
  c.settle();
  this.slot = -1; this.phase = 0; this.driving = -1; this.inReset = true;
  this.addr = this.fetchAddr = 0; this.ioCm = this.srcCm = 0; this.syncSeen = 0;
  const log = this.mem.log, hook = this.mem.onRomPort;
  this.mem.log = null; this.mem.onRomPort = null;
  for (let i = 0; i < 96; i++) this.period();
  while (this.slot !== X3) this.period();
  c.drive(pins.reset, 0); c.settle();
  while (this.slot !== A1) this.period();
  this.inReset = false;
  this.ioCm = this.srcCm = 0;
  this.cycles = 0;
  this.mem.log = log; this.mem.onRomPort = hook;
};

// True once the program sits in a jump-to-self.
Board.prototype.halted = function () {
  const rom = this.mem.rom, a = this.fetchAddr;
  const isHalt = (x) => (rom[x] & 0xF0) === 0x40 && (((rom[x] & 15) << 8) | rom[(x + 1) & 0xFFF]) === x;
  return isHalt(a) || (a > 0 && isHalt(a - 1));
};

if (typeof module !== "undefined") module.exports = { Chip, Memory, Board, SLOT_NAMES };
