// Original pose interpretation of the linked POKEDANCE reference. No source
// motion data, model, music, or isolated chest animation is copied into the app.
export type VtuberMotion = 'idle' | 'entry' | 'win' | 'loss';
export type Rotation = [number, number, number];
export const REACTION_SECONDS = { entry: 5.2, win: 4.8, loss: 3.6 };
export const DANCE_BPM = 128;
export const DANCE_SECONDS = 8 * 60 / DANCE_BPM;
const KEYS = [
  { point: -1, hip: 1, level: 0 }, { point: 1, hip: -1, level: .01 },
  { point: -1, hip: 1, level: .015 }, { point: 1, hip: -1, level: -.005 },
  { point: -.6, hip: .7, level: .035 }, { point: .6, hip: -.7, level: .035 },
  { point: -1, hip: 1, level: .015 }, { point: 1, hip: -1, level: .005 },
];
const ease = (value: number) => { const u = Math.max(0, Math.min(1, value)); return u * u * (3 - 2 * u); };
function envelope(time: number, duration: number) {
  const edge = Math.max(0, Math.min(1, time / .35, (duration - time) / .65));
  return (1 - Math.cos(Math.PI * edge)) / 2;
}
export function reactionEnvelope(kind: keyof typeof REACTION_SECONDS, age: number) {
  return envelope(Math.max(0, age), REACTION_SECONDS[kind]);
}
export function dancePhase(time: number) {
  const beat = Math.max(0, time) * DANCE_BPM / 60;
  const index = Math.floor(beat) % KEYS.length, fraction = beat % 1;
  const a = KEYS[index], b = KEYS[(index + 1) % KEYS.length];
  // Hold readable pointing poses, then ease quickly into the next beat.
  const blend = ease((fraction - .58) / .42);
  return {
    point: a.point + (b.point - a.point) * blend,
    hip: a.hip + (b.hip - a.hip) * blend,
    level: a.level + (b.level - a.level) * blend,
    pulse: Math.sin(fraction * Math.PI) ** 2,
    beat,
  };
}
export function vtuberPose(motion: VtuberMotion, time: number, lookX = 0, lookY = 0, reactionTime = time) {
  const t = Math.max(0, time), phase = dancePhase(t);
  const entry = motion === 'entry' ? envelope(reactionTime, REACTION_SECONDS.entry) : 0;
  const win = motion === 'win' ? envelope(reactionTime, REACTION_SECONDS.win) : 0;
  const loss = motion === 'loss' ? envelope(reactionTime, REACTION_SECONDS.loss) : 0;
  const energy = 1 + entry * .3, pump = Math.sin(reactionTime * Math.PI * 4);
  const kissTime = Math.max(0, Math.min(1, reactionTime / REACTION_SECONDS.loss));
  const toMouth = ease(kissTime / .3) * (1 - ease((kissTime - .55) / .3));
  const blow = ease((kissTime - .5) / .35);
  const rotations: Record<string, Rotation> = {
    hips: [phase.pulse * .025, phase.hip * .055 * energy, phase.hip * .065 * energy],
    spine: [phase.pulse * .018, -phase.hip * .06, -phase.hip * .045 * energy],
    chest: [0, 0, phase.hip * .012],
    upperChest: [0, 0, 0],
    neck: [0, lookX * .04, loss * .07 * toMouth],
    head: [lookY * .06 - phase.pulse * .035, lookX * .1 - phase.point * .05 + loss * blow * .2, -phase.hip * .04 + win * pump * .03],
    // The renderer solves these arm chains to authored hand targets in 3D.
    leftUpperArm: [0, 0, 0], rightUpperArm: [0, 0, 0],
    leftLowerArm: [0, 0, 0], rightLowerArm: [0, 0, 0],
    leftHand: [0, 0, 0], rightHand: [0, 0, 0],
    leftUpperLeg: [Math.max(0, phase.hip) * .05, 0, -.025],
    rightUpperLeg: [Math.max(0, -phase.hip) * .05, 0, .025],
    leftLowerLeg: [phase.pulse * .06, 0, 0], rightLowerLeg: [phase.pulse * .06, 0, 0],
  };
  for (const [side, sign] of [['left', 1], ['right', -1]] as const) {
    // Two extended fingers and a thumb: the reference's side-pointing motif.
    for (const finger of ['Index', 'Middle', 'Ring', 'Little']) {
      const curl = finger === 'Ring' || finger === 'Little' ? 1 - win * .8 : 0;
      rotations[`${side}${finger}Proximal`] = [0, 0, sign * curl * .95];
      rotations[`${side}${finger}Intermediate`] = [0, 0, sign * curl * 1.1];
      rotations[`${side}${finger}Distal`] = [0, 0, sign * curl * .6];
    }
    rotations[`${side}ThumbMetacarpal`] = [0, sign * .2, sign * .15];
    rotations[`${side}ThumbProximal`] = [0, 0, 0];
    rotations[`${side}ThumbDistal`] = [0, 0, 0];
  }
  const handY = -.04 + phase.level + entry * phase.pulse * .012;
  const left: Rotation = [phase.point * .11 - .04, handY, .15];
  const right: Rotation = [phase.point * .11 + .04, handY + .015, .17];
  left[0] += (-.145 - left[0]) * win;
  right[0] += (.145 - right[0]) * win;
  left[1] += (.135 + pump * .018 - left[1]) * win;
  right[1] += (.135 - pump * .018 - right[1]) * win;
  right[0] += ((.02 * toMouth + .23 * blow) - right[0]) * loss;
  right[1] += ((.115 * toMouth + .075 * blow) - right[1]) * loss;
  return {
    rotations, hands: { left, right },
    point: phase.point * (1 - win), pointUp: win,
    x: phase.hip * .026 * energy,
    y: phase.pulse * .009 + entry * phase.pulse * .012 + win * Math.max(0, pump) * .032,
    turn: -.06 + phase.hip * .045,
    happy: .25 + phase.pulse * .04 + entry * .15 + win * .45 + loss * .15 * toMouth,
    sad: loss * .12, angry: 0, relaxed: 0,
    blink: Math.max(0, 1 - Math.abs((t % 4.8) - 4.55) / .12),
    wink: loss * .6 * toMouth,
    mouthOh: loss * .8 * toMouth,
    mouthAa: win * Math.max(0, pump) * .25 + loss * blow * .25,
  };
}
