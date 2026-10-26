// Code-only customization demo layer. Everything here is built at runtime from
// a CC0 base mesh: body-shape inflation, garment shells offset from the body
// surface, code-built accessories, and — when the model ships no bust bones —
// breast bones injected into the skeleton with vertices re-skinned to them,
// then driven by per-side springs owned here. No artist-authored assets are
// added; swapping the base model is a profile change.

export type BustSpringParams = { stiffness: number; damping: number };
export type BustSpringState = { angle: number; velocity: number };

export function createBustSpringState(): BustSpringState {
  return { angle: 0, velocity: 0 };
}

// Damped spring chasing a moving support (the parent bone's current offset from
// rest). The transient gap between support and angle is the visible jiggle:
// the breast trails the torso, overshoots, and settles.
export function stepBustSpring(state: BustSpringState, support: number, dt: number, params: BustSpringParams): number {
  const step = Math.min(Math.max(dt, 0), .05);
  const accel = -params.stiffness * (state.angle - support) - params.damping * state.velocity;
  state.velocity += accel * step;
  state.angle += state.velocity * step;
  return state.angle;
}

export type InflateProfile = { y0: number; y1: number; cy: number; cz: number; radius: number; xmax: number; amount: number };
export type ShellBand = { min: number; max: number; offset: number; plunge?: { depth: number; halfWidth: number; frontZ: number } };

export type CloneProfile = {
  // Existing bust bones to take over, or null to inject new ones at `inject`.
  bustBoneNames: [string, string] | null;
  inject: { y: number; z: number; sideX: number } | null;
  // Chest vertices re-skinned onto the injected bones (bind-space region).
  reskin: { y0: number; y1: number; cz: number; xmax: number; fraction: number };
  inflate: InflateProfile;
  bandeau: ShellBand;
  shorts: ShellBand;
  straps: { top: [number, number, number]; shoulder: [number, number, number] };
  hide: RegExp;
  garmentColor: string;
  // Flatten the body texture to plain skin (bases that paint clothing onto it).
  flattenBody: boolean;
  // Persistent extra mouth-`oh` morph so the clone's resting face differs.
  faceOh: number;
};

// Victoria Rubin (1.72m): ships J_Sec bust bones, long hair, and a body
// texture with proper painted skin/underwear under the dress.
export const VICTORIA_PROFILE: CloneProfile = {
  bustBoneNames: ['J_Sec_L_Bust1', 'J_Sec_R_Bust1'],
  inject: null,
  reskin: { y0: 1.2, y1: 1.38, cz: 0, xmax: .13, fraction: .45 },
  inflate: { y0: 1.14, y1: 1.40, cy: 1.27, cz: .02, radius: .18, xmax: .15, amount: .1 },
  bandeau: { min: 1.14, max: 1.34, offset: .0045, plunge: { depth: .075, halfWidth: .10, frontZ: .03 } },
  shorts: { min: .88, max: 1.0, offset: .004 },
  straps: { top: [-.052, 1.32, .12], shoulder: [-.10, 1.42, .03] },
  hide: /Tops_01_CLOTH/,
  garmentColor: '#8f1030',
  flattenBody: false,
  faceOh: .12,
};

// Sakurada Fumiriya (1.89m): anime-styled face, no bust bones — everything is
// injected and inflated in code. Scaled to the base model's height at load.
export const FUMIRIYA_PROFILE: CloneProfile = {
  bustBoneNames: null,
  inject: { y: 1.46, z: .055, sideX: .06 },
  reskin: { y0: 1.34, y1: 1.56, cz: .005, xmax: .14, fraction: .45 },
  inflate: { y0: 1.28, y1: 1.58, cy: 1.45, cz: .01, radius: .20, xmax: .17, amount: .11 },
  bandeau: { min: 1.33, max: 1.52, offset: .0045 },
  shorts: { min: .78, max: 1.0, offset: .004 },
  straps: { top: [-.06, 1.50, .12], shoulder: [-.11, 1.58, .03] },
  hide: /Tops_01_CLOTH|Bottoms_01_CLOTH|AccessoryNeck_01_CLOTH/,
  garmentColor: '#8f1030',
  flattenBody: true,
  faceOh: .12,
};

type Three = typeof import('three');
type VrmLike = {
  scene: import('three').Object3D;
  springBoneManager?: { joints: Set<{ bone: import('three').Object3D }>; deleteJoint(joint: { bone: import('three').Object3D }): void };
};

export type BustDrive = { id: string | null; excitement: number; pulse?: number };
export type CodeCustomDemo = { update(dt: number, drive: BustDrive): void };

