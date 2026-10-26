// Original renderer-independent character data and animation math. This module
// contains no Spine runtime code. Native coordinates use +Y downward.
export type Motion = 'dance' | 'idle' | 'jump' | 'cheer';
export type Transform = { x: number; y: number; rotation: number };
export type Bone = Transform & { name: string; parent?: string; length?: number };
export type Attachment = { name: string; bone: string; image: string; x: number; y: number; width: number; height: number };
export type Pose = Record<string, Transform>;
export const CLIP_SECONDS: Record<Motion, number> = { dance: 4, idle: 4, jump: 1.4, cheer: 2.4 };
export const BONES: Bone[] = [
  { name: 'root', x: 0, y: 0, rotation: 0 },
  { name: 'hips', parent: 'root', x: 0, y: -306, rotation: 0 },
  { name: 'torso', parent: 'hips', x: 0, y: -35, rotation: 0 },
  { name: 'neck', parent: 'torso', x: 0, y: -164, rotation: 0 },
  { name: 'head', parent: 'neck', x: 0, y: -24, rotation: 0 },
  { name: 'hair-back', parent: 'head', x: 0, y: -50, rotation: 0 },
  { name: 'hair-left', parent: 'head', x: -51, y: -31, rotation: 0 },
  { name: 'hair-right', parent: 'head', x: 51, y: -31, rotation: 0 },
  { name: 'tail', parent: 'hips', x: 57, y: -20, rotation: 0 },
  { name: 'arm-left', parent: 'torso', x: -75, y: -144, rotation: 0, length: 106 },
  { name: 'forearm-left', parent: 'arm-left', x: 0, y: 106, rotation: 0, length: 105 },
  { name: 'arm-right', parent: 'torso', x: 75, y: -144, rotation: 0, length: 106 },
  { name: 'forearm-right', parent: 'arm-right', x: 0, y: 106, rotation: 0, length: 105 },
  { name: 'thigh-left', parent: 'hips', x: -50, y: 20, rotation: 0, length: 135 },
  { name: 'shin-left', parent: 'thigh-left', x: 0, y: 135, rotation: 0, length: 148 },
  { name: 'thigh-right', parent: 'hips', x: 50, y: 20, rotation: 0, length: 135 },
  { name: 'shin-right', parent: 'thigh-right', x: 0, y: 135, rotation: 0, length: 148 },
];
export const ATTACHMENTS: Attachment[] = [
  { name: 'back-hair', bone: 'hair-back', image: 'back-hair', x: 0, y: 125, width: 206, height: 300 },
  { name: 'coat-tail', bone: 'tail', image: 'coat-tail', x: 0, y: 45, width: 52, height: 108 },
  { name: 'thigh-left', bone: 'thigh-left', image: 'thigh-left', x: 0, y: 65, width: 76, height: 151 },
  { name: 'shin-left', bone: 'shin-left', image: 'shin-left', x: -5, y: 65, width: 72, height: 175 },
  { name: 'thigh-right', bone: 'thigh-right', image: 'thigh-right', x: 0, y: 65, width: 76, height: 151 },
  { name: 'shin-right', bone: 'shin-right', image: 'shin-right', x: 5, y: 65, width: 72, height: 175 },
  { name: 'pelvis', bone: 'hips', image: 'pelvis', x: 0, y: -6, width: 143, height: 94 },
  { name: 'arm-left', bone: 'arm-left', image: 'arm-left', x: 0, y: 51, width: 57, height: 124 },
  { name: 'forearm-left', bone: 'forearm-left', image: 'forearm-left', x: 0, y: 51, width: 47, height: 134 },
  { name: 'arm-right', bone: 'arm-right', image: 'arm-right', x: 0, y: 51, width: 57, height: 124 },
  { name: 'forearm-right', bone: 'forearm-right', image: 'forearm-right', x: 0, y: 51, width: 47, height: 134 },
  { name: 'torso', bone: 'torso', image: 'torso', x: 0, y: -76, width: 179, height: 198 },
  { name: 'face', bone: 'head', image: 'head-open', x: 0, y: -39, width: 135, height: 155 },
  { name: 'hair-left', bone: 'hair-left', image: 'hair-left', x: -3, y: 82, width: 42, height: 224 },
  { name: 'hair-right', bone: 'hair-right', image: 'hair-right', x: 3, y: 82, width: 42, height: 224 },
];

export function worldPose(pose: Pose): Pose {
  const out: Pose = {};
  for (const bone of BONES) {
    const local = pose[bone.name], parent = bone.parent ? out[bone.parent] : undefined;
    if (!parent) out[bone.name] = { ...local };
    else {
      const c = Math.cos(parent.rotation), s = Math.sin(parent.rotation);
      out[bone.name] = { x: parent.x + c * local.x - s * local.y, y: parent.y + s * local.x + c * local.y, rotation: parent.rotation + local.rotation };
    }
  }
  return out;
}

