#!/usr/bin/env python3
"""Build web/4004-lesion.html: a single self-contained page showing the lesion study on the
die photo (hover/click a transistor to see what its loss breaks; highlight by instruction,
cluster or block). Run from the repository root after analyze_study.py and figures.py.

    build_lesion_web.py [OUT]
"""
import base64
import io
import json
import os
import sys
from PIL import Image

D = "experiments/lesion"
R = os.path.join(D, "results")
out = sys.argv[1] if len(sys.argv) > 1 else "web/4004-lesion.html"
web = json.load(open(os.path.join(R, "web.json")))
photo = Image.open(os.path.join(D, "figures", ".photo_half.png")).convert("RGB")
buf = io.BytesIO()
photo.save(buf, "JPEG", quality=80)
photo_uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

# compact transistor records
tr = []
for t in web["tr"]:
    rec = [t["x"], t["y"], t["d"], t["g"], t["a"], t["b"], t["cl"], t["blk"]]
    for m in "oc":
        r = t.get(m)
        if r is None:
            rec.append(None); continue
        inst = "".join(chr(48 + round(v / 100 * 40)) for v in r["i"])   # 0..40 -> '0'..'X'
        rec.append([r["s"], r["e"], r["nf"], inst, r["k"], r["r"], ",".join(r["f"]), r["x"], r["fu"]])
    tr.append(rec)
data = dict(names=web["names"], kinds=web["kinds"], sev=web["sev"], eff=web["eff"], clusters=web["clusters"], tr=tr)
summary = open(os.path.join(R, "summary.txt")).read()


def count(mode, sev):
    i = web["sev"].index(sev)
    return sum(1 for t in web["tr"] if mode in t and t[mode]["s"] == i)


html = TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>4004 Lesion Map</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>
/* Same bench as the birthday demo: the die photo is the stage, an instrument column beside it.
   One deliberate dark look (a microscope bench), so no light/dark switch. */
:root {
  color-scheme: dark;
  --bench: #0d0f15; --panel: #151923; --line: #29303f; --ink: #e7e4db; --muted: #929aab;
  --amber: #ffb84a; --amber-dim: #5a4322;
  --sev0: #ffb07a; --sev1: #f28a4e; --sev2: #d95926; --sev3: #a3431c;
  --hi: #3987e5;
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --body: "IBM Plex Sans", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
}
* { box-sizing: border-box; }
body { background: var(--bench); color: var(--ink); font: 16px/1.55 var(--body); margin: 0;
  padding: 28px max(16px, env(safe-area-inset-right, 0px)) 56px max(16px, env(safe-area-inset-left, 0px)); }