type Sides = Array<{
  bone: import('three').Object3D;
  pitch: BustSpringState; lift: BustSpringState;
  pitchParams: BustSpringParams; liftParams: BustSpringParams; kick: number;
  restQuat?: import('three').Quaternion; restPos?: import('three').Vector3;
  parentRestQuat?: import('three').Quaternion; parentRestPos?: import('three').Vector3;
}>;

// Restyles the clone into an original character with code-only assets and
// attaches the owned bust physics. Returns null when the rig lacks the bones
// needed for the profile.
export function buildCodeCustomDemo(THREE: Three, avatar: VrmLike, profile: CloneProfile): CodeCustomDemo | null {
  for (const joint of avatar.springBoneManager?.joints || []) {
    if (/bust|breast/i.test(joint.bone.name)) avatar.springBoneManager?.deleteJoint(joint);
  }
  avatar.scene.updateMatrixWorld(true);

  let boneL: import('three').Object3D | null = null;
  let boneR: import('three').Object3D | null = null;
  if (profile.bustBoneNames) {
    boneL = avatar.scene.getObjectByName(profile.bustBoneNames[0]) ?? null;
    boneR = avatar.scene.getObjectByName(profile.bustBoneNames[1]) ?? null;
  } else if (profile.inject) {
    const injected = injectBustBones(THREE, avatar, profile);
    boneL = injected?.L || null;
    boneR = injected?.R || null;
  }
  if (!boneL || !boneR) return null;

  restyleClone(avatar, profile);
  const bodies = findBodyMeshes(THREE, avatar.scene);
  for (const body of bodies) {
    inflateBust(THREE, body, profile.inflate);
    buildGarmentShell(THREE, body, profile.bandeau, profile.garmentColor);
    buildGarmentShell(THREE, body, profile.shorts, '#101826');
  }
  addStraps(THREE, avatar, '#101826', profile.straps);
  addChoker(THREE, avatar, '#101826');

  const sides: Sides = [
    { bone: boneL, pitch: createBustSpringState(), lift: createBustSpringState(), pitchParams: { stiffness: 82, damping: 5.6 }, liftParams: { stiffness: 150, damping: 10 }, kick: 2.6 },
    { bone: boneR, pitch: createBustSpringState(), lift: createBustSpringState(), pitchParams: { stiffness: 98, damping: 6.8 }, liftParams: { stiffness: 150, damping: 10 }, kick: 2.2 },
  ];
  for (const side of sides) {
    side.restQuat = side.bone.quaternion.clone();
    side.restPos = side.bone.position.clone();
    side.parentRestQuat = side.bone.parent!.getWorldQuaternion(new THREE.Quaternion());
    side.parentRestPos = side.bone.parent!.getWorldPosition(new THREE.Vector3());
  }
  let lastId: string | null = null, fired = false, lastPulse = 0;
  const quat = new THREE.Quaternion(), forward = new THREE.Vector3(), axis = new THREE.Vector3(1, 0, 0), spin = new THREE.Quaternion();
  return {
    update(dt: number, drive: BustDrive) {
      if (drive.id !== lastId) { lastId = drive.id; fired = false; }
      if (drive.excitement > .5 && !fired) {
        fired = true;
        for (const side of sides) {
          side.pitch.velocity -= side.kick;
          side.lift.velocity -= side.kick * .8;
        }
      }
      // Beat sync: a sharp impulse on each pulse peak makes the bounce read,
      // not just lag. Rising edge only, so it fires once per beat.
      const pulse = drive.pulse ?? 0;
      if (pulse > .82 && lastPulse <= .82) {
        for (const side of sides) {
          side.pitch.velocity -= .55;
          side.lift.velocity -= .45;
        }
      }
      lastPulse = pulse;
      for (const side of sides) {
        side.bone.parent!.getWorldQuaternion(quat);
        quat.multiply(side.parentRestQuat!.clone().invert());
        forward.set(0, 0, 1).applyQuaternion(quat);
        const supportPitch = Math.atan2(forward.y, Math.hypot(forward.x, forward.z));
        const parentPos = side.bone.parent!.getWorldPosition(new THREE.Vector3());
        const supportLift = parentPos.y - side.parentRestPos!.y;
        stepBustSpring(side.pitch, supportPitch, dt, side.pitchParams);
        stepBustSpring(side.lift, supportLift, dt, side.liftParams);
        // Apply the lag error, not the absolute support: the parent transform
        // already carries the motion; the error is what the breast trails
        // with. Gain well above 1 makes the trail read at screen size.
        const pitchErr = (supportPitch - side.pitch.angle) * 2.4;
        const liftErr = supportLift - side.lift.angle;
        side.bone.quaternion.copy(side.restQuat!).multiply(spin.setFromAxisAngle(axis, -pitchErr));
        side.bone.position.set(side.restPos!.x, side.restPos!.y - liftErr * .9, side.restPos!.z);
        // three-vrm bones run with matrixAutoUpdate=false (the normalized
        // humanoid drives them through .matrix); recompose the local matrix
        // or the skin never sees the spring motion.
        side.bone.updateMatrix();
      }
    },
  };
}