// Analytic two-bone inverse kinematics. The returned angles use a +Y rest axis.
export function solveLeg(x: number, y: number, bend: number, upper = 135, lower = 148) {
  const distance = Math.min(upper + lower - 1e-6, Math.max(Math.abs(upper - lower) + 1e-6, Math.hypot(x, y)));
  const knee = bend * Math.acos(Math.max(-1, Math.min(1, (distance * distance - upper * upper - lower * lower) / (2 * upper * lower))));
  const thigh = Math.atan2(y, x) - Math.atan2(lower * Math.sin(knee), upper + lower * Math.cos(knee)) - Math.PI / 2;
  return { thigh, knee };
}

export function samplePose(motion: Motion, seconds: number): Pose {
  const pose = Object.fromEntries(BONES.map(bone => [bone.name, { x: bone.x, y: bone.y, rotation: bone.rotation }])) as Pose;
  const t = Math.max(0, seconds), sway = Math.sin(Math.PI * t), beat = Math.sin(4 * Math.PI * t);
  let stepLeft = 0, stepRight = 0;
  pose['arm-left'].rotation = .16;
  pose['arm-right'].rotation = -.16;
  pose['forearm-left'].rotation = -.13;
  pose['forearm-right'].rotation = .13;
  if (motion === 'dance') {
    pose.hips.x = 12 * sway; pose.hips.y += 2 * beat; pose.hips.rotation = sway * .02;
    pose.torso.rotation = -sway * .08 + Math.sin(2 * Math.PI * t) * .025;
    pose.head.rotation = sway * .035;
    pose['arm-left'].rotation = .38 + sway * .62;
    pose['arm-right'].rotation = -.38 + sway * .62;
    pose['forearm-left'].rotation = -.65 + Math.sin(2 * Math.PI * t) * .36;
    pose['forearm-right'].rotation = .65 + Math.sin(2 * Math.PI * t) * .36;
    stepLeft = Math.max(0, sway) * 13; stepRight = Math.max(0, -sway) * 13;
  } else if (motion === 'idle') {
    pose.hips.y += Math.sin(Math.PI * t / 2) * 1.6;
    pose.torso.rotation = Math.sin(Math.PI * t / 2) * .012;
    pose.head.rotation = -Math.sin(Math.PI * t / 2) * .025;
  } else if (motion === 'jump') {
    const u = Math.min(1, t / CLIP_SECONDS.jump);
    const flight = Math.max(0, Math.sin(Math.PI * Math.max(0, Math.min(1, (u - .15) / .7))));
    pose.root.y = -118 * flight;
    pose.hips.y += u < .15 ? Math.sin(u / .15 * Math.PI) * 23 : u > .85 ? Math.sin((u - .85) / .15 * Math.PI) * 19 : 0;
    pose['arm-left'].rotation = .16 + flight * 2.4;
    pose['arm-right'].rotation = -.16 - flight * 2.4;
    pose['forearm-left'].rotation = -.13 - flight * .25;
    pose['forearm-right'].rotation = .13 + flight * .25;
  } else {
    const u = Math.min(1, t / CLIP_SECONDS.cheer);
    const lift = Math.pow(Math.sin(Math.PI * u), .65);
    pose['arm-left'].rotation = .16 + lift * 2.6;
    pose['arm-right'].rotation = -.16 - lift * 2.6;
    pose['forearm-left'].rotation = -.13 - lift * .4;
    pose['forearm-right'].rotation = .13 + lift * .4;
    pose.head.rotation = Math.sin(t * 8) * .035 * lift;
  }
  const world = worldPose(pose);
  for (const [side, sign, step] of [['left', -1, stepLeft], ['right', 1, stepRight]] as const) {
    const start = world[`thigh-${side}`];
    const target = { x: sign * 63, y: pose.root.y - 8 - step };
    const solved = solveLeg(target.x - start.x, target.y - start.y, sign);
    pose[`thigh-${side}`].rotation = solved.thigh - world.hips.rotation;
    pose[`shin-${side}`].rotation = solved.knee;
  }
  // Baked secondary-motion approximation is included in the interchange export.
  pose['hair-back'].rotation = -sway * .045;
  pose['hair-left'].rotation = -sway * .075 + Math.sin(2 * Math.PI * t) * .025;
  pose['hair-right'].rotation = -sway * .07 - Math.sin(2 * Math.PI * t) * .025;
  pose.tail.rotation = sway * .09;
  return pose;
}

export type Spring = { value: number; velocity: number };
export function stepSpring(spring: Spring, target: number, seconds: number): Spring {
  const dt = Math.max(0, Math.min(seconds, 1 / 15)), steps = Math.max(1, Math.ceil(dt * 120));
  let { value, velocity } = spring;
  for (let i = 0; i < steps; i++) {
    const h = dt / steps;
    velocity += ((target - value) * 105 - velocity * 15) * h;
    value += velocity * h;
  }
  return { value: Math.max(-.55, Math.min(.55, value)), velocity };
}
