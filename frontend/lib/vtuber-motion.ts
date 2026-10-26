// Original classical club choreography: smooth continuous waves — side sways,
// per-beat bobs, flowing arm arcs and slow phrase breathing. No keyframed
// poses, no pointing; everything is sinusoidal so any phase reads natural.
// Reactions (entry / win / loss) ride on top and vanish exactly at their
// envelope edges.
export type VtuberMotion = 'idle' | 'entry' | 'win' | 'loss';
export type Rotation = [number, number, number];
export const REACTION_SECONDS = { entry: 5.2, win: 4.8, loss: 3.6 };
export const DANCE_BPM = 128;
export const DANCE_SECONDS = 8 * 60 / DANCE_BPM;
const BEAT = Math.PI * 2 * DANCE_BPM / 60;
const ease = (value: number) => { const u = Math.max(0, Math.min(1, value)); return u * u * (3 - 2 * u); };
function envelope(time: number, duration: number) {
  const edge = Math.max(0, Math.min(1, time / .35, (duration - time) / .65));
  return (1 - Math.cos(Math.PI * edge)) / 2;
}
export function reactionEnvelope(kind: keyof typeof REACTION_SECONDS, age: number) {
  return envelope(Math.max(0, age), REACTION_SECONDS[kind]);
}
// Smooth phrase signals: sway (2-beat side drift), bob (per-beat), pulse
// (per-beat bump 0..1), flow (whole-phrase breathing). All periodic within
// DANCE_SECONDS.
export function dancePhase(time: number) {
  const t = Math.max(0, time), w = t * BEAT;
  return {
    sway: Math.sin(w * .5),
    bob: Math.sin(w),
    pulse: (1 - Math.cos(w)) / 2,
    flow: Math.sin(w * .25 + 1),
    beat: w / Math.PI,
  };
}
export function vtuberPose(motion: VtuberMotion, time: number, lookX = 0, lookY = 0, reactionTime = time) {
  const t = Math.max(0, time), { sway, bob, pulse, flow } = dancePhase(t);
  const entry = motion === 'entry' ? envelope(reactionTime, REACTION_SECONDS.entry) : 0;
  const win = motion === 'win' ? envelope(reactionTime, REACTION_SECONDS.win) : 0;
  const loss = motion === 'loss' ? envelope(reactionTime, REACTION_SECONDS.loss) : 0;
  const energy = 1 + entry * .3, pump = Math.sin(reactionTime * Math.PI * 4);
  const kissTime = Math.max(0, Math.min(1, reactionTime / REACTION_SECONDS.loss));
  const toMouth = ease(kissTime / .3) * (1 - ease((kissTime - .55) / .3));
  const blow = ease((kissTime - .5) / .35);
  const lag = Math.sin(t * BEAT * .5 - .35);
  const rotations: Record<string, Rotation> = {
    hips: [pulse * .03 * energy + flow * .008, sway * .075 * energy, sway * .07 * energy],
    spine: [pulse * .02, -sway * .065 * energy, -lag * .05 * energy],
    chest: [pulse * .04 + flow * .01, 0, sway * .014],
    upperChest: [pulse * .03, 0, sway * .01],
    neck: [0, lookX * .04, sway * .02 + loss * .07 * toMouth],
    head: [lookY * .06 - pulse * .03, lookX * .1 + sway * .055 + loss * blow * .2, -sway * .045 + win * pump * .03],
    // The renderer solves these arm chains to authored hand targets in 3D.
    leftUpperArm: [0, 0, 0], rightUpperArm: [0, 0, 0],
    leftLowerArm: [0, 0, 0], rightLowerArm: [0, 0, 0],
    leftHand: [0, 0, 0], rightHand: [0, 0, 0],
    leftUpperLeg: [Math.max(0, sway) * .06, 0, -.02],
    rightUpperLeg: [Math.max(0, -sway) * .06, 0, .02],
    leftLowerLeg: [pulse * .09, 0, 0], rightLowerLeg: [pulse * .09, 0, 0],
  };
  for (const [side, sign] of [['left', 1], ['right', -1]] as const) {
    // Soft hands: a gentle breathing curl on the outer fingers only.
    const curl = .12 + .08 * Math.sin(t * BEAT * .5 + sign);
    for (const finger of ['Ring', 'Little']) {
      rotations[`${side}${finger}Proximal`] = [0, 0, sign * curl * .55];
      rotations[`${side}${finger}Intermediate`] = [0, 0, sign * curl * .6];
    }
    rotations[`${side}ThumbMetacarpal`] = [0, sign * .18, sign * .12];
    rotations[`${side}ThumbProximal`] = [0, 0, 0];
    rotations[`${side}ThumbDistal`] = [0, 0, 0];
  }
  // Flowing arm arcs: hands drift side to side over two beats, breathe up and
  // down on the beat, and arc forward/back in unison — a classic smooth sway.
  const drift = .05 * Math.sin(t * BEAT * .5 + .6);
  const lift = .045 * Math.sin(t * BEAT + 1.1);
  const arc = .04 * Math.cos(t * BEAT * .5 + .6);
  const handY = -.17 + lift + entry * (pulse * .02 + .05);
  const left: Rotation = [-.13 - drift, handY, .12 + arc];
  const right: Rotation = [.13 + drift, handY, .12 + arc];
  // Win: both hands rise beside the head, pumping softly in opposition.
  left[0] += (-.15 - left[0]) * win;
  right[0] += (.15 - right[0]) * win;
  left[1] += (.14 + pump * .02 - left[1]) * win;
  right[1] += (.14 - pump * .02 - right[1]) * win;
  // Loss: right hand blows a kiss; left keeps dancing.
  right[0] += ((.02 * toMouth + .23 * blow) - right[0]) * loss;
  right[1] += ((.115 * toMouth + .075 * blow) - right[1]) * loss;
  return {
    rotations, hands: { left, right },
    point: 0, pointUp: win,
    x: sway * .028 * energy,
    // Weight drops on the beat (pulse²) and recovers after — grounded, not floating.
    y: -pulse * pulse * .014 + flow * .002 + entry * pulse * .012 + win * Math.max(0, pump) * .032,
    turn: sway * .05 + flow * .01,
    happy: .25 + pulse * .05 + entry * .15 + win * .45 + loss * .15 * toMouth,
    sad: loss * .12, angry: 0, relaxed: 0,
    blink: Math.max(0, 1 - Math.abs((t % 4.8) - 4.55) / .12),
    wink: loss * .6 * toMouth,
    mouthOh: loss * .8 * toMouth,
    mouthAa: win * Math.max(0, pump) * .25 + loss * blow * .25,
  };
}