// Creates two bones under the upper-chest bone, registers them in the host
// skinned mesh's skeleton, and transfers a fraction of the chest vertices'
// dominant skin weight onto them, so the new bones carry part of the bust.
function injectBustBones(THREE: Three, avatar: VrmLike, profile: CloneProfile): { L: import('three').Bone; R: import('three').Bone } | null {
  const upperChest = avatar.scene.getObjectByName('J_Bip_C_UpperChest');
  if (!upperChest || !profile.inject) return null;
  const hosts: import('three').SkinnedMesh[] = [];
  avatar.scene.traverse(object => {
    const mesh = object as import('three').SkinnedMesh;
    if (mesh.isSkinnedMesh && mesh.skeleton.bones.includes(upperChest as import('three').Bone)) hosts.push(mesh);
  });
  const host = hosts[0];
  if (!host) return null;
  const skeleton = host.skeleton;
  const bones: Record<'L' | 'R', import('three').Bone> = { L: new THREE.Bone(), R: new THREE.Bone() };
  bones.L.name = 'Code_Bust_L';
  bones.R.name = 'Code_Bust_R';
  // Place the bone origins at the inflated bust apex in upper-chest local space.
  for (const [key, side] of [['L', -1], ['R', 1]] as const) {
    const world = new THREE.Vector3(side * profile.inject.sideX, profile.inject.y, profile.inject.z);
    bones[key].position.copy(upperChest.worldToLocal(world.clone()));
    upperChest.add(bones[key]);
  }
  avatar.scene.updateMatrixWorld(true);
  skeleton.bones.push(bones.L, bones.R);
  skeleton.boneInverses.push(bones.L.matrixWorld.clone().invert(), bones.R.matrixWorld.clone().invert());
  skeleton.init();
  const indices = { L: skeleton.bones.length - 2, R: skeleton.bones.length - 1 };
  reskinBust(THREE, avatar, skeleton, indices, profile.reskin);
  return bones;
}

function reskinBust(THREE: Three, avatar: VrmLike, skeleton: import('three').Skeleton, indices: { L: number; R: number }, region: CloneProfile['reskin']) {
  avatar.scene.traverse(object => {
    const mesh = object as import('three').SkinnedMesh;
    if (!mesh.isSkinnedMesh || mesh.skeleton !== skeleton) return;
    const position = mesh.geometry.getAttribute('position');
    const skinIndex = mesh.geometry.getAttribute('skinIndex');
    const skinWeight = mesh.geometry.getAttribute('skinWeight');
    if (!position || !skinIndex || !skinWeight) return;
    for (let vertex = 0; vertex < position.count; vertex++) {
      const x = position.getX(vertex), y = position.getY(vertex), z = position.getZ(vertex);
      if (y < region.y0 || y > region.y1 || Math.abs(x) > region.xmax || z < region.cz) continue;
      const pairs: Array<{ bone: number; weight: number }> = [];
      let sum = 0;
      for (let c = 0; c < 4; c++) {
        const weight = skinWeight.getComponent(vertex, c);
        if (weight > 1e-4) { pairs.push({ bone: skinIndex.getComponent(vertex, c), weight }); sum += weight; }
      }
      if (!pairs.length || sum <= 0) continue;
      let donor = pairs[0];
      for (const pair of pairs) if (pair.weight > donor.weight) donor = pair;
      const transfer = donor.weight * region.fraction;
      if (transfer <= 1e-4) continue;
      donor.weight -= transfer;
      const target = x < 0 ? indices.L : indices.R;
      const existing = pairs.find(pair => pair.bone === target);
      if (existing) existing.weight += transfer;
      else pairs.push({ bone: target, weight: transfer });
      pairs.sort((a, b) => b.weight - a.weight);
      const top = pairs.slice(0, 4);
      const topSum = top.reduce((total, pair) => total + pair.weight, 0) || 1;
      for (let c = 0; c < 4; c++) {
        const pair = top[c];
        skinIndex.setComponent(vertex, c, pair ? pair.bone : 0);
        skinWeight.setComponent(vertex, c, pair ? pair.weight / topSum * sum : 0);
      }
    }
    skinIndex.needsUpdate = true;
    skinWeight.needsUpdate = true;
  });
}

