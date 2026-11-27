#!/usr/bin/env node
// Draws the start-up splash pictures into plymouth/dice/: the Dice die (the
// same one DiceWeb draws, from diceweb/js/die3d.js) turning round, in 32
// frames, plus the word DiceOS and the pieces of the loading bar. And the
// Traced one, into plymouth/dice-traced/: DiceWeb's hills in Traced mode,
// painted by hand pixel by pixel, with the die and a paper label in ink. Both
// get "Restarting", "Shutting down" and "Updating" for when the computer is
// doing those.
// Node 18 or newer, nothing to install:  node tools/make-splash.js
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT = path.join(__dirname, '..');
const DIE = require(path.join(ROOT, 'diceweb', 'js', 'die3d.js'));
const OUT = path.join(ROOT, 'plymouth', 'dice');
const SIZE = 64, SCALE = 3, FRAMES = 32;
const OUTLINE = [44, 44, 52]; // a soft edge so the black die shows on the black screen

// ---- PNG, by hand (RGBA, no filtering) ------------------------------------
const CRC = new Int32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c; });
function crc32(buf) { let c = -1; for (const b of buf) c = CRC[(c ^ b) & 255] ^ (c >>> 8); return (c ^ -1) >>> 0; }
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(file, w, h, rgba, scale) {
  const W = w * scale, H = h * scale;
  const raw = Buffer.alloc((W * 4 + 1) * H);
  for (let y = 0; y < H; y++) {
    raw[y * (W * 4 + 1)] = 0;
    for (let x = 0; x < W; x++) {
      const s = (Math.floor(y / scale) * w + Math.floor(x / scale)) * 4, d = y * (W * 4 + 1) + 1 + x * 4;
      raw[d] = rgba[s]; raw[d + 1] = rgba[s + 1]; raw[d + 2] = rgba[s + 2]; raw[d + 3] = rgba[s + 3];
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4); ihdr[8] = 8; ihdr[9] = 6;
  fs.writeFileSync(file, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]));
}

// ---- the word "DiceOS", 5 by 7 letters --------------------------------------
const FONT = {
  D: ['1110.', '1..1.', '1...1', '1...1', '1...1', '1..1.', '1110.'],
  i: ['..1..', '.....', '.11..', '..1..', '..1..', '..1..', '.111.'],
  c: ['.....', '.....', '.111.', '1....', '1....', '1....', '.111.'],
  e: ['.....', '.....', '.111.', '1...1', '11111', '1....', '.111.'],
  O: ['.111.', '1...1', '1...1', '1...1', '1...1', '1...1', '.111.'],
  S: ['.1111', '1....', '1....', '.111.', '....1', '....1', '1111.'],
};
Object.assign(FONT, {
  R: ['1111.', '1...1', '1...1', '1111.', '1.1..', '1..1.', '1...1'],
  U: ['1...1', '1...1', '1...1', '1...1', '1...1', '1...1', '.111.'],
  s: ['.....', '.....', '.1111', '1....', '.111.', '....1', '1111.'],
  t: ['.1...', '.1...', '1111.', '.1...', '.1...', '.1..1', '..11.'],
  a: ['.....', '.....', '.111.', '....1', '.1111', '1...1', '.1111'],
  r: ['.....', '.....', '1.11.', '11..1', '1....', '1....', '1....'],
  n: ['.....', '.....', '1.11.', '11..1', '1...1', '1...1', '1...1'],
  g: ['.....', '.1111', '1...1', '1...1', '.1111', '....1', '.111.'],
  h: ['1....', '1....', '1.11.', '11..1', '1...1', '1...1', '1...1'],
  u: ['.....', '.....', '1...1', '1...1', '1...1', '1..11', '.11.1'],
  d: ['....1', '....1', '.11.1', '1..11', '1...1', '1...1', '.1111'],
  o: ['.....', '.....', '.111.', '1...1', '1...1', '1...1', '.111.'],
  w: ['.....', '.....', '1...1', '1...1', '1.1.1', '1.1.1', '.1.1.'],
  p: ['.....', '.....', '1111.', '1...1', '1111.', '1....', '1....'],
  ' ': ['...', '...', '...', '...', '...', '...', '...'],
});
function word(text, rgba) {
  const widths = [...text].map((ch) => FONT[ch][0].length + 1), w = widths.reduce((a, b) => a + b, 0) - 1, h = 7, px = new Uint8Array(w * h * 4);
  let x0 = 0;
  [...text].forEach((ch, i) => { FONT[ch].forEach((row, y) => [...row].forEach((c, x) => { if (c === '1') px.set(rgba || [243, 243, 245, 255], (y * w + x0 + x) * 4); })); x0 += widths[i]; });
  return { w, h, px };
}
const MODES = [['restarting', 'Restarting'], ['shutting', 'Shutting down'], ['updating', 'Updating']];
function block(w, h, rgba) { const px = new Uint8Array(w * h * 4); for (let i = 0; i < w * h; i++) px.set(rgba, i * 4); return { w, h, px }; }

