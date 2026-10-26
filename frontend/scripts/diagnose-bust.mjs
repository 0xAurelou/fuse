// Diagnostic: are the raw J_Sec bust bones the same objects the skinned mesh
// follows, and does rotating them actually move skinned vertices?
import { readFileSync } from 'node:fs';
import { GLTFLoader } from '../node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '../node_modules/@pixiv/three-vrm/lib/three-vrm.module.js';

const original = readFileSync(new URL('../public/characters/victoria/avatar.vrm', import.meta.url));
const jsonLen = original.readUInt32LE(12);
const gltf = JSON.parse(original.toString('utf8', 20, 20 + jsonLen));
// Strip texture references so the GLTFLoader needs no image decoding in node.
const scrub = (value) => {
  if (Array.isArray(value)) { for (const item of value) scrub(item); return; }
  if (!value || typeof value !== 'object') return;
  for (const key of Object.keys(value)) {
    if (/texture/i.test(key)) delete value[key];
    else scrub(value[key]);
  }
};
scrub(gltf.materials);
if (gltf.extensions?.VRM?.materialProperties) scrub(gltf.extensions.VRM.materialProperties);
delete gltf.textures; delete gltf.images; delete gltf.samplers;
let json = Buffer.from(JSON.stringify(gltf), 'utf8');
const pad = (4 - (json.length % 4)) % 4;
json = Buffer.concat([json, Buffer.alloc(pad, 0x20)]);
const rest = original.subarray(20 + jsonLen); // remaining chunks (BIN)
const out = Buffer.alloc(12 + 8 + json.length + rest.length);
out.write('glTF', 0, 'ascii'); out.writeUInt32LE(2, 4); out.writeUInt32LE(out.length, 8);
out.writeUInt32LE(json.length, 12); out.writeUInt32LE(0x4E4F534A, 16);
json.copy(out, 20); rest.copy(out, 20 + json.length);

const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));
const parsed = await loader.parseAsync(out.buffer.slice(out.byteOffset, out.byteOffset + out.length), '');
const vrm = parsed.userData.vrm;

const normUpper = vrm.humanoid.getNormalizedBoneNode('upperChest');
const rawUpper = vrm.scene.getObjectByName('J_Bip_C_UpperChest');
console.log('normalized upperChest === raw J_Bip_C_UpperChest:', normUpper === rawUpper);
console.log('normalized upperChest parent:', normUpper?.parent?.name, '| raw parent:', rawUpper?.parent?.name);

const rawBust = vrm.scene.getObjectByName('J_Sec_L_Bust1');
console.log('raw bust found:', !!rawBust, '| parent:', rawBust?.parent?.name);

let host = null, boneIndex = -1, vertex = -1;
vrm.scene.traverse(object => {
  if (host || !object.isSkinnedMesh) return;
  const idx = object.skeleton.bones.indexOf(rawBust);
  if (idx < 0) return;
  const si = object.geometry.getAttribute('skinIndex'), sw = object.geometry.getAttribute('skinWeight');
  for (let v = 0; v < si.count; v++) {
    for (let c = 0; c < 4; c++) {
      if (si.getComponent(v, c) === idx && sw.getComponent(v, c) > .3) { host = object; boneIndex = idx; vertex = v; return; }
    }
  }
});
console.log('skinned host:', host?.name, '| boneIndex', boneIndex, '| vertex', vertex);

if (host && vertex >= 0) {
  const THREE = await import('../node_modules/three/build/three.module.js');
  const bone = host.skeleton.bones[boneIndex];
  console.log('skeleton bone[13]:', bone.name, '| same as rawBust:', bone === rawBust);
  let ancestor = bone, depth = 0, underScene = false;
  while (ancestor) { if (ancestor === vrm.scene) underScene = true; ancestor = ancestor.parent; depth++; }
  console.log('bone under vrm.scene:', underScene, '| depth', depth);
  let count = 0;
  vrm.scene.traverse(o => { if (o.name === 'J_Sec_L_Bust1') count++; });
  console.log('J_Sec_L_Bust1 instances under vrm.scene:', count);
  vrm.scene.updateMatrixWorld(true);
  bone.updateWorldMatrix(true, false);
  host.skeleton.update();
  const m0 = bone.matrixWorld.elements.slice();
  const read = () => {
    const p = host.geometry.getAttribute('position');
    return host.applyBoneTransform(vertex, new THREE.Vector3(p.getX(vertex), p.getY(vertex), p.getZ(vertex)));
  };
  const before = read();
  const restQ = bone.quaternion.clone();
  console.log('bone.matrixAutoUpdate:', bone.matrixAutoUpdate);
  bone.quaternion.copy(restQ).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), .3));
  if (!bone.matrixAutoUpdate) bone.updateMatrix();
  bone.updateWorldMatrix(true, false);
  vrm.scene.updateMatrixWorld(true);
  const m1 = bone.matrixWorld.elements.slice();
  console.log('bone matrixWorld changed:', m0.some((v, i) => Math.abs(v - m1[i]) > 1e-6));
  host.skeleton.update();
  const after = read();
  console.log('vertex world delta after .3 rad bust rotation:', before.distanceTo(after).toFixed(4));
  // And the reverse: does rotating the NORMALIZED upperChest move the raw one?
  const nu = normUpper.getWorldQuaternion(new THREE.Quaternion());
  const ru = rawUpper.getWorldQuaternion(new THREE.Quaternion());
  console.log('normalized vs raw upperChest world quat identical:', nu.equals(ru));
}