.wrap { max-width: 1280px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }
.dates { font: 500 13px var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--amber); }
h1 { font: 800 clamp(28px, 4.6vw, 50px)/1.04 var(--display); letter-spacing: -0.02em; margin: 6px 0 8px; text-wrap: balance; }
.lede { max-width: 72ch; color: var(--muted); margin: 0; }
.lede b { color: var(--ink); font-weight: 600; }
.stage { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 20px; align-items: start; }
@media (max-width: 1000px) { .stage { grid-template-columns: minmax(0, 1fr); } }
.die { margin: 0; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.die canvas { display: block; width: 100%; height: auto; background: #06070a; border: 1px solid var(--line); cursor: crosshair; touch-action: manipulation; }
.controls { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: end; }
.ctl { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.ctl span { font: 500 11px var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
select, button { font: 500 13px var(--mono); color: var(--ink); background: var(--panel); border: 1px solid var(--line);
  padding: 7px 10px; border-radius: 2px; max-width: 100%; }
button { cursor: pointer; }
button[aria-pressed="true"] { background: var(--amber); border-color: var(--amber); color: #1b1407; }
.seg { display: flex; } .seg button + button { border-left: 0; }
select:focus-visible, button:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font: 12px var(--mono); color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }
.legend i.none { background: transparent; border: 1px solid #7a7f8c; }
.status { font: 13px var(--mono); color: var(--muted); margin: 0; min-height: 1.5em; }
.panel { border: 1px solid var(--line); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.label { font: 500 11px var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin: 0; }
.tid { font: 800 22px/1.1 var(--display); margin: 0; }
.kv { font: 13px var(--mono); margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 3px 12px; }
.kv dt { color: var(--muted); } .kv dd { margin: 0; overflow-wrap: anywhere; }
.mode h3 { font: 600 14px var(--body); margin: 0 0 6px; }
.badge { font: 500 11px var(--mono); padding: 1px 6px; border-radius: 2px; margin-left: 6px; color: #1b1407; }
.bars { display: grid; grid-template-columns: 46px 1fr 34px; gap: 2px 8px; font: 11.5px var(--mono); align-items: center; }
.bars .b { height: 8px; background: #232838; border-radius: 0 4px 4px 0; overflow: hidden; }
.bars .b > div { height: 100%; background: var(--sev1); border-radius: 0 4px 4px 0; }
.bars .n { color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
.small { font-size: 13px; color: var(--muted); margin: 0; }
.notes { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px 40px; border-top: 1px solid var(--line); padding-top: 24px; }
.notes > div { min-width: 0; }
h2 { font: 800 20px/1.2 var(--display); margin: 0 0 10px; }
.notes p, .notes li { color: var(--muted); max-width: 64ch; }
.notes p { margin: 0 0 10px; } .notes b { color: var(--ink); font-weight: 600; }
.notes ul { margin: 0; padding-left: 1.2em; }
table { border-collapse: collapse; font: 12.5px var(--mono); width: 100%; }
th, td { text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 500; }
.credit { font-size: 13px; color: var(--muted); max-width: 90ch; margin: 0; }
a { color: var(--amber); }
details pre { font: 11.5px/1.45 var(--mono); color: var(--muted); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="dates">Lesion study &middot; switch-level model</div>
    <h1>What breaks when one transistor fails</h1>
    <p class="lede">Each of the 4004's <b>2,242 transistors</b> was forced permanently <b>off</b> (stuck open) and, separately, permanently <b>on</b> (stuck closed) in a transistor-level simulation of the chip, and the damaged chip was put through <b>2,046 single-instruction tests and 3 reset tests</b>. Hover or tap a transistor to see what its loss breaks.</p>
  </header>
  <div class="stage">
    <figure class="die">
      <canvas id="die" role="img" aria-label="Die photo of the Intel 4004 with every transistor marked and coloured by how badly its lesion damages the chip"></canvas>
      <div class="controls">
        <div class="ctl"><span>Colour by severity of</span>
          <div class="seg" role="group" aria-label="Lesion mode">
            <button type="button" data-mode="o" aria-pressed="true">stuck open</button>
            <button type="button" data-mode="c" aria-pressed="false">stuck closed</button>
            <button type="button" data-mode="w" aria-pressed="false">worse of both</button>
          </div></div>
        <label class="ctl"><span>Highlight instruction</span><select id="f-inst"><option value="">&ndash;</option></select></label>
        <label class="ctl"><span>Highlight cluster</span><select id="f-cl"><option value="">&ndash;</option></select></label>
        <label class="ctl"><span>Highlight block</span><select id="f-blk"><option value="">&ndash;</option></select></label>
        <label class="ctl" style="flex-direction:row;align-items:center;gap:8px"><input type="checkbox" id="f-ng" checked><span>instruction: ignore global lesions</span></label>
      </div>
      <div class="legend" id="legend"></div>
      <p class="status" id="status"></p>
    </figure>
    <aside class="panel" id="info" aria-live="polite">
      <p class="label">Transistor</p>
      <p class="small">Hover over the die (or tap) to inspect a transistor. Click to keep it selected.</p>
    </aside>
  </div>
  <section class="notes">
    <div>
      <h2>How to read it</h2>
      <p><b>Severity.</b> <i>Global</i>: the instructions used to set up and read back the chip fail, or 240+ of the 256 opcodes fail on some test. <i>Broad</i>: 12+ of 19 instruction groups fail (usually a data or address bit). <i>Partial</i>: fewer groups (instruction-specific). <i>Reset-only</i>: only the reset tests differ.</p>
      <p><b>Instructions</b> list the share of that instruction's tests that fail. <b>Kinds</b> say what went wrong: ACC/CY/REG (data), PC/STACK, CMRAM/CM (command lines), ADDR/MBUS/X1/XDOC/DRV (bus), XUND (undocumented X2/X3 bus contents only), SYNC, UNST (simulator did not settle).</p>
      <p><b>Clusters</b> group transistors whose lesions break the same set of instructions in the same ways. <b>Blocks</b> are named from the intact chip's behaviour (a node that always equals register R5 bit 2 belongs to the index registers), not from a drawing.</p>
    </div>
    <div>
      <h2>What "no effect" means here</h2>
      <p>The simulator treats transistors as ideal switches: no voltages, no leakage, no delays, and a path to ground always beats a path to the supply. So <b>no effect</b> means <b>no difference on the pins in these tests, in this model</b>. It does not mean the transistor is unnecessary.</p>
      <ul>
        <li>A load stuck on, or a protection device stuck off, changes nothing by construction.</li>
        <li>A stuck-on device fighting another is resolved as a clean 0 (flag <i>contention</i>); silicon would give a bad level.</li>
        <li>A node left without a driver keeps its charge forever (flag <i>floats</i>); silicon would leak it away within milliseconds.</li>
        <li>The test rig drives TEST, RESET and the clocks as ideal sources.</li>
      </ul>
    </div>
    <div>
      <h2>Counts</h2>
      <table id="counts"></table>
      <details><summary class="small">Full summary of the analysis</summary><pre>__SUMMARY__</pre></details>
    </div>
  </section>
  <p class="credit">Die photomicrograph and mask-layer tracings: the Intel 4004 35th Anniversary Project at <a href="https://www.4004.com/">4004.com</a> (Tim McNerney, Lajos Kintli, Fred Huettig, Barry and Brian Silverman, Christopher Tarnovsky), used under CC BY-NC-SA 3.0. This page, the netlist and the lesion data derived from them carry the same non-commercial terms. Instruction mnemonics follow the MCS-4 manual. Simulation results have not been checked against real chips.</p>
</div>
<script>
"use strict";
(function () {
  const DATA = __DATA__;
  const PHOTO = "__PHOTO__";
  const W = __W__, H = __H__;
  const $ = (id) => document.getElementById(id);
  const canvas = $("die"), ctx = canvas.getContext("2d");
  const css = getComputedStyle(document.documentElement);
  const SEVC = [css.getPropertyValue("--sev0"), css.getPropertyValue("--sev1"), css.getPropertyValue("--sev2"), css.getPropertyValue("--sev3")].map((s) => s.trim());
  const HI = css.getPropertyValue("--hi").trim();
  const N = DATA.names, TR = DATA.tr.map((r, i) => ({ id: i, x: r[0], y: r[1], d: r[2], g: r[3], a: r[4], b: r[5], cl: r[6], blk: r[7].replace(/^~/, ""), blkNear: r[7].startsWith("~"), o: r[8], c: r[9] }));
  for (const t of TR) for (const m of ["o", "c"]) if (t[m]) {
    const r = t[m];
    t[m] = { s: r[0], e: r[1], nf: r[2], inst: Array.from(r[3]).map((ch) => Math.round((ch.charCodeAt(0) - 48) * 2.5)), k: r[4], r: r[5], f: r[6] ? r[6].split(",") : [], x: r[7], fu: r[8] };
  }
  // crop to the transistors
  const xs = TR.map((t) => t.x), ys = TR.map((t) => t.y);
  const X0 = Math.max(0, Math.min(...xs) - 20), X1 = Math.min(W, Math.max(...xs) + 20);
  const Y0 = Math.max(0, Math.min(...ys) - 20), Y1 = Math.min(H, Math.max(...ys) + 20);
  const S = 2;   // canvas pixels per photo pixel
  canvas.width = Math.round((X1 - X0) * S); canvas.height = Math.round((Y1 - Y0) * S);
  let noGlobal = true, mode = "o", fInst = "", fCl = "", fBlk = "", hover = null, pinned = null, photo = null;

  function sevOf(t) {
    if (mode === "w") { const a = t.o ? t.o.s : 4, b = t.c ? t.c.s : 4; return Math.min(a, b); }
    return t[mode] ? t[mode].s : 4;
  }
  function highlighted(t) {
    if (fInst !== "") {
      const i = +fInst, ok = (r) => r && r.inst[i] > 0 && !(noGlobal && r.s === 0);
      if (!(ok(t.o) || ok(t.c))) return false;
    }
    if (fCl !== "" && t.cl !== +fCl) return false;
    if (fBlk !== "" && t.blk !== fBlk) return false;
    return true;
  }
  const filtering = () => fInst !== "" || fCl !== "" || fBlk !== "";

  function draw() {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#06070a"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (photo) { ctx.globalAlpha = 0.32; ctx.drawImage(photo, X0, Y0, X1 - X0, Y1 - Y0, 0, 0, canvas.width, canvas.height); ctx.globalAlpha = 1; }
    ctx.setTransform(S, 0, 0, S, -X0 * S, -Y0 * S);
    const f = filtering();
    let shown = 0;
    for (const t of TR) {
      const hi = f && highlighted(t);
      if (hi) shown++;
      const s = sevOf(t);
      ctx.beginPath(); ctx.arc(t.x, t.y, hi ? 3.6 : 3.0, 0, 2 * Math.PI);
      if (f) {
        if (hi) { ctx.fillStyle = HI; ctx.fill(); ctx.lineWidth = 0.6; ctx.strokeStyle = "#06070a"; ctx.stroke(); }
        else { ctx.fillStyle = "rgba(120,124,136,0.35)"; ctx.fill(); }
      } else if (s >= 4) { ctx.lineWidth = 0.9; ctx.strokeStyle = "rgba(160,166,180,0.8)"; ctx.stroke(); }
      else { ctx.fillStyle = SEVC[s]; ctx.fill(); }
    }
    const sel = pinned ?? hover;
    if (sel !== null) {
      const t = TR[sel];
      ctx.beginPath(); ctx.arc(t.x, t.y, 8, 0, 2 * Math.PI); ctx.lineWidth = 2; ctx.strokeStyle = "#ffffff"; ctx.stroke();
    }
    $("status").textContent = f ? `${shown} transistors highlighted` + (fInst !== "" ? ` (a lesion in either mode breaks ${N[+fInst]} in at least one test${noGlobal ? ", global lesions ignored" : ""})` : "") : "";
  }

  function legend() {
    const lab = ["global", "broad", "partial", "reset only"];
    const counts = [0, 0, 0, 0, 0];
    for (const t of TR) counts[sevOf(t)]++;
    $("legend").innerHTML = (filtering() ? `<span><i style="background:${HI}"></i>highlighted</span><span><i style="background:rgba(120,124,136,0.6)"></i>other</span>` :
      lab.map((l, i) => `<span><i style="background:${SEVC[i]}"></i>${l} ${counts[i]}</span>`).join("") + `<span><i class="none"></i>no effect ${counts[4]}</span>`);
  }

  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  function modeHTML(t, m, title) {
    const r = t[m];
    if (!r) return "";
    const sevName = DATA.sev[r.s];
    const col = r.s < 4 ? SEVC[r.s] : "#7a7f8c";
    const kinds = DATA.kinds.filter((k, i) => r.k & (1 << i));
    let h = `<div class="mode"><h3>${title}<span class="badge" style="background:${col}">${esc(sevName)}</span></h3>`;
    h += `<dl class="kv"><dt>effect</dt><dd>${esc(DATA.eff[r.e])}</dd><dt>failing</dt><dd>${r.nf} of 2046 tests${r.r ? ", reset tests " + r.r.toString(2).split("").reverse().map((b, i) => b === "1" ? i : null).filter((v) => v !== null).join("+") : ""}</dd>`;
    if (kinds.length) h += `<dt>kinds</dt><dd>${esc(kinds.join(" "))}</dd>`;
    if (r.f.length) h += `<dt>flags</dt><dd>${esc(r.f.join(" "))}</dd>`;
    if (r.x) h += `<dt>why null</dt><dd>${esc(r.x)}</dd>`;
    if (r.fu) h += `<dt>follow-up</dt><dd>${esc(r.fu)}</dd>`;
    h += `</dl>`;
    const bad = r.inst.map((v, i) => [v, i]).filter(([v]) => v > 0);
    if (bad.length && bad.length < N.length) {
      bad.sort((a, b) => b[0] - a[0]);
      h += `<div class="bars" style="margin-top:6px">` + bad.slice(0, 14).map(([v, i]) => `<span>${N[i]}</span><div class="b"><div style="width:${v}%"></div></div><span class="n">${v}%</span>`).join("") + `</div>`;
      if (bad.length > 14) h += `<p class="small">&hellip; and ${bad.length - 14} more instructions</p>`;
    } else if (bad.length) h += `<p class="small">every instruction fails in some test (median ${bad.map(([v]) => v).sort((a, b) => a - b)[bad.length >> 1]}% of tests)</p>`;
    return h + `</div>`;
  }
  function info(i) {
    const el = $("info");
    if (i === null) { el.innerHTML = `<p class="label">Transistor</p><p class="small">Hover over the die (or tap) to inspect a transistor. Click to keep it selected.</p>`; return; }
    const t = TR[i], cl = DATA.clusters[t.cl];
    el.innerHTML = `<p class="label">Transistor${pinned !== null ? " (selected; click empty die to release)" : ""}</p><p class="tid">T${t.id} <span class="small">${esc(t.d)}</span></p>
      <dl class="kv"><dt>gate</dt><dd>${esc(t.g)}</dd><dt>channel</dt><dd>${esc(t.a)} &ndash; ${esc(t.b)}</dd>
      <dt>cluster</dt><dd>C${t.cl} (${cl ? cl.n : "?"}): ${esc(cl ? cl.name : "")}</dd><dt>block</dt><dd>${esc(t.blk || "unassigned")}${t.blkNear ? " (by proximity)" : ""}</dd></dl>`
      + modeHTML(t, "o", "Stuck open") + modeHTML(t, "c", "Stuck closed");
  }
  function nearest(ev) {
    const rect = canvas.getBoundingClientRect();
    const px = X0 + (ev.clientX - rect.left) / rect.width * (X1 - X0), py = Y0 + (ev.clientY - rect.top) / rect.height * (Y1 - Y0);
    let best = null, bd = 64;
    for (const t of TR) { const d = (t.x - px) ** 2 + (t.y - py) ** 2; if (d < bd) { bd = d; best = t.id; } }
    return best;
  }
  canvas.addEventListener("mousemove", (ev) => { if (pinned !== null) return; const n = nearest(ev); if (n !== hover) { hover = n; info(n); draw(); } });
  canvas.addEventListener("mouseleave", () => { if (pinned === null) { hover = null; info(null); draw(); } });
  canvas.addEventListener("click", (ev) => { const n = nearest(ev); pinned = n; hover = n; info(n); draw(); });

  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    legend(); draw();
  }));
  const fi = $("f-inst"); N.forEach((n, i) => fi.add(new Option(n, i)));
  const fc = $("f-cl"); DATA.clusters.filter((c) => c.n >= 2).forEach((c) => fc.add(new Option(`C${c.id} (${c.n}) ${c.name.length > 60 ? c.name.slice(0, 58) + "..." : c.name}`, c.id)));
  const fb = $("f-blk"); [...new Set(TR.map((t) => t.blk).filter((b) => b))].sort().forEach((b) => fb.add(new Option(b, b)));
  $("f-ng").addEventListener("change", (e) => { noGlobal = e.target.checked; legend(); draw(); });
  fi.addEventListener("change", () => { fInst = fi.value; legend(); draw(); });
  fc.addEventListener("change", () => { fCl = fc.value; legend(); draw(); });
  fb.addEventListener("change", () => { fBlk = fb.value; legend(); draw(); });

  // counts table
  const rows = DATA.sev.map((s, i) => [s, TR.filter((t) => t.o && t.o.s === i).length, TR.filter((t) => t.c && t.c.s === i).length]);
  $("counts").innerHTML = `<tr><th>severity</th><th>stuck open</th><th>stuck closed</th></tr>` + rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join("");

  legend(); draw(); info(null);
  const im = new Image();
  im.onload = () => { photo = im; draw(); };
  im.src = PHOTO;
})();
</script>
</body>
</html>
"""
summary_html = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
html = (TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
        .replace("__PHOTO__", photo_uri).replace("__W__", str(photo.width)).replace("__H__", str(photo.height))
        .replace("__SUMMARY__", summary_html))
open(out, "w").write(html)
print(f"wrote {out}: {len(html) / 1e6:.2f} MB")
