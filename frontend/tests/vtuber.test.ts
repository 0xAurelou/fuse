import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DANCE_BPM, DANCE_SECONDS, dancePhase, REACTION_SECONDS, vtuberPose, type VtuberMotion } from '../lib/vtuber-motion.ts';

test('bundled VTuber is a self-contained CC0 skinned VRM with face and spring-bone data', () => {
  const bytes = readFileSync(new URL('../public/characters/victoria/avatar.vrm', import.meta.url));
  assert.equal(bytes.toString('ascii', 0, 4), 'glTF');
  assert.equal(bytes.readUInt32LE(8), bytes.length);
  const gltf = JSON.parse(bytes.toString('utf8', 20, 20 + bytes.readUInt32LE(12)));
  const vrm = gltf.extensions.VRM;
  assert.equal(vrm.meta.licenseName, 'CC0');
  assert.equal(vrm.meta.commercialUssageName, 'Allow');
  assert.ok(gltf.skins.length > 0);
  assert.ok(gltf.meshes.some((mesh: { primitives: { attributes: Record<string, number> }[] }) => mesh.primitives.some(primitive => 'JOINTS_0' in primitive.attributes && 'WEIGHTS_0' in primitive.attributes)));
  assert.ok(vrm.secondaryAnimation.boneGroups.length > 0);
  assert.ok(vrm.blendShapeMaster.blendShapeGroups.some((group: { presetName: string }) => group.presetName === 'blink'));
  for (const resource of [...gltf.buffers, ...gltf.images]) assert.ok(!resource.uri || resource.uri.startsWith('data:'));
});

test('all dance and reaction poses stay finite with bounded expressions', () => {
  for (const motion of ['idle', 'entry', 'win', 'loss'] as VtuberMotion[]) for (let frame = 0; frame <= 960; frame++) {
    const pose = vtuberPose(motion, frame / 60, .8, -.7);
    assert.ok(Object.values(pose.rotations).flat().every(Number.isFinite));
    assert.ok([...pose.hands.left, ...pose.hands.right, pose.x, pose.y, pose.turn].every(Number.isFinite));
    for (const field of ['happy', 'sad', 'angry', 'blink', 'relaxed', 'wink', 'mouthOh', 'mouthAa'] as const) assert.ok(pose[field] >= 0 && pose[field] <= 1);
  }
});

test('classical dance sways the weight smoothly and loops exactly each phrase', () => {
  let minX = 1, maxX = -1;
  for (let frame = 0; frame <= 480; frame++) {
    const pose = vtuberPose('idle', frame / 60);
    minX = Math.min(minX, pose.x); maxX = Math.max(maxX, pose.x);
    for (const side of ['left', 'right'] as const) for (const value of pose.hands[side]) assert.ok(Math.abs(value) < .3);
  }
  assert.ok(minX < -.015 && maxX > .015, `expected weight shift both ways, got ${minX}..${maxX}`);
  for (let frame = 0; frame <= 240; frame++) {
    const a = dancePhase(frame / 60), b = dancePhase(frame / 60 + DANCE_SECONDS);
    for (const field of ['sway', 'bob', 'pulse', 'flow'] as const) assert.ok(Math.abs(a[field] - b[field]) < 1e-10);
  }
});

test('victory cheer lifts the whole body and hands; reactions fade back to the same dance pose', () => {
  const idle = vtuberPose('idle', .5), win = vtuberPose('win', .5, 0, 0, 1.125);
  assert.ok(win.y > idle.y + .03);
  assert.ok(win.hands.left[1] > idle.hands.left[1] && win.hands.right[1] > idle.hands.right[1]);
  assert.ok(win.happy > idle.happy);
  assert.deepEqual(win.rotations.chest, idle.rotations.chest);
  assert.deepEqual(win.rotations.upperChest, idle.rotations.upperChest);
  const kiss = vtuberPose('loss', .5, 0, 0, 1.4);
  assert.ok(kiss.mouthOh > .5 && kiss.wink > .5);
  for (const kind of ['entry', 'win', 'loss'] as const) for (const age of [0, REACTION_SECONDS[kind]]) {
    const pose = vtuberPose(kind, .5, 0, 0, age);
    for (const name of Object.keys(idle.rotations)) pose.rotations[name].forEach((value, index) => assert.ok(Math.abs(value - idle.rotations[name][index]) < 1e-12));
    for (const side of ['left', 'right'] as const) pose.hands[side].forEach((value, index) => assert.ok(Math.abs(value - idle.hands[side][index]) < 1e-12));
    for (const field of ['x', 'y', 'turn', 'happy', 'sad', 'angry', 'blink', 'relaxed', 'wink', 'mouthOh', 'mouthAa'] as const) assert.ok(Math.abs(pose[field] - idle[field]) < 1e-12);
  }
});