// ---- draw them all ------------------------------------------------------------
fs.mkdirSync(OUT, { recursive: true });
for (const f of fs.readdirSync(OUT)) if (/^die\d+\.png$|^seg-(on|off)\.png$/.test(f)) fs.unlinkSync(path.join(OUT, f));
for (let i = 0; i < FRAMES; i++) {
  // a full turn about the up-down line, starting and ending at rest
  const M = DIE.pose([0, 1, 0], (i / FRAMES) * Math.PI * 2);
  const img = DIE.render(SIZE, M, { ss: 4, outline: OUTLINE });
  png(path.join(OUT, 'die' + i + '.png'), img.w, img.h, img.data, SCALE);
}
const wd = word('DiceOS');
png(path.join(OUT, 'word.png'), wd.w, wd.h, wd.px, 6);
for (const [file, text] of MODES) { const m = word(text, [200, 200, 210, 255]); png(path.join(OUT, file + '.png'), m.w, m.h, m.px, 3); }
const on = block(4, 2, [243, 243, 245, 255]), off = block(4, 2, [58, 58, 66, 255]);
png(path.join(OUT, 'seg-on.png'), on.w, on.h, on.px, 4);
png(path.join(OUT, 'seg-off.png'), off.w, off.h, off.px, 4);
console.log('Drew ' + FRAMES + ' frames of the die, the word and the loading bar into ' + path.relative(process.cwd(), OUT));

