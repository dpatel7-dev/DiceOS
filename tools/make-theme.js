#!/usr/bin/env node
// SereneTab's colours for DiceOS's browser windows (serenetab-theme/): a soft dawn along
// the top of the window, the tabs and bar in light glass. node tools/make-theme.js
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const OUT = path.join(__dirname, '..', 'serenetab-theme');
const CRC = new Int32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c; });
const crc32 = (buf) => { let c = -1; for (const b of buf) c = CRC[(c ^ b) & 255] ^ (c >>> 8); return (c ^ -1) >>> 0; };
const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, c]); };
function png(file, W, H, px) {
  const raw = Buffer.alloc((W * 3 + 1) * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const [r, g, b] = px(x, y); const d = y * (W * 3 + 1) + 1 + x * 3; raw[d] = r; raw[d + 1] = g; raw[d + 2] = b; }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4); ihdr[8] = 8; ihdr[9] = 2;
  fs.writeFileSync(file, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]));
}
// peach, then lilac, then the morning sky, left to right, a little lighter at the bottom
const STOPS = [[0, [246, 214, 196]], [0.35, [232, 214, 240]], [0.7, [208, 222, 246]], [1, [198, 228, 240]]];
const at = (t) => { for (let i = 1; i < STOPS.length; i++) if (t <= STOPS[i][0]) { const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], k = (t - a) / (b - a); return ca.map((v, j) => v + (cb[j] - v) * k); } return STOPS[STOPS.length - 1][1]; };
fs.mkdirSync(OUT, { recursive: true });
png(path.join(OUT, 'frame.png'), 1600, 120, (x, y) => at(x / 1599).map((v) => Math.round(v + (255 - v) * (y / 119) * 0.25)));
const manifest = {
  manifest_version: 3, name: 'SereneTab', version: '2.3.0', description: 'SereneTab\'s colours for DiceOS\'s browser windows.',
  theme: {
    images: { theme_frame: 'frame.png', theme_frame_inactive: 'frame.png' },
    colors: { frame: [226, 220, 242], frame_inactive: [234, 230, 244], toolbar: [248, 248, 252], tab_text: [30, 34, 48], tab_background_text: [74, 80, 100], tab_background_text_inactive: [110, 114, 130],
      bookmark_text: [40, 44, 58], toolbar_button_icon: [64, 72, 98], omnibox_background: [255, 255, 255], omnibox_text: [26, 30, 44], ntp_background: [222, 230, 246], ntp_text: [30, 34, 48], ntp_link: [70, 100, 190] },
    tints: { buttons: [0.62, 0.35, 0.4] },
    properties: { ntp_background_alignment: 'bottom' },
  },
};
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log('SereneTab\'s window colours are in ' + path.relative(process.cwd(), OUT));
