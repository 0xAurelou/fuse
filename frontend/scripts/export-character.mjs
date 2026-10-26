import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { ATTACHMENTS, BONES, CLIP_SECONDS, samplePose } from '../lib/character-rig.ts';

const directory = fileURLToPath(new URL('../public/characters/nova/', import.meta.url));
await mkdir(directory, { recursive: true });
const round = value => Math.round(value * 1e5) / 1e5;
const frames = Object.fromEntries(Object.entries(CLIP_SECONDS).map(([name, duration]) => [name, Array.from({ length: Math.round(duration * 30) + 1 }, (_, i) => ({ time: round(Math.min(duration, i / 30)), pose: samplePose(name, Math.min(duration, i / 30)) }))]));
await writeFile(`${directory}/nova.rig.json`, JSON.stringify({ name: 'Nova', age: 28, format: 'fuse-articulated-2d-v1', coordinates: 'positive Y down', bones: BONES, attachments: ATTACHMENTS, clips: frames }, null, 2));
const animations = {};
for (const [name, samples] of Object.entries(frames)) {
  const bones = {};
  for (const bone of BONES) {
    const rotate = samples.map(frame => ({ time: frame.time, value: round(-(frame.pose[bone.name].rotation - bone.rotation) * 180 / Math.PI) }));
    const translate = samples.map(frame => ({ time: frame.time, x: round(frame.pose[bone.name].x - bone.x), y: round(-(frame.pose[bone.name].y - bone.y)) }));
    const timelines = {};
    if (rotate.some(frame => Math.abs(frame.value) > 1e-5)) timelines.rotate = rotate;
    if (translate.some(frame => Math.abs(frame.x) + Math.abs(frame.y) > 1e-5)) timelines.translate = translate;
    if (Object.keys(timelines).length) bones[bone.name] = timelines;
  }
  animations[name] = { bones };
  if (name === 'idle' || name === 'dance') animations[name].slots = { face: { attachment: [{ time: 0, name: 'head-open' }, { time: 3.84, name: 'head-closed' }, { time: 3.96, name: 'head-open' }] } };
}
const attachments = {};
for (const attachment of ATTACHMENTS) {
  const region = { type: 'region', path: attachment.image, x: attachment.x, y: -attachment.y, width: attachment.width, height: attachment.height };
  attachments[attachment.name] = { [attachment.image]: region };
  if (attachment.name === 'face') attachments.face['head-closed'] = { ...region, path: 'head-closed' };
}
const spine = {
  skeleton: { spine: '4.2.22', x: -200, y: -30, width: 400, height: 800, images: './images/', fps: 30 },
  bones: BONES.map(bone => ({ name: bone.name, ...(bone.parent ? { parent: bone.parent } : {}), x: bone.x, y: -bone.y, rotation: -bone.rotation * 180 / Math.PI, ...(bone.length ? { length: bone.length } : {}) })),
  slots: ATTACHMENTS.map(attachment => ({ name: attachment.name, bone: attachment.bone, attachment: attachment.image })),
  skins: [{ name: 'default', attachments }], animations,
};
await writeFile(`${directory}/nova.spine.json`, JSON.stringify(spine, null, 2));
execFileSync('python3', ['-c', 'import zipfile,pathlib,sys; p=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(p/"nova-rig.zip","w",zipfile.ZIP_DEFLATED); [z.write(f,f.relative_to(p)) for f in sorted(p.rglob("*")) if f.is_file() and f.suffix!=".zip"]; z.close()', directory]);
console.log('Exported Nova native rig, Spine 4.2-format data and source/texture archive.');