function findBodyMeshes(THREE: Three, scene: import('three').Object3D) {
  const found: import('three').SkinnedMesh[] = [];
  scene.traverse(object => {
    const mesh = object as import('three').SkinnedMesh;
    if (mesh.isSkinnedMesh) {
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      if (materials.some(material => /Body_00_SKIN/.test(material.name))) found.push(mesh);
    }
  });
  return found;
}

// Pushes the chest-region skin vertices outward in bind space, before the
// garment shells are built, so the shells fit the inflated shape. Vertices
// re-skinned to bust bones are displaced the same way and keep following them.
function inflateBust(THREE: Three, body: import('three').SkinnedMesh, profile: InflateProfile) {
  const position = body.geometry.getAttribute('position');
  if (!position) return;
  for (let i = 0; i < position.count; i++) {
    const x = position.getX(i), y = position.getY(i), z = position.getZ(i);
    if (y < profile.y0 || y > profile.y1) continue;
    if (Math.abs(x) > profile.xmax || z < profile.cz) continue;
    const yFall = Math.sin((y - profile.y0) / (profile.y1 - profile.y0) * Math.PI);
    const dx = x, dz = z - profile.cz;
    const r = Math.hypot(dx, dz);
    if (r > profile.radius) continue;
    const weight = yFall * (1 - (r / profile.radius) ** 2);
    if (weight <= 0) continue;
    const push = profile.amount * weight / Math.max(r, 1e-4);
    const lift = y > profile.cy ? profile.amount * .25 * weight : 0;
    position.setXYZ(i, x + dx * push, y + lift, z + dz * push);
  }
  position.needsUpdate = true;
  body.geometry.computeBoundingSphere();
}

// Duplicates the body-surface triangles inside a bind-space height band,
// pushed outward along their normals, as a fitted shell with its own
// material. The shell is bound to the same skeleton, so every animation and
// the bust springs deform it for free.
function buildGarmentShell(THREE: Three, body: import('three').SkinnedMesh, band: ShellBand, color: string) {
  const source = body.geometry;
  const position = source.getAttribute('position');
  const normal = source.getAttribute('normal');
  const uv = source.getAttribute('uv');
  const skinIndex = source.getAttribute('skinIndex');
  const skinWeight = source.getAttribute('skinWeight');
  const index = source.getIndex();
  if (!normal || !skinIndex || !skinWeight || !index) return;
  const remap = new Map<number, number>();
  const outPos: number[] = [], outNor: number[] = [], outUv: number[] = [], outSkinIndex: number[] = [], outSkinWeight: number[] = [], outIndex: number[] = [];
  const inBand = (vertex: number) => {
    const y = position.getY(vertex);
    if (y < band.min || y > band.max) return false;
    // Plunging neckline: front-center vertices may sit lower than the band
    // top, cut deepest at the center and feathering out to the sides.
    if (band.plunge) {
      const x = position.getX(vertex), z = position.getZ(vertex);
      if (z > band.plunge.frontZ && Math.abs(x) < band.plunge.halfWidth) {
        const cut = band.max - band.plunge.depth * (1 - (x / band.plunge.halfWidth) ** 2);
        if (y > cut) return false;
      }
    }
    return true;
  };
  for (let tri = 0; tri < index.count; tri += 3) {
    const corners = [index.getX(tri), index.getX(tri + 1), index.getX(tri + 2)];
    if (!corners.every(inBand)) continue;
    for (const vertex of corners) {
      let target = remap.get(vertex);
      if (target === undefined) {
        target = outPos.length / 3;
        remap.set(vertex, target);
        const nx = normal.getX(vertex), ny = normal.getY(vertex), nz = normal.getZ(vertex);
        outPos.push(position.getX(vertex) + nx * band.offset, position.getY(vertex) + ny * band.offset, position.getZ(vertex) + nz * band.offset);
        outNor.push(nx, ny, nz);
        if (uv) outUv.push(uv.getX(vertex), uv.getY(vertex));
        outSkinIndex.push(skinIndex.getX(vertex), skinIndex.getY(vertex), skinIndex.getZ(vertex), skinIndex.getW(vertex));
        outSkinWeight.push(skinWeight.getX(vertex), skinWeight.getY(vertex), skinWeight.getZ(vertex), skinWeight.getW(vertex));
      }
      outIndex.push(target);
    }
  }
  if (!outIndex.length) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setIndex(outIndex);
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(outPos, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(outNor, 3));
  if (outUv.length) geometry.setAttribute('uv', new THREE.Float32BufferAttribute(outUv, 2));
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(outSkinIndex, 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(outSkinWeight, 4));
  geometry.computeBoundingSphere();
  const shell = new THREE.SkinnedMesh(geometry, new THREE.MeshStandardMaterial({ color, roughness: .3, metalness: .25, side: THREE.DoubleSide }));
  shell.name = 'CodeShellGarment';
  shell.frustumCulled = false;
  shell.bind(body.skeleton, body.bindMatrix);
  body.parent?.add(shell);
}

