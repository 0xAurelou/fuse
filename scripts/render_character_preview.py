"""Render the exported original rig to a PNG and animated GIF for asset review."""
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'frontend/public/characters/nova'
rig = json.loads((ASSETS / 'nova.rig.json').read_text())
images = {a['image']: Image.open(ASSETS / 'images' / (a['image'] + '.png')).convert('RGBA') for a in rig['attachments']}


def render(frame):
    canvas = Image.new('RGBA', (480, 760), '#17152c')
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 24), 'NOVA / ORIGINAL ADULT CHARACTER', fill='#f6c2e0')
    draw.text((28, 43), 'ARTICULATED RIG / DANCE LOOP', fill='#a995b8')
    world = {}
    for bone in rig['bones']:
        local = frame['pose'][bone['name']]
        if not bone.get('parent'):
            world[bone['name']] = local.copy()
            continue
        parent = world[bone['parent']]
        c, s = math.cos(parent['rotation']), math.sin(parent['rotation'])
        world[bone['name']] = dict(x=parent['x'] + c*local['x'] - s*local['y'], y=parent['y'] + s*local['x'] + c*local['y'], rotation=parent['rotation']+local['rotation'])
    for attachment in rig['attachments']:
        bone = world[attachment['bone']]
        c, s = math.cos(bone['rotation']), math.sin(bone['rotation'])
        x = 240 + bone['x'] + c*attachment['x'] - s*attachment['y']
        y = 715 + bone['y'] + s*attachment['x'] + c*attachment['y']
        image = images[attachment['image']].resize((attachment['width'], attachment['height']), Image.Resampling.LANCZOS)
        image = image.rotate(-math.degrees(bone['rotation']), Image.Resampling.BICUBIC, expand=True)
        canvas.alpha_composite(image, (round(x-image.width/2), round(y-image.height/2)))
    return canvas.convert('RGB')


frames = [render(frame) for frame in rig['clips']['dance'][:-1:2]]
frames[8].save(ASSETS / 'preview.png')
frames[0].save(ASSETS / 'preview.gif', save_all=True, append_images=frames[1:], duration=67, loop=0, optimize=False)
print(f'Rendered {len(frames)} frames to {ASSETS}')
