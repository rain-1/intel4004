// Cross-check the JavaScript port against a log produced by the C simulator:
//   bun web/check.js netlist/4004.json program.bin expected.sim.log [test-pin-level]
const fs = require("fs");
const { Board } = require("./sim4004.js");
const net = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
net.transistors = net.transistors.flatMap((t) => [t.gate, t.a, t.b]);
const rom = fs.readFileSync(process.argv[3]);
const want = fs.readFileSync(process.argv[4], "utf8").trimEnd().split("\n");
const b = new Board(net, rom);
for (let i = 0; i < 16; i++) b.mem.romIn[i] = (i * 7 + 3) & 15;
if (process.argv[5] === "1") { b.chip.drive(b.pins.test, 1); b.chip.settle(); }
b.mem.log = [];
const t0 = Date.now();
while (b.mem.log.length < want.length && b.cycles < 3e6) b.cycle();
const got = b.mem.log.slice(0, want.length);
const bad = got.findIndex((l, i) => l !== want[i]);
const secs = (Date.now() - t0) / 1000;
if (bad < 0 && got.length === want.length) {
  console.log(`ok   ${process.argv[3]} (${want.length} log lines identical, ${Math.round(b.cycles / secs)} cycles/s)`);
} else {
  console.log(`FAIL ${process.argv[3]} at line ${bad}: got ${got[bad]} want ${want[bad]}`);
  process.exit(1);
}
