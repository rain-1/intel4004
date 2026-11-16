#!/usr/bin/env python3
"""Render a vertical (1080x1920) video of the transistor-level 4004 running the birthday
program. Every lit wire in every frame comes from the recorded simulation.

    ./i4004 --quiet --dump build/video/run --extra 400 demo/birthday.bin
    python3 tools/make_video.py build/video/run demo/birthday.bin video/4004-birthday.mp4
    python3 tools/make_video.py build/video/run demo/birthday.bin out_dir --stills 50,200,900

Needs ffmpeg, numpy, Pillow, and the fonts in video/fonts/.
"""
import math
import os
import random
import subprocess
import sys
import wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from diemap import NONE, photo_maps

W, H, FPS = 1080, 1920, 30
BENCH, PANEL, LINE = (13, 15, 21), (21, 25, 35), (41, 48, 63)
INK, MUTED, AMBER, AMBER_DIM = (231, 228, 219), (146, 154, 171), (255, 184, 74), (90, 67, 34)
PAPER, PAPER_INK = (239, 232, 214), (39, 35, 28)
TINT_METAL, TINT_LOWER = np.array([150, 96, 14], np.float32), np.array([128, 44, 30], np.float32)

INTRO, SLOW, RAMP, FINALE = 105, 150, 60, 285     # frames
MAIN_RATE, SUB_RATE, IDLE_RATE = 300.0, 5.0, 32.0  # clock phases per frame
DIE_Y, DIE_H = 250, 796
PAPER_X0, PAPER_X1, PAPER_Y, PAPER_Y_FINAL = 70, 1010, 1270, 630
LINE_H, TEXT_SIZE = 52, 42
SLOTS = ["A1", "A2", "A3", "M1", "M2", "X1", "X2", "X3"]

FONTS = os.path.join(os.path.dirname(__file__), "..", "video", "fonts")


def font(name, size, **axes):
    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    if axes:
        names = [a["name"] if isinstance(a["name"], str) else a["name"].decode() for a in f.get_variation_axes()]
        defaults = {"Weight": 400, "Width": 100}
        f.set_variation_by_axes([axes.get(n.lower(), defaults.get(n, 100)) for n in names])
    return f


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


# ---- the program, as far as the captions need to understand it -----------------------
IO = ["WRM", "WMP", "WRR", "WPM", "WR0", "WR1", "WR2", "WR3", "SBM", "RDM", "RDR", "ADM", "RD0", "RD1", "RD2", "RD3"]
ACC = ["CLB", "CLC", "IAC", "CMC", "CMA", "RAL", "RAR", "TCC", "DAC", "TCS", "STC", "DAA", "KBP", "DCL"]


def disasm(rom, a):
    b, n, r = rom[a], rom[(a + 1) % len(rom)], rom[a] & 15
    return {
        0x0: "NOP", 0x1: f"JCN {r}, ${n:02X}",
        0x2: f"SRC P{r >> 1}" if r & 1 else f"FIM P{r >> 1}, ${n:02X}",
        0x3: f"JIN P{r >> 1}" if r & 1 else f"FIN P{r >> 1}",
        0x4: f"JUN ${(r << 8) | n:03X}", 0x5: f"JMS ${(r << 8) | n:03X}",
        0x6: f"INC R{r}", 0x7: f"ISZ R{r}, ${n:02X}", 0x8: f"ADD R{r}", 0x9: f"SUB R{r}",
        0xA: f"LD R{r}", 0xB: f"XCH R{r}", 0xC: f"BBL {r}", 0xD: f"LDM {r}", 0xE: IO[r],
    }.get(b >> 4, ACC[r] if r < len(ACC) else "?")


