// Replay the netlist-derived single-instruction vectors (vectors/v1) through an
// INDEPENDENT emulator: Mark Ablovatskii's i40xx-emu (MIT, github.com/markablov/i40xx),
// a pin- and stage-level JavaScript model of the 4004/4040. Nothing of it is copied here;
// pass the path of a checkout:
//
//   bun tests/independent/check_i40xx.js <i40xx checkout> vectors/v1 [report.tsv]
//
// Only its CPU class is used. This script plays the part of the ROM and RAM chips on the
// data pins, exactly as the vector says the bus was fed.
import { gunzipSync } from 'node:zlib';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const [emuDir, vecDir, reportPath] = process.argv.slice(2);
const base = resolve(emuDir, 'packages/i40xx-emu/src/cpu');
const { default: CPU } = await import(`${base}/cpu.js`);
const P = await import(`${base}/pins.js`);
const D = [P.D0, P.D1, P.D2, P.D3];
const CMRAM = [P.CM_RAM0, P.CM_RAM1, P.CM_RAM2, P.CM_RAM3];

const NAMES = ['NOP', 'JCN', 'FIM/SRC', 'FIN/JIN', 'JUN', 'JMS', 'INC', 'ISZ', 'ADD', 'SUB', 'LD', 'XCH', 'BBL', 'LDM'];
const IO = ['WRM', 'WMP', 'WRR', 'WPM', 'WR0', 'WR1', 'WR2', 'WR3', 'SBM', 'RDM', 'RDR', 'ADM', 'RD0', 'RD1', 'RD2', 'RD3'];
const ACCG = ['CLB', 'CLC', 'IAC', 'CMC', 'CMA', 'RAL', 'RAR', 'TCC', 'DAC', 'TCS', 'STC', 'DAA', 'KBP', 'DCL'];
function mnemonic(op) {
  const opr = op >> 4, opa = op & 15;
  if (opr === 2) return (opa & 1) ? 'SRC' : 'FIM';
  if (opr === 3) return (opa & 1) ? 'JIN' : 'FIN';
  if (opr === 14) return IO[opa];
  if (opr === 15) return ACCG[opa] ?? 'undefined';
  if (opr === 0) return opa ? 'undefined' : 'NOP';
  return NAMES[opr];
}

function run(t) {
  const cpu = new CPU({ instructionCycles: 0n });
  const r = cpu.registers;
  r.acc = t.initial.acc; r.carry = t.initial.cy; r.pc = t.initial.pc;
  r.indexBanks[0] = [...t.initial.r];
  // vector stack is most recent first; the emulator's is a circular buffer with a pointer
  const s = t.initial.stack;
  r.stack[0] = s[2]; r.stack[1] = s[1]; r.stack[2] = s[0]; r.sp = 3;
  // the emulator's own rule for which CM-RAM lines a DCL value selects
  const dcl = t.initial.dcl & 7;
  r.ramControl = dcl === 0 ? 0b0001 : (dcl << 1);

  const pins = cpu.pins;
  const obs = { addr: [], srcHi: null, srcLo: null, srcCm: null };
  cpu.tick();                                   // the emulator's start-up X3
  for (let c = 0; c < t.length; c++) {
    let a = 0;
    cpu.tick(); a |= pins.getPinsData(D);       // A1
    cpu.tick(); a |= pins.getPinsData(D) << 4;  // A2
    cpu.tick(); a |= pins.getPinsData(D) << 8;  // A3
    obs.addr.push(a);
    pins.setPinsData(D, t.fed[c] >> 4);         // ROM answers: OPR
    cpu.tick();                                 // M1
    pins.setPinsData(D, t.fed[c] & 15);         // OPA
    cpu.tick();                                 // M2
    cpu.tick();                                 // X1
    cpu.tick();                                 // X2
    if (c === 0) { obs.srcHi = pins.getPinsData(D); obs.srcCm = pins.getPinsData(CMRAM); }
    if (t.io_in !== null && t.io_in !== undefined) pins.setPinsData(D, t.io_in);   // RAM/ROM answers a read
    cpu.tick();                                 // X3: execute
    if (c === 0) obs.srcLo = pins.getPinsData(D);
  }
  const top = [1, 2, 3].map((k) => r.stack[(r.sp - k + 7 * 3) % 7]);
  return { pc: r.pc & 0xFFF, acc: r.acc, cy: r.carry, r: r.indexBanks[0], stack: top, cmRam: r.ramControl, obs };
}