// ---- Traced mode: plymouth/dice-traced/ ---------------------------------------------------------
// The picture is DiceWeb's own Traced world (diceweb/js/scape.js and traced.js), painted here without a
// browser on the small canvas below, then the die, a paper label with DiceOS on it, and the bar, in ink.
const TR = path.join(ROOT, 'plymouth', 'dice-traced');
fs.mkdirSync(TR, { recursive: true });
for (const f of fs.readdirSync(TR)) if (/\.png$/.test(f)) fs.unlinkSync(path.join(TR, f));
// just enough of a canvas to paint the worlds: fillRect, drawImage, image data, a rectangle to clip to
function parseColour(v) {
  let m = /^#([0-9a-f]{6})$/i.exec(v);
  if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), 1];
  m = /^rgba?\(([^)]+)\)$/.exec(String(v).replace(/\s/g, ''));
  if (m) { const p = m[1].split(',').map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
  return [0, 0, 0, 0];
}
function softCanvas() {
  let W = 1, H = 1, data = new Uint8ClampedArray(4);
  const cv = { style: {}, get width() { return W; }, set width(v) { W = Math.max(1, v | 0); data = new Uint8ClampedArray(W * H * 4); }, get height() { return H; }, set height(v) { H = Math.max(1, v | 0); data = new Uint8ClampedArray(W * H * 4); }, get data() { return data; } };
  const st = { alpha: 1, fs: '#000000', fill: [0, 0, 0, 1], clip: null, path: [] }, stack = [];
  const inClip = (x, y) => !st.clip || (x >= st.clip[0] && y >= st.clip[1] && x < st.clip[0] + st.clip[2] && y < st.clip[1] + st.clip[3]);
  const put = (x, y, r, g, b, a) => {
    if (x < 0 || y < 0 || x >= W || y >= H || a <= 0 || !inClip(x, y)) return;
    const i = (y * W + x) * 4, da = data[i + 3] / 255, oa = a + da * (1 - a);
    if (oa <= 0) return;
    data[i] = (r * a + data[i] * da * (1 - a)) / oa; data[i + 1] = (g * a + data[i + 1] * da * (1 - a)) / oa; data[i + 2] = (b * a + data[i + 2] * da * (1 - a)) / oa; data[i + 3] = oa * 255;
  };
  const noop = () => {};
  const ctx = {
    canvas: cv, imageSmoothingEnabled: false, globalCompositeOperation: 'source-over', lineWidth: 1, strokeStyle: '#000', font: '', textAlign: 'left', textBaseline: 'alphabetic', shadowBlur: 0, shadowColor: '',
    get globalAlpha() { return st.alpha; }, set globalAlpha(v) { st.alpha = +v; },
    get fillStyle() { return st.fs; }, set fillStyle(v) { st.fs = v; st.fill = typeof v === 'string' ? parseColour(v) : [0, 0, 0, 0]; },
    save() { stack.push({ alpha: st.alpha, fs: st.fs, fill: st.fill, clip: st.clip }); }, restore() { Object.assign(st, stack.pop() || {}); },
    beginPath() { st.path = []; }, rect(x, y, w, h) { st.path.push([x, y, w, h]); }, clip() { if (st.path[0]) st.clip = st.path[0]; },
    moveTo: noop, lineTo: noop, closePath: noop, fill: noop, stroke: noop, ellipse: noop, arc: noop, fillText: noop, setTransform: noop, translate: noop, rotate: noop, scale: noop,
    measureText: () => ({ width: 0 }), createLinearGradient: () => ({ addColorStop: noop }), createRadialGradient: () => ({ addColorStop: noop }),
    fillRect(x, y, w, h) {
      const [r, g, b, a0] = st.fill, a = a0 * st.alpha, x0 = Math.round(x), y0 = Math.round(y), x1 = Math.round(x + w), y1 = Math.round(y + h);
      for (let yy = y0; yy < y1; yy++) for (let xx = x0; xx < x1; xx++) put(xx, yy, r, g, b, a);
    },
    clearRect(x, y, w, h) { for (let yy = Math.max(0, y | 0); yy < Math.min(H, y + h); yy++) data.fill(0, (yy * W + Math.max(0, x | 0)) * 4, (yy * W + Math.min(W, x + w)) * 4); },
    drawImage(img, ...a) {
      let sx = 0, sy = 0, sw = img.width, sh = img.height, dx, dy, dw, dh;
      if (a.length === 2) [dx, dy] = a, dw = sw, dh = sh;
      else if (a.length === 4) [dx, dy, dw, dh] = a;
      else [sx, sy, sw, sh, dx, dy, dw, dh] = a;
      const src = img === cv ? data.slice(0) : img.data, IW = img.width;
      dx = Math.round(dx); dy = Math.round(dy); dw = Math.round(dw); dh = Math.round(dh);
      for (let y = 0; y < dh; y++) for (let x = 0; x < dw; x++) {
        const px = Math.floor(sx + (x * sw) / dw), py = Math.floor(sy + (y * sh) / dh);
        if (px < 0 || py < 0 || px >= IW || py >= img.height) continue;
        const i = (py * IW + px) * 4;
        put(dx + x, dy + y, src[i], src[i + 1], src[i + 2], (src[i + 3] / 255) * st.alpha);
      }
    },
    putImageData(id, x, y) { for (let yy = 0; yy < id.height; yy++) for (let xx = 0; xx < id.width; xx++) { const s = (yy * id.width + xx) * 4, d = ((y + yy) * W + x + xx) * 4; if (x + xx < W && y + yy < H) for (let k = 0; k < 4; k++) data[d + k] = id.data[s + k]; } },
    getImageData(x, y, w, h) { const out = new Uint8ClampedArray(w * h * 4); for (let yy = 0; yy < h; yy++) out.set(data.subarray(((y + yy) * W + x) * 4, ((y + yy) * W + x + w) * 4), yy * w * 4); return { data: out, width: w, height: h }; },
  };
  cv.getContext = () => ctx;
  return cv;
}
{
  const vm = require('vm');
  const box = { document: { createElement: () => softCanvas() }, ImageData: function (d, w, h) { this.data = d; this.width = w; this.height = h; }, console, performance: { now: () => 0 } };
  box.window = box;
  vm.createContext(box);
  for (const f of ['gfx.js', 'scape.js', 'traced.js']) vm.runInContext(fs.readFileSync(path.join(ROOT, 'diceweb', 'js', f), 'utf8'), box, { filename: f });
  const W = 640, H = 360, c = softCanvas();
  c.width = W; c.height = H;
  const scene = new box.DiceGfx.Scape({ world: 'hills', night: false, W, H, seed: 'splash', traced: true });
  scene.draw(c.getContext('2d'), 0, true);
  png(path.join(TR, 'scene.png'), W, H, c.data, 3);
}
// the die with an ink line round it, a paper label with the name, the bar and the words, in ink
const TINK = [44, 46, 72, 255], PAPER = [243, 238, 226, 255];
for (let i = 0; i < FRAMES; i++) {
  const M = DIE.pose([0, 1, 0], (i / FRAMES) * Math.PI * 2);
  const img = DIE.render(SIZE, M, { ss: 4, outline: [44, 46, 72] });
  png(path.join(TR, 'die' + i + '.png'), img.w, img.h, img.data, SCALE);
}
{
  const t = word('DiceOS', TINK), pad = 5, w = t.w + pad * 2 + 2, h = t.h + pad * 2 + 2, px = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const edge = x === 0 || y === 0 || x === w - 1 || y === h - 1;
    px.set(edge ? TINK : y === 1 ? [255, 255, 255, 255] : y === h - 2 ? [222, 214, 196, 255] : PAPER, (y * w + x) * 4);
  }
  for (let y = 0; y < t.h; y++) for (let x = 0; x < t.w; x++) if (t.px[(y * t.w + x) * 4 + 3]) px.set(TINK, ((y + pad + 1) * w + x + pad + 1) * 4);
  png(path.join(TR, 'label.png'), w, h, px, 6);
}
png(path.join(TR, 'seg-on.png'), 4, 2, block(4, 2, TINK).px, 4);
png(path.join(TR, 'seg-off.png'), 4, 2, block(4, 2, [44, 46, 72, 70]).px, 4);
for (const [file, text] of MODES) { const m = word(text, TINK); png(path.join(TR, file + '.png'), m.w, m.h, m.px, 3); }
console.log('Drew the Traced splash into ' + path.relative(process.cwd(), TR));