// Original-character restyle, code-only: blue hair, warm amber eyes, dark
// blue lashes/brows, rose lips, the opaque outfit hidden, and the body texture
// flattened to plain skin — this base model paints her uniform (collar, scarf,
// vest, skirt) onto the body texture itself, so hiding the cloth meshes is not
// enough; the shells and flat skin read as the revealing two-piece.
function restyleClone(avatar: VrmLike, profile: CloneProfile) {
  avatar.scene.traverse(object => {
    const mesh = object as unknown as { isMesh?: boolean; visible: boolean; material: import('three').Material | import('three').Material[] };
    if (!mesh.isMesh) return;
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) {
      const toon = material as import('three').Material & { color?: import('three').Color; shadeColorFactor?: import('three').Color; opacity?: number; map?: unknown };
      // Some sample models ship skin/hair as alpha-blended, which reads as
      // ghostly over the dark desk. Force the solid regions opaque; keep alpha
      // on lash/brow/line overlays whose textures need it.
      if (/SKIN|HAIR|EyeIris|EyeWhite/.test(material.name)) {
        material.transparent = false;
        material.depthWrite = true;
        if (typeof toon.opacity === 'number') toon.opacity = 1;
        material.needsUpdate = true;
      }
      if (profile.flattenBody && /Body_00_SKIN/.test(material.name)) {
        toon.map = null;
        toon.color?.set('#f2c9b8');
        toon.shadeColorFactor?.set('#d9a189');
        material.needsUpdate = true;
      }
      if (profile.hide.test(material.name)) mesh.visible = false;
      else if (/HAIR/.test(material.name)) { toon.color?.set('#5b8def'); toon.shadeColorFactor?.set('#33549e'); }
      else if (/EyeIris/.test(material.name)) toon.color?.set('#d9a545');
      else if (/FaceEyelash|FaceBrow/.test(material.name)) toon.color?.set('#2b3a67');
      else if (/FaceMouth/.test(material.name)) toon.color?.set('#c96a7e');
    }
  });
}

// Code-built long hair was tried here and removed: flat ribbon strands read
// as cardboard from the front. Long hair needs a base model that ships it.

// Simple choker around the neck bone.
function addChoker(THREE: Three, avatar: VrmLike, color: string) {
  const neck = avatar.scene.getObjectByName('J_Bip_C_Neck');
  if (!neck) return;
  avatar.scene.updateMatrixWorld(true);
  const neckPos = neck.getWorldPosition(new THREE.Vector3());
  const choker = new THREE.Mesh(new THREE.TorusGeometry(.045, .006, 8, 32), new THREE.MeshStandardMaterial({ color, roughness: .35, metalness: .3 }));
  choker.position.copy(neckPos);
  choker.rotation.x = Math.PI / 2;
  avatar.scene.add(choker);
  neck.attach(choker);
}

// Thin shoulder straps from the bandeau top over the shoulders, parented to
// the upper-chest bone so they follow the dance.
function addStraps(THREE: Three, avatar: VrmLike, color: string, straps: CloneProfile['straps']) {
  const anchor = avatar.scene.getObjectByName('J_Bip_C_UpperChest');
  if (!anchor) return;
  avatar.scene.updateMatrixWorld(true);
  const material = new THREE.MeshStandardMaterial({ color, roughness: .4, metalness: .1 });
  for (const side of [-1, 1]) {
    const top = new THREE.Vector3(side * Math.abs(straps.top[0]), straps.top[1], straps.top[2]);
    const shoulder = new THREE.Vector3(side * Math.abs(straps.shoulder[0]), straps.shoulder[1], straps.shoulder[2]);
    const strap = new THREE.Mesh(new THREE.CylinderGeometry(.0075, .0075, top.distanceTo(shoulder), 8), material);
    strap.position.copy(top).lerp(shoulder, .5);
    strap.lookAt(shoulder);
    strap.rotateX(Math.PI / 2);
    avatar.scene.add(strap);
    anchor.attach(strap);
  }
}
