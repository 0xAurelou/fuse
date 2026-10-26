// Diagnostic: verify the posed arm chain (shoulder -> elbow -> hand) stays
// connected and that skinned vertices follow their bones, across dance phases.
import { readFileSync } from 'node:fs';
import { GLTFLoader } from '../node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '../node_modules/@pixiv/three-vrm/lib/three-vrm.module.js';
import * as THREE from '../node_modules/three/build/three.module.js';
import { vtuberPose } from '../lib/vtuber-motion.ts';
import { solveArmChain } from '../lib/vtuber-ik.ts';

const original = readFileSync(new URL('../public/characters/victoria/avatar.vrm', import.meta.url));
const jsonLen = original.readUInt32LE(12);
const gltf = JSON.parse(original.toString('utf8', 20, 20 + jsonLen));
const scrub = (value) => {
  if (Array.isArray(value)) { for (const item of value) scrub(item); return; }
  if (!value || typeof value !== 'object') return;
  for (const key of Object.keys(value)) { if (/texture/i.test(key)) delete value[key]; else scrub(value[key]); }
};
scrub(gltf.materials);
if (gltf.extensions?.VRM?.materialProperties) scrub(gltf.extensions.VRM.materialProperties);
delete gltf.textures; delete gltf.images; delete gltf.samplers;
let json = Buffer.from(JSON.stringify(gltf), 'utf8');
json = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, 0x20)]);
const rest = original.subarray(20 + jsonLen);
const out = Buffer.alloc(12 + 8 + json.length + rest.length);
out.write('glTF', 0, 'ascii'); out.writeUInt32LE(2, 4); out.writeUInt32LE(out.length, 8);
out.writeUInt32LE(json.length, 12); out.writeUInt32LE(0x4E4F534A, 16);
json.copy(out, 20); rest.copy(out, 20 + json.length);

const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));
const parsed = await loader.parseAsync(out.buffer.slice(out.byteOffset, out.byteOffset + out.length), '');
const vrm = parsed.userData.vrm;
vrm.update(0);

const bones = new Map();
for (const name of Object.keys(vtuberPose('idle', 0).rotations)) {
  const node = vrm.humanoid.getNormalizedBoneNode(name);
  if (node) bones.set(name, node);
}
const torso = bones.get('chest') || bones.get('upperChest');
const hips = vrm.humanoid.getNormalizedBoneNode('hips');
const bounds = new THREE.Box3().setFromObject(vrm.scene);
const height = bounds.max.y - bounds.min.y;

function rotateDirection(bone, current, desired) {
  if (current.lengthSq() < 1e-10 || desired.lengthSq() < 1e-10) return;
  const delta = new THREE.Quaternion().setFromUnitVectors(current.normalize(), desired.normalize());
  const world = bone.getWorldQuaternion(new THREE.Quaternion());
  const parent = bone.parent?.getWorldQuaternion(new THREE.Quaternion()) || new THREE.Quaternion();
  bone.quaternion.copy(parent.invert().multiply(delta.multiply(world)));
  bone.updateWorldMatrix(false, true);
}
function aimBone(bone, child, target) {
  const origin = bone.getWorldPosition(new THREE.Vector3());
  rotateDirection(bone, child.getWorldPosition(new THREE.Vector3()).sub(origin), target.clone().sub(origin));
}
function poseArms(pose) {
  const anchor = torso.getWorldPosition(new THREE.Vector3());
  for (const side of ['left', 'right']) {
    const upper = bones.get(`${side}UpperArm`), lower = bones.get(`${side}LowerArm`), hand = bones.get(`${side}Hand`);
    const shoulder = upper.getWorldPosition(new THREE.Vector3());
    const elbow = lower.getWorldPosition(new THREE.Vector3());
    const tip = hand.getWorldPosition(new THREE.Vector3());
    const target = anchor.clone().add(new THREE.Vector3(...pose.hands[side]).multiplyScalar(height));
    const outward = Math.sign(shoulder.x - anchor.x) || (side === 'left' ? -1 : 1);
    const pole = shoulder.clone().add(new THREE.Vector3(outward * height * .20, -height * .15, height * .08));
    const solved = solveArmChain(shoulder.toArray(), target.toArray(), pole.toArray(), shoulder.distanceTo(elbow), elbow.distanceTo(tip));
    aimBone(upper, lower, new THREE.Vector3(...solved.elbow));
    aimBone(lower, hand, new THREE.Vector3(...solved.hand));
  }
}

