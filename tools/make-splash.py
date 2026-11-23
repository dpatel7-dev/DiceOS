#!/usr/bin/env python3
"""Draws the boot splash pictures (a pixel die whose dots light up as the Pi
starts, and the word Dice) into plymouth/dice/. Standard library only."""
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'plymouth', 'dice')
COLS = [(0xff, 0x70, 0x7a), (0xf5, 0xc4, 0x31), (0x8f, 0xd1, 0x6a), (0x7c, 0xc4, 0xff), (0xd3, 0x9c, 0xf5), (0x2b, 0xc4, 0xb2)]
PIPS6 = [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]


def png(path, w, h, px, scale):
    rows = []
    for y in range(h * scale):
        row = bytearray([0])
        for x in range(w * scale):
            row += bytes(px[y // scale][x // scale])
        rows.append(bytes(row))
    raw = zlib.compress(b''.join(rows), 9)
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w * scale, h * scale, 8, 6, 0, 0, 0)) + chunk(b'IDAT', raw) + chunk(b'IEND', b''))


def die(lit):
    S = 30
    px = [[(0, 0, 0, 0)] * S for _ in range(S)]
    for y in range(S):
        for x in range(S):
            edge = min(x, y, S - 1 - x, S - 1 - y)
            corner = (x in (0, S - 1)) and (y in (0, S - 1))
            if corner:
                continue
            if edge == 0 or (edge == 1 and ((x in (1, S - 2)) and (y in (1, S - 2)))):
                px[y][x] = (0xf3, 0xf3, 0xf5, 255)
            elif edge >= 1:
                px[y][x] = (0x1b, 0x1b, 0x1f, 255)
    for i, (a, b) in enumerate(PIPS6):
        c = COLS[i] + (255,) if i < lit else (0x3a, 0x3a, 0x42, 255)
        cx, cy = 7 + a * 7, 7 + b * 7
        for y in range(cy, cy + 4):
            for x in range(cx, cx + 4):
                px[y][x] = c
    return S, S, px


FONT = {  # 5 wide, 7 tall
    'D': ['1110.', '1..1.', '1...1', '1...1', '1...1', '1..1.', '1110.'],
    'i': ['..1..', '.....', '.11..', '..1..', '..1..', '..1..', '.111.'],
    'c': ['.....', '.....', '.111.', '1....', '1....', '1....', '.111.'],
    'e': ['.....', '.....', '.111.', '1...1', '11111', '1....', '.111.'],
}


def word(text):
    w = len(text) * 6 - 1
    px = [[(0, 0, 0, 0)] * w for _ in range(7)]
    for i, ch in enumerate(text):
        for y, row in enumerate(FONT[ch]):
            for x, c in enumerate(row):
                if c == '1':
                    px[y][i * 6 + x] = (0xf3, 0xf3, 0xf5, 255)
    return w, 7, px


os.makedirs(OUT, exist_ok=True)
for n in range(7):
    w, h, px = die(n)
    png(os.path.join(OUT, 'die%d.png' % n), w, h, px, 6)
w, h, px = word('Dice')
png(os.path.join(OUT, 'word.png'), w, h, px, 6)
print('wrote the splash pictures to', OUT)
