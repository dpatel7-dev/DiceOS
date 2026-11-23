#!/usr/bin/env node
// Draws the start-up splash pictures into plymouth/dice/: the Dice die (the
// same one DiceWeb draws, from diceweb/js/die3d.js) turning round, in 32
// frames, plus the word DiceOS and the pieces of the loading bar.
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
function word(text) {
  const w = text.length * 6 - 1, h = 7, px = new Uint8Array(w * h * 4);
  [...text].forEach((ch, i) => FONT[ch].forEach((row, y) => [...row].forEach((c, x) => { if (c === '1') px.set([243, 243, 245, 255], (y * w + i * 6 + x) * 4); })));
  return { w, h, px };
}
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
const on = block(4, 2, [243, 243, 245, 255]), off = block(4, 2, [58, 58, 66, 255]);
png(path.join(OUT, 'seg-on.png'), on.w, on.h, on.px, 4);
png(path.join(OUT, 'seg-off.png'), off.w, off.h, off.px, 4);
console.log('Drew ' + FRAMES + ' frames of the die, the word and the loading bar into ' + path.relative(process.cwd(), OUT));