// Skinned mesh + vertex pickers per bone, weighted > .5.
const host = (() => { let found = null; vrm.scene.traverse(o => { if (!found && o.isSkinnedMesh && o.name === 'Bodybaked') found = o; return; }); return found; })();
const vertexFor = (rawName) => {
  const idx = host.skeleton.bones.findIndex(b => b.name === rawName);
  const si = host.geometry.getAttribute('skinIndex'), sw = host.geometry.getAttribute('skinWeight');
  for (let v = 0; v < si.count; v++) for (let c = 0; c < 4; c++) if (si.getComponent(v, c) === idx && sw.getComponent(v, c) > .5) return v;
  return -1;
};
const upperV = vertexFor('J_Bip_L_UpperArm'), lowerV = vertexFor('J_Bip_L_LowerArm'), handV = vertexFor('J_Bip_L_Hand');
console.log('skin vertices picked: upper', upperV, 'lower', lowerV, 'hand', handV);
const skinAt = (v) => {
  const p = host.geometry.getAttribute('position');
  return host.applyBoneTransform(v, new THREE.Vector3(p.getX(v), p.getY(v), p.getZ(v)));
};

for (const t of [.5]) {
  const motion = process.argv[2] || 'idle';
  const reactionTime = Number(process.argv[3] || .5);
  const pose = vtuberPose(motion, t, 0, 0, reactionTime);
  for (const [name, node] of bones) node.rotation.set(...pose.rotations[name]);
  vrm.scene.updateMatrixWorld(true);
  poseArms(pose);
  vrm.update(0);
  vrm.scene.updateMatrixWorld(true);
  host.skeleton.update();
  const upper = bones.get('leftUpperArm'), lower = bones.get('leftLowerArm'), hand = bones.get('leftHand');
  const S = upper.getWorldPosition(new THREE.Vector3()), E = lower.getWorldPosition(new THREE.Vector3()), H = hand.getWorldPosition(new THREE.Vector3());
  const restUpper = host.skeleton.bones.find(b => b.name === upper.name);
  console.log(`t=${t}: shoulder->elbow ${S.distanceTo(E).toFixed(3)}m | elbow->hand ${E.distanceTo(H).toFixed(3)}m | shoulder at ${S.y.toFixed(2)}m`);
  console.log(`   skin->bone distance: upper ${skinAt(upperV).distanceTo(S).toFixed(3)} | lower ${skinAt(lowerV).distanceTo(E).toFixed(3)} | hand ${skinAt(handV).distanceTo(H).toFixed(3)}`);
  const anchor = torso.getWorldPosition(new THREE.Vector3());
  const target = anchor.clone().add(new THREE.Vector3(...pose.hands.left).multiplyScalar(height));
  console.log(`   hand target ${target.y.toFixed(2)}m | solved hand bone ${H.y.toFixed(2)}m | target reach error ${target.distanceTo(H).toFixed(3)}m | frame bottom ≈ ${(bounds.max.y - height * .215 - height * .26).toFixed(2)}m`);
  for (const side of ['left', 'right']) {
    for (const part of ['UpperArm', 'LowerArm', 'Hand']) {
      const node = bones.get(`${side}${part}`);
      const e = new THREE.Euler().setFromQuaternion(node.quaternion, 'XYZ');
      console.log(`   ${side}${part} euler: [${[e.x, e.y, e.z].map(v => v.toFixed(3)).join(', ')}]`);
    }
  }
}