def annotate_fetches(rom, fetches):
    """For each fetch: the text to show (instruction, or what a second cycle is doing)."""
    notes, pending, last = [], None, ""
    for _, a in fetches:
        b = rom[a]
        if pending == "operand":
            notes.append(last)
            pending = None
        elif pending == "table":
            ch = f' "{chr(b)}"' if 32 <= b < 127 else ""
            notes.append(f"FIN reads ${b:02X}{ch}")
            pending = None
        else:
            last = disasm(rom, a)
            notes.append(last)
            opr = b >> 4
            if opr in (1, 4, 5, 7) or (opr == 2 and not b & 1):
                pending = "operand"
            elif opr == 3 and not b & 1:
                pending = "table"
    return notes


def main():
    prefix, rom_path, out = sys.argv[1:4]
    stills = [int(x) for x in sys.argv[5].split(",")] if len(sys.argv) > 5 and sys.argv[4] == "--stills" else None
    root = os.path.join(os.path.dirname(__file__), "..")
    photo, ids_m, ids_l, net = photo_maps(os.path.join(root, "source/analyzer"),
                                          os.path.join(root, "source/4004-composite-photo.jpg"),
                                          os.path.join(root, "netlist/photo_align.json"))
    n = net["nodes"]
    pads = net["pads"]
    rom = open(rom_path, "rb").read() + bytes(16)
    states = np.memmap(prefix + ".states", np.uint8, "r").reshape(-1, n)
    fetches, prints, halt = [], [], None
    for line in open(prefix + ".events"):
        step, kind, value = line.split()
        if kind == "F":
            fetches.append((int(step), int(value)))
        elif kind == "P":
            prints.append((int(step), chr(int(value))))
        else:
            halt = int(step)
    notes = annotate_fetches(rom, fetches)
    fetch_steps = np.array([s for s, _ in fetches])
    print_steps = np.array([s for s, _ in prints])
    all_text = "".join(c for _, c in prints)

    # the BCD subtraction: STC, then four rounds of TCS SUB CLC ADD DAA XCH
    stc = rom.index(b"\xFA\xF9")
    end_of = {a: s for s, a in fetches}                 # (each of these addresses runs once)
    sub0, sub1 = end_of[stc] - 32, end_of[stc + 24]
    digit_done = [end_of[stc + 6 * k + 6] for k in range(4)]
    # the two years as the program holds them: FIM P4/P5 and FIM P2/P3 data, thousands first
    year = [rom[8] & 15, rom[8] >> 4, rom[6] & 15, rom[6] >> 4]
    born = [rom[12] & 15, rom[12] >> 4, rom[10] & 15, rom[10] >> 4]
    age = f"{int(''.join(map(str, year))) - int(''.join(map(str, born))):04d}"

    # ---- timeline: which clock phases each frame covers -------------------------------
    spans, pos = [(0, 0)] * INTRO, 0.0

    def advance(rate):
        nonlocal pos
        spans.append((int(pos), int(pos + rate)))
        pos += rate

    for _ in range(SLOW):
        advance(1)
    for f in range(RAMP):
        advance(MAIN_RATE ** ((f + 1) / RAMP))
    while pos < halt:
        if pos < sub0:
            rate = lerp(SUB_RATE, MAIN_RATE, ease((sub0 - pos) / 3000))
        elif pos <= sub1 + 96:
            rate = SUB_RATE
        else:
            rate = lerp(SUB_RATE, MAIN_RATE, ease((pos - sub1 - 96) / 3000))
        advance(max(SUB_RATE, rate))
    halt_frame = len(spans)
    for _ in range(FINALE):
        advance(IDLE_RATE)
    spans = [(a, min(b, len(states) - 1)) for a, b in spans]
    frame_end = np.array([b for _, b in spans])
    frame_of = lambda step: int(np.searchsorted(frame_end, step))
    total = len(spans)
    print(f"{total} frames, {total / FPS:.1f}s; program ends at {halt_frame / FPS:.1f}s", file=sys.stderr)

    # ---- sound -------------------------------------------------------------------------
    if not stills:
        write_audio(out + ".wav", total, spans, prints, frame_of, digit_done, halt_frame)

    # ---- die rendering ------------------------------------------------------------------
    dh, dw = ids_m.shape
    p = np.asarray(photo).astype(np.float32)
    lum = (p * [0.3, 0.5, 0.2]).sum(2, keepdims=True)
    base = (p * 0.55 + lum * 0.45) * np.array([0.42, 0.44, 0.5], np.float32)
    idx_m = np.where(ids_m == NONE, n, ids_m).astype(np.int32)
    idx_l = np.where(ids_l == NONE, n, ids_l).astype(np.int32)
    glow = np.zeros(n, np.float32)
    quiet_nodes = [pads["VSS"], pads["VDD"]]

    def render_die(level, power, zoom):
        lut = np.append(level * power, 0).astype(np.float32)
        gm, gl = lut[idx_m], lut[idx_l]
        halo = Image.fromarray(np.clip((gm + gl * 0.6) * 255, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7))
        halo = np.asarray(halo, np.float32)[..., None] / 255
        rgb = base * (0.25 + 0.75 * power) + gm[..., None] * TINT_METAL + gl[..., None] * TINT_LOWER + halo * (TINT_METAL * 0.55)
        img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
        if zoom > 1.001:
            cw, ch = dw / zoom, dh / zoom
            cx, cy = lerp(dw / 2, dw * 0.47, ease(zoom - 1)), lerp(dh / 2, dh * 0.56, ease(zoom - 1))
            img = img.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2)))
        return img.resize((W, DIE_H), Image.BILINEAR)

    # ---- type ----------------------------------------------------------------------------
    f_title = font("Archivo.ttf", 86, weight=800, width=100)
    f_dates = font("IBMPlexMono-Medium.ttf", 30)
    f_mono = font("IBMPlexMono-Medium.ttf", TEXT_SIZE)
    f_ins = font("IBMPlexMono-Medium.ttf", 38)
    f_small = font("IBMPlexMono-Medium.ttf", 24)
    f_slot = font("IBMPlexMono-Medium.ttf", 26)
    f_cap = font("IBMPlexSans.ttf", 40, weight=500, width=100)
    f_big = font("IBMPlexMono-Medium.ttf", 76)
    f_end = font("IBMPlexSans.ttf", 42, weight=500, width=100)
    adv = f_mono.getlength("M")
    text_x = (PAPER_X0 + PAPER_X1) / 2 - 27 * adv / 2

    rng = random.Random(1971)
    confetti = [dict(x=rng.uniform(0, W), delay=rng.uniform(0, 3.5), speed=rng.uniform(260, 520),
                     sway=rng.uniform(20, 70), w=rng.uniform(1.5, 4), ph=rng.uniform(0, 6.28),
                     size=rng.uniform(10, 22), color=rng.choice([AMBER, PAPER, (240, 120, 90), (127, 214, 208), (255, 220, 130)]))
                for _ in range(170)]

    scroll = 0.0
    sink = None
    if not stills:
        sink = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-i", out + ".wav", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "160k", "-shortest",
             "-movflags", "+faststart", out], stdin=subprocess.PIPE)

    for f, (s0, s1) in enumerate(spans):
        # glow: share of this frame's time each node spent negative, with a short afterglow
        if s1 > s0:
            stride = max(1, (s1 - s0) // 48)
            level = states[s0:s1:stride].mean(0, dtype=np.float32)
        else:
            level = states[s1].astype(np.float32)
        level[quiet_nodes] = 0
        glow = np.maximum(level, glow * 0.72)
        if stills and f not in stills:
            if f < max(stills):
                # keep the paper scroll consistent with the full render
                line = all_text[:int(np.searchsorted(print_steps, s1, "right"))].count("\n") - 1
                target = max(0, line - 9) * LINE_H if f < halt_frame else 0
                scroll += (target - scroll) * 0.25
            continue

        fin = (f - halt_frame) / FPS                       # seconds into the finale (negative before)
        fin_t = ease(fin / 1.3)
        power = ease((f - 45) / 50)
        zoom = 1.0
        if INTRO - 20 <= f < INTRO + SLOW + RAMP:
            zoom = 1 + 1.5 * ease((f - (INTRO - 20)) / 40) * (1 - ease((f - INTRO - SLOW) / RAMP))

        img = Image.new("RGB", (W, H), BENCH)
        d = ImageDraw.Draw(img)
        img.paste(render_die(glow, power, zoom), (0, DIE_Y))
        d.line([(0, DIE_Y - 1), (W, DIE_Y - 1)], LINE, 2)
        d.line([(0, DIE_Y + DIE_H), (W, DIE_Y + DIE_H)], LINE, 2)

        # header
        d.text((60, 66), "15 NOV 1971  →  15 NOV 2026", AMBER, f_dates)
        d.text((56, 108), "Happy birthday, 4004" if fin > 0.4 else "The 4004 turns 55", INK, f_title)

        text = all_text[:int(np.searchsorted(print_steps, s1, "right"))]
        k = int(np.searchsorted(fetch_steps, s1, "right"))
        in_sub = sub0 - 300 <= s1 <= sub1 + 1500

        # instrument strip + caption (fade away for the finale)
        if fin < 0.2:
            slot = (s1 // 4) % 8
            for i, name in enumerate(SLOTS):
                x = 60 + i * 70
                on = i == slot and f >= INTRO
                d.rectangle([x, 1068, x + 62, 1114], AMBER if on else PANEL, None if on else LINE)
                d.text((x + 31, 1091), name, (27, 20, 7) if on else MUTED, f_slot, anchor="mm")
            for i, (label, node) in enumerate((("CLK1", pads["PHI1"]), ("CLK2", pads["PHI2"]), ("SYNC", pads["SYNC"]))):
                x = 640 + i * 132
                on = bool(states[s1][node]) and f >= INTRO
                d.ellipse([x, 1081, x + 20, 1101], AMBER if on else AMBER_DIM)
                d.text((x + 30, 1091), label, INK if on else MUTED, f_slot, anchor="lm")
            if f >= INTRO and k < len(fetches):
                a = fetches[k][1]
                d.text((60, 1136), f"${a:03X}", MUTED, f_ins)
                d.text((60 + f_ins.getlength("$000  "), 1136), notes[k], INK, f_ins)

            if f < 50:
                cap = "A chip from 1971, rebuilt from its own die."
            elif f < INTRO:
                cap = "2,242 transistors. Power on."
            elif f < INTRO + SLOW:
                cap = "Slow motion: one clock phase per frame."
            elif f < INTRO + SLOW + RAMP:
                cap = "Now faster…"
            elif "=" not in text:
                cap = "It reads a message out of its ROM."
            elif in_sub or s1 < sub0:
                cap = "Then does what it was built for: decimal sums."
            elif "." not in text:
                cap = f"One candle per year: {text.count('i')} of {int(age)}"
            else:
                cap = "And a cake."
            d.text((60, 1192), cap, AMBER if "candle" in cap else INK, f_cap)

        # the subtraction, worked on screen as the chip does it
        show = ease((s1 - (sub0 - 300)) / 250) * (1 - ease((s1 - sub1 - 900) / 600))
        if in_sub and show > 0.02:
            panel = Image.new("RGBA", (W, 330), (0, 0, 0, 0))
            pd = ImageDraw.Draw(panel)
            pd.rectangle([0, 0, W, 330], (13, 15, 21, int(225 * show)))
            col = lambda c: c + (int(255 * show),)
            x0, gap = 400, 96
            pd.text((x0 - gap, 18), " ", col(INK), f_big)
            for i in range(4):
                pd.text((x0 + i * gap, 14), str(year[i]), col(INK), f_big)
                pd.text((x0 + i * gap, 104), str(born[i]), col(INK), f_big)
                done = s1 >= digit_done[3 - i]
                working = not done and (i == 3 or s1 >= digit_done[2 - i]) and s1 >= sub0
                if done:
                    pd.text((x0 + i * gap, 214), age[i], col(AMBER), f_big)
                elif working:
                    pd.rectangle([x0 + i * gap - 6, 216, x0 + i * gap + 54, 306], None, col(AMBER), 3)
            pd.text((x0 - gap, 104), "−", col(INK), f_big)
            pd.line([(x0 - gap, 204), (x0 + 4 * gap - 30, 204)], col(MUTED), 4)
            img.paste(panel, (0, DIE_Y + DIE_H - 330), panel)
            d = ImageDraw.Draw(img)

        # teletype paper
        line = text.count("\n") - 1
        target = max(0, line - 9) * LINE_H if fin < 0 else 0
        scroll += (target - scroll) * 0.25
        top = lerp(PAPER_Y, PAPER_Y_FINAL, fin_t)
        bottom = lerp(H + 40, PAPER_Y_FINAL + 18 * LINE_H + 90, fin_t)
        if fin_t > 0:
            d.rectangle([PAPER_X0 + 10, top + 14, PAPER_X1 + 10, bottom + 14], (5, 6, 9))
        d.rectangle([PAPER_X0, top, PAPER_X1, bottom], PAPER)
        lines = text.lstrip("\n").split("\n")
        flames = []
        for i, content in enumerate(lines):
            y = top + 44 + i * LINE_H - scroll
            if y < top + 6 or y > min(bottom, H) - 10:
                continue
            d.text((text_x, y), content, PAPER_INK, f_mono)
            flames += [(text_x + c * adv + adv / 2, y, i * 31 + c) for c, ch in enumerate(content) if ch == "i"]
        if fin < 0.3 and (f // 8) % 2 == 0 and f >= INTRO:      # print head
            y = top + 44 + (len(lines) - 1) * LINE_H - scroll
            d.rectangle([text_x + len(lines[-1]) * adv, y + 8, text_x + (len(lines[-1]) + 0.6) * adv, y + 46], PAPER_INK)
        for x, y, seed in flames:                                # every candle is lit
            flick = math.sin(f * 0.9 + seed * 1.7)
            hgt = 19 + 4 * flick
            cx, by = x + 1.5 * math.sin(f * 0.5 + seed), y + 15
            d.ellipse([cx - 7, by - hgt, cx + 7, by + 2], (245, 130, 40))
            d.ellipse([cx - 3.5, by - hgt * 0.62, cx + 3.5, by + 1], (255, 226, 120))

        if fin > 0:
            a = ease((fin - 1.2) / 0.8)
            if a > 0:
                c = tuple(int(lerp(BENCH[i], INK[i], a)) for i in range(3))
                m = tuple(int(lerp(BENCH[i], MUTED[i], a)) for i in range(3))
                y = PAPER_Y_FINAL + 18 * LINE_H + 130
                d.text((W / 2, y), "Every transistor traced from the die", c, f_end, anchor="ma")
                d.text((W / 2, y + 58), "and simulated, switch by switch.", c, f_end, anchor="ma")
                d.text((W / 2, H - 46), "Die photo and layer tracings: 4004.com, CC BY-NC-SA", m, f_small, anchor="ma")
            for q in confetti:
                t = fin - q["delay"]
                if t < 0:
                    continue
                y = -40 + t * q["speed"]
                if y > H + 40:
                    continue
                x = q["x"] + q["sway"] * math.sin(t * q["w"] + q["ph"])
                ang = t * q["w"] * 2 + q["ph"]
                sx, sy = q["size"] * 0.5, q["size"] * 0.5 * abs(math.cos(ang * 1.3)) + 2
                ca, sa = math.cos(ang), math.sin(ang)
                d.polygon([(x + ca * px - sa * py, y + sa * px + ca * py)
                           for px, py in ((-sx, -sy), (sx, -sy), (sx, sy), (-sx, sy))], q["color"])

        if f < 30:                                               # fade up from black
            img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, ease(f / 30))
        if stills:
            img.save(os.path.join(out, f"frame{f:05d}.png"))
        else:
            sink.stdin.write(img.tobytes())
            if f % 150 == 0:
                print(f"frame {f}/{total}", file=sys.stderr)
    if sink:
        sink.stdin.close()
        sink.wait()
        os.remove(out + ".wav")
        print(f"wrote {out}", file=sys.stderr)


def write_audio(path, total, spans, prints, frame_of, digit_done, halt_frame):
    """Teletype clatter for each printed character, clock ticks in slow motion, a chime per
    decimal digit, and Happy Birthday on a square wave at the end."""
    sr = 44100
    audio = np.zeros(int(total / FPS * sr) + sr, np.float32)
    rng = np.random.default_rng(4004)

    def add(t, sound):
        i = int(t * sr)
        if 0 <= i < len(audio) - len(sound):
            audio[i:i + len(sound)] += sound

    def tone(freq, dur, vol, square=False, decay=0.0):
        t = np.arange(int(dur * sr)) / sr
        w = np.sign(np.sin(2 * np.pi * freq * t)) if square else np.sin(2 * np.pi * freq * t)
        env = np.minimum(1, t / 0.004) * np.minimum(1, (dur - t) / 0.02)
        if decay:
            env = env * np.exp(-t / decay)
        return (w * env * vol).astype(np.float32)

    def click(vol):
        m = int(0.03 * sr)
        t = np.arange(m) / sr
        noise = np.diff(rng.standard_normal(m + 1)) * np.exp(-t / 0.004)
        return ((noise * 0.5 + np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.012)) * vol).astype(np.float32)

    # power-on hum
    t = np.arange(int(2.2 * sr)) / sr
    add(1.4, (np.sin(2 * np.pi * (50 * t + 18 * t * t)) * np.minimum(1, t / 0.5) * np.exp(-t / 1.1) * 0.16).astype(np.float32))
    # slow motion: phi1 and phi2 take turns
    for f in range(INTRO, INTRO + SLOW):
        phase = spans[f][0] % 4
        if phase == 0:
            add(f / FPS, tone(880, 0.03, 0.09))
        elif phase == 2:
            add(f / FPS, tone(660, 0.03, 0.09))
    # teletype
    for step, ch in prints:
        t = frame_of(step) / FPS + rng.uniform(0, 1 / FPS)
        if ch == "\n":
            add(t, tone(110, 0.09, 0.22, decay=0.03))
        elif ch != " ":
            add(t, click(0.22))
    for i, step in enumerate(digit_done):
        t = frame_of(step) / FPS
        add(t, tone(660 * 2 ** (i / 6), 0.16, 0.14, decay=0.06))
        add(t + 0.07, tone(990 * 2 ** (i / 6), 0.22, 0.14, decay=0.08))
    # Happy Birthday (the melody is in the public domain)
    note = {"G": 392.0, "A": 440.0, "B": 493.88, "C": 523.25, "D": 587.33, "E": 659.25, "F": 698.46, "g": 783.99}
    tune = [("G", .75), ("G", .25), ("A", 1), ("G", 1), ("C", 1), ("B", 2),
            ("G", .75), ("G", .25), ("A", 1), ("G", 1), ("D", 1), ("C", 2),
            ("G", .75), ("G", .25), ("g", 1), ("E", 1), ("C", 1), ("B", 1), ("A", 1),
            ("F", .75), ("F", .25), ("E", 1), ("C", 1), ("D", 1), ("C", 3)]
    beat, t = 0.27, halt_frame / FPS + 0.7
    for name, beats in tune:
        dur = beats * beat
        add(t, tone(note[name], dur * 0.92, 0.075, square=True, decay=0.5))
        add(t, tone(note[name] / 2, dur * 0.92, 0.07, decay=0.4))
        t += dur
    # soften the square wave's edge a little, then write
    audio = np.convolve(audio, np.ones(6, np.float32) / 6, "same")
    audio = np.clip(audio, -0.98, 0.98)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sr)
        out.writeframes((audio * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    main()