const rows = [];
let total = 0, bad = 0;
const perMnemonic = new Map();
for (let op = 0; op < 256; op++) {
  const file = `${vecDir}/${op.toString(16).padStart(2, '0')}.json.gz`;
  const tests = JSON.parse(gunzipSync(readFileSync(file)).toString());
  const m = mnemonic(op);
  const tally = { n: 0, fail: 0, fields: {}, thrown: 0, example: '' };
  for (const t of tests) {
    tally.n++;
    let got;
    try { got = run(t); } catch (e) { tally.thrown++; tally.fail++; tally.fields.threw = (tally.fields.threw || 0) + 1; continue; }
    const f = t.final, diff = [];
    if (got.pc !== f.pc) diff.push('pc');
    if (got.acc !== f.acc) diff.push('acc');
    if (got.cy !== f.cy) diff.push('cy');
    if (got.r.some((v, i) => v !== f.r[i])) diff.push('reg');
    // stack: a 4004 keeps 3 return addresses, this emulator 7 (it also models the 4040).
    // JMS: all three levels are comparable. BBL: only the two that remain defined.
    const levels = (op >> 4) === 12 ? 2 : 3;
    if (got.stack.slice(0, levels).some((v, i) => (v & 0xFFF) !== f.stack[i])) diff.push('stack');
    if (got.cmRam !== f.cm_ram) diff.push('cm_ram');
    if (got.obs.addr.some((a, i) => a !== t.cycles[i].addr)) diff.push('address_out');
    if (m === 'SRC') {
      if (got.obs.srcHi !== t.cycles[0].bus[6] || got.obs.srcLo !== t.cycles[0].bus[7]) diff.push('src_bus');
      if (got.obs.srcCm !== (t.cycles[0].cm[6] >> 1)) diff.push('src_cm');
    }
    if (diff.length) {
      tally.fail++;
      for (const d of diff) tally.fields[d] = (tally.fields[d] || 0) + 1;
      if (!tally.example) {
        tally.example = `${t.name}: init pc=${t.initial.pc} acc=${t.initial.acc} cy=${t.initial.cy} test=${t.initial.test} fed=${t.fed.map((b) => b.toString(16)).join(' ')} io_in=${t.io_in}`
          + ` | netlist pc=${f.pc} acc=${f.acc} cy=${f.cy} | emulator pc=${got.pc} acc=${got.acc} cy=${got.cy}`;
      }
    }
  }
  total += tally.n; bad += tally.fail;
  rows.push([op.toString(16).toUpperCase().padStart(2, '0'), m, tally.n, tally.fail,
    Object.entries(tally.fields).map(([k, v]) => `${k}:${v}`).join(' '), tally.example].join('\t'));
  const pm = perMnemonic.get(m) || { n: 0, fail: 0, fields: {} };
  pm.n += tally.n; pm.fail += tally.fail;
  for (const [k, v] of Object.entries(tally.fields)) pm.fields[k] = (pm.fields[k] || 0) + v;
  perMnemonic.set(m, pm);
}
if (reportPath) writeFileSync(reportPath, `opcode\tmnemonic\ttests\tdiffer\tfields\texample\n${rows.join('\n')}\n`);
console.log(`${total} vectors, ${total - bad} identical, ${bad} differ`);
for (const [m, v] of perMnemonic) {
  if (v.fail) console.log(`  ${m.padEnd(10)} ${String(v.fail).padStart(5)} of ${String(v.n).padStart(5)}  ${Object.entries(v.fields).map(([k, x]) => `${k}:${x}`).join(' ')}`);
}
