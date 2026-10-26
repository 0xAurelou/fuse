import test from 'node:test';
import assert from 'node:assert/strict';
import { solveArmChain, type Point3 } from '../lib/vtuber-ik.ts';
import { vtuberPose } from '../lib/vtuber-motion.ts';
const distance = (a: Point3, b: Point3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

test('dance arm IK preserves both segment lengths and meets reachable targets', () => {
  for (const motion of ['idle', 'win', 'loss'] as const) for (let frame = 0; frame <= 480; frame++) {
    const pose = vtuberPose(motion, frame / 60);
    for (const [side, sign] of [['left', -1], ['right', 1]] as const) {
      const shoulder: Point3 = [sign * .20, 1.30, 0];
      const target = pose.hands[side].map((value, index) => value * 1.6 + (index === 1 ? 1.2 : 0)) as Point3;
      const { elbow, hand } = solveArmChain(shoulder, target, [sign * .5, 1.0, .15], .24, .22);
      assert.ok(Math.abs(distance(shoulder, elbow) - .24) < 1e-8);
      assert.ok(Math.abs(distance(elbow, hand) - .22) < 1e-8);
      if (distance(shoulder, target) < .459999 && distance(shoulder, target) > .020001) assert.ok(distance(hand, target) < 1e-8);
    }
  }
});

test('IK handles unreachable, coincident and straight pole targets without NaNs', () => {
  for (const target of [[0, 0, 0], [10, 0, 0], [0, 1, 0], [0, 0, 1]] as Point3[]) {
    const solved = solveArmChain([0, 0, 0], target, target, .24, .22);
    assert.ok([...solved.elbow, ...solved.hand].every(Number.isFinite));
    assert.ok(Math.abs(distance([0, 0, 0], solved.elbow) - .24) < 1e-8);
    assert.ok(Math.abs(distance(solved.elbow, solved.hand) - .22) < 1e-8);
  }
});
