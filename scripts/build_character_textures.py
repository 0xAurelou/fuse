#!/usr/bin/env python3
"""Extract generated original character parts and package their texture atlas.

This is deterministic texture-build processing, not illustration generation.
The source artwork itself is authored with Image Gen and retained unchanged.
"""
import argparse
import json
from pathlib import Path
from PIL import Image

NAMES = [
    'head-open', 'head-closed', 'torso', 'pelvis',
    'arm-left', 'forearm-left', 'arm-right', 'forearm-right',
    'thigh-left', 'shin-left', 'thigh-right', 'shin-right',
    'back-hair', 'hair-left', 'hair-right', 'coat-tail',
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sheet', type=Path)
    parser.add_argument('--torso', type=Path)
    parser.add_argument('--out', type=Path, default=Path('frontend/public/characters/nova'))
    args = parser.parse_args()
    sheet = Image.open(args.sheet).convert('RGBA')
    out = args.out
    (out / 'images').mkdir(parents=True, exist_ok=True)
    (out / 'source').mkdir(exist_ok=True)
    sheet.save(out / 'source/parts-sheet.png')
    # Generated row boundaries measured from this sheet's transparent gutters.
    cuts_y = [0, 315, 617, 927, 1254]
    cuts_y = [round(value * sheet.height / 1254) for value in cuts_y]
    frames = {}
    atlas = Image.new('RGBA', (2048, 2048))
    lines = ['nova.png', 'size: 2048, 2048', 'format: RGBA8888', 'filter: Linear, Linear', 'repeat: none']
    for index, name in enumerate(NAMES):
        col, row = index % 4, index // 4
        source = sheet.crop((round(col * sheet.width / 4), cuts_y[row], round((col + 1) * sheet.width / 4), cuts_y[row + 1]))
        if name == 'torso' and args.torso:
            source = Image.open(args.torso).convert('RGBA')
            source.save(out / 'source/torso-revision.png')
        box = source.getchannel('A').point(lambda value: 255 if value > 16 else 0).getbbox()
        if not box:
            raise ValueError(f'No visible pixels for {name}')
        # Keep a two-pixel transparent inset to avoid atlas filtering bleed.
        part = source.crop(box)
        if max(part.size) > 450:
            part.thumbnail((450, 450), Image.Resampling.LANCZOS)
        padded = Image.new('RGBA', (part.width + 4, part.height + 4))
        padded.alpha_composite(part, (2, 2))
        padded.save(out / 'images' / f'{name}.png')
        x, y = col * 512 + 12, row * 512 + 12
        atlas.alpha_composite(padded, (x, y))
        w, h = padded.size
        frames[name] = {'x': x, 'y': y, 'width': w, 'height': h}
        lines += [name, '  rotate: false', f'  xy: {x}, {y}', f'  size: {w}, {h}', f'  orig: {w}, {h}', '  offset: 0, 0', '  index: -1']
    atlas.save(out / 'nova.png')
    (out / 'nova.atlas').write_text('\n'.join(lines) + '\n')
    (out / 'textures.json').write_text(json.dumps({'image': 'nova.png', 'width': 2048, 'height': 2048, 'frames': frames}, indent=2) + '\n')
    print(f'Packaged {len(frames)} original parts into {out}')

if __name__ == '__main__':
    main()
