import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { BONES, CLIP_SECONDS, samplePose, solveLeg, stepSpring, worldPose, type Motion } from '../lib/character-rig.ts';

test('two-bone leg IK keeps the ankle on its authored target throughout a dance loop', () => {
  for (let frame = 0; frame <= 240; frame++) {
    const t = frame / 60, pose = samplePose('dance', t), world = worldPose(pose);
    for (const [side, sign] of [['left', -1], ['right', 1]] as const) {
      const shin = world[`shin-${side}`];
      const x = shin.x - Math.sin(shin.rotation) * 148, y = shin.y + Math.cos(shin.rotation) * 148;
      const lift = Math.max(0, -sign * Math.sin(Math.PI * t)) * 13;
      assert.ok(Math.abs(x - sign * 63) < 1e-7);
      assert.ok(Math.abs(y - (-8 - lift)) < 1e-7);
    }
  }
});

test('looping clips are continuous and every pose is finite across all supported actions', () => {
  for (const motion of Object.keys(CLIP_SECONDS) as Motion[]) {
    const length = CLIP_SECONDS[motion];
    for (let frame = 0; frame <= length * 60; frame++) {
      const pose = samplePose(motion, frame / 60);
      for (const bone of BONES) assert.ok(Object.values(pose[bone.name]).every(Number.isFinite));
    }
    if (motion === 'dance' || motion === 'idle') {
      const start = samplePose(motion, 0), end = samplePose(motion, length);
      for (const bone of BONES) for (const field of ['x', 'y', 'rotation'] as const) assert.ok(Math.abs(start[bone.name][field] - end[bone.name][field]) < 1e-9);
    }
  }
  const unreachable = solveLeg(1000, 1000, -1);
  assert.ok(Number.isFinite(unreachable.thigh) && Number.isFinite(unreachable.knee));
});

test('hair spring settles and remains bounded after a delayed frame', () => {
  let spring = { value: 0, velocity: 0 };
  for (let frame = 0; frame < 300; frame++) spring = stepSpring(spring, .3, frame === 10 ? 100 : 1 / 60);
  assert.ok(Math.abs(spring.value - .3) < 1e-6);
  assert.ok(Math.abs(spring.velocity) < 1e-6);
});

test('export references actual separated textures, ordered parents and all four motion clips', () => {
  const directory = new URL('../public/characters/nova/', import.meta.url);
  const exported = JSON.parse(readFileSync(new URL('nova.spine.json', directory), 'utf8'));
  const seen = new Set<string>();
  for (const bone of exported.bones) {
    assert.ok(!bone.parent || seen.has(bone.parent)); seen.add(bone.name);
  }
  assert.deepEqual(Object.keys(exported.animations).sort(), ['cheer', 'dance', 'idle', 'jump']);
  for (const slot of exported.slots) {
    assert.ok(seen.has(slot.bone));
    for (const attachment of Object.values(exported.skins[0].attachments[slot.name]) as { path: string }[]) assert.ok(existsSync(new URL(`images/${attachment.path}.png`, directory)));
  }
  assert.ok(existsSync(new URL('nova.atlas', directory)) && existsSync(new URL('nova-rig.zip', directory)));
});
