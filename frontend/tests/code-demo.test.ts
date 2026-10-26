import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createBustSpringState, stepBustSpring } from '../lib/avatar-code-demo.ts';

test('clone base model is a self-contained CC0 VRM with the bones and materials the clone profile needs', () => {
  const bytes = readFileSync(new URL('../public/characters/fumiriya/avatar.vrm', import.meta.url));
  assert.equal(bytes.toString('ascii', 0, 4), 'glTF');
  assert.equal(bytes.readUInt32LE(8), bytes.length);
  const gltf = JSON.parse(bytes.toString('utf8', 20, 20 + bytes.readUInt32LE(12)));
  const vrm = gltf.extensions.VRM;
  assert.equal(vrm.meta.licenseName, 'CC0');
  assert.equal(vrm.meta.commercialUssageName, 'Allow');
  const names = gltf.nodes.map((node: { name?: string }) => node.name || '');
  assert.ok(names.includes('J_Bip_C_UpperChest'), 'clone injection needs the upper-chest bone');
  assert.ok(gltf.materials.some((material: { name?: string }) => /Body_00_SKIN/.test(material.name || '')), 'clone garments need the body skin mesh');
  assert.ok(gltf.materials.some((material: { name?: string }) => /Tops_01_CLOTH/.test(material.name || '')), 'clone restyle expects the tops material');
  for (const resource of [...gltf.buffers, ...gltf.images]) assert.ok(!resource.uri || resource.uri.startsWith('data:'));
});

const PARAMS = { stiffness: 90, damping: 7 };

test('bust spring rests at zero without support motion', () => {
  const state = createBustSpringState();
  for (let i = 0; i < 600; i++) stepBustSpring(state, 0, 1 / 60, PARAMS);
  assert.equal(state.angle, 0);
  assert.equal(state.velocity, 0);
});

test('bust spring trails a support step, overshoots, and settles onto it', () => {
  const state = createBustSpringState();
  let peak = 0;
  for (let i = 0; i < 120; i++) {
    stepBustSpring(state, .2, 1 / 60, PARAMS);
    peak = Math.max(peak, state.angle);
  }
  // Under-damped (damping ratio ~0.37): the spring must overshoot the .2 support.
  assert.ok(peak > .21, `expected overshoot past .2, got ${peak}`);
  assert.ok(Math.abs(state.angle - .2) < .02, `expected settle near .2, got ${state.angle}`);
  for (let i = 0; i < 180; i++) stepBustSpring(state, .2, 1 / 60, PARAMS);
  assert.ok(Math.abs(state.angle - .2) < 1e-3);
});

test('bust spring decays to rest when the support returns to zero', () => {
  const state = createBustSpringState();
  for (let i = 0; i < 180; i++) stepBustSpring(state, .2, 1 / 60, PARAMS);
  for (let i = 0; i < 600; i++) stepBustSpring(state, 0, 1 / 60, PARAMS);
  assert.ok(Math.abs(state.angle) < 1e-3);
  assert.ok(Math.abs(state.velocity) < 1e-2);
});

test('bust spring clamps huge dt and never diverges', () => {
  const state = createBustSpringState();
  stepBustSpring(state, .5, 10, PARAMS);
  assert.ok(Number.isFinite(state.angle) && Math.abs(state.angle) < 1);
  for (let i = 0; i < 60; i++) stepBustSpring(state, 0, 1 / 60, PARAMS);
  assert.ok(Number.isFinite(state.angle));
});

test('per-side parameters de-phase left and right springs', () => {
  const left = createBustSpringState(), right = createBustSpringState();
  const leftParams = { stiffness: 82, damping: 6.4 }, rightParams = { stiffness: 98, damping: 7.8 };
  let maxGap = 0;
  for (let i = 0; i < 90; i++) {
    stepBustSpring(left, .2, 1 / 60, leftParams);
    stepBustSpring(right, .2, 1 / 60, rightParams);
    maxGap = Math.max(maxGap, Math.abs(left.angle - right.angle));
  }
  assert.ok(maxGap > 1e-3, `expected per-side de-phasing, max gap ${maxGap}`);
});
