import type { VRM, VRMHumanBoneName } from '@pixiv/three-vrm';
import type { Object3D, Mesh, Material, Color, Vector3 } from 'three';
import { REACTION_SECONDS, dancePhase, reactionEnvelope, vtuberPose } from './vtuber-motion';
import type { AvatarReaction } from './avatar-events';
import { solveArmChain, type Point3 } from './vtuber-ik';
import { buildCodeCustomDemo, VICTORIA_PROFILE, type CloneProfile, type CodeCustomDemo } from './avatar-code-demo';

export type CharacterOptions = { playing: boolean; reaction: AvatarReaction | null };
export type CharacterRenderer = { setOptions: (options: CharacterOptions) => void; destroy: () => void };

type ThreeModule = typeof import('three');

type Rig = {
  avatar: VRM;
  bones: Map<string, Object3D>;
  hips: Object3D | null;
  hipsOrigin: Vector3 | null;
  torso: Object3D | null;
  baseTurn: number;
  demo: CodeCustomDemo | null;
  faceOh: number;
};

export async function createCharacterRenderer(host: HTMLDivElement, initial: CharacterOptions, signal: AbortSignal): Promise<CharacterRenderer | null> {
  const [THREE, { GLTFLoader }, { VRMLoaderPlugin, VRMUtils }] = await Promise.all([
    import('three'), import('three/addons/loaders/GLTFLoader.js'), import('@pixiv/three-vrm'),
  ]);
  if (signal.aborted) return null;
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const canvas = renderer.domElement;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'A 3D anime VTuber avatar, customized at load by code');
  host.appendChild(canvas);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-.5, .5, .5, -.5, .01, 20);
  scene.add(new THREE.HemisphereLight(0xffeefa, 0x7775a5, 2));
  const key = new THREE.DirectionalLight(0xfff5ed, 2.2); key.position.set(-1, 2, 3); scene.add(key);
  const rim = new THREE.DirectionalLight(0xc5b7ff, 1); rim.position.set(2, 1, -1); scene.add(rim);

  let avatar: VRM | undefined;
  try {
    const response = await fetch('/characters/victoria/avatar.vrm', { signal });
    if (!response.ok) throw new Error('Avatar download failed');
    const bytes = await response.arrayBuffer();
    if (signal.aborted) { renderer.dispose(); canvas.remove(); return null; }
    const loader = new GLTFLoader();
    loader.register(parser => new VRMLoaderPlugin(parser));
    const gltf = await loader.parseAsync(bytes, '');
    avatar = gltf.userData.vrm as VRM | undefined;
    if (!avatar) throw new Error('Avatar contains no VRM rig');
    if (signal.aborted) {
      VRMUtils.deepDispose(avatar.scene);
      renderer.dispose(); canvas.remove(); return null;
    }
  } catch (error) {
    if (avatar) VRMUtils.deepDispose(avatar.scene);
    renderer.dispose(); canvas.remove(); throw error;
  }

  // Keep the supplied model geometry/textures; restyle clothing as glossy
  // clubwear, keep the desk palette for hair. Per-rig accents distinguish the
  // base model from the code-only demo copy.
  function restyle(vrm: VRM, accents: { cloth: string; rim: string; hair: string; hairShade: string }) {
    vrm.scene.traverse(object => {
      object.frustumCulled = false;
      const mesh = object as Mesh;
      if (!mesh.isMesh) return;
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        const toon = material as Material & { color?: Color; shadeColorFactor?: Color; rimColor?: Color; shadingToonyFactor?: number };
        if (material.name.includes('Tops_01_CLOTH')) {
          toon.color?.set(accents.cloth); toon.shadeColorFactor?.set('#070409');
          toon.rimColor?.set(accents.rim); if (typeof toon.shadingToonyFactor === 'number') toon.shadingToonyFactor = 1;
        } else if (material.name.includes('Shoes_01_CLOTH')) {
          toon.color?.set('#140d12'); toon.shadeColorFactor?.set('#050306');
        } else if (material.name.includes('HAIR')) {
          toon.color?.set(accents.hair); toon.shadeColorFactor?.set(accents.hairShade);
        }
      }
    });
  }

  function addHeadphones(vrm: VRM, height: number, accent: string) {
    const head = vrm.humanoid.getRawBoneNode('head');
    if (!head) return;
    const headphones = new THREE.Group(), radius = height * .077;
    const shell = new THREE.MeshStandardMaterial({ color: '#201d32', roughness: .45, metalness: .4 });
    const accentMaterial = new THREE.MeshBasicMaterial({ color: accent });
    const band = new THREE.Mesh(new THREE.TorusGeometry(radius, radius * .06, 8, 40, Math.PI), shell);
    band.position.y = radius * .75; headphones.add(band);
    for (const side of [-1, 1]) {
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(radius * .30, radius * .30, radius * .28, 20), shell);
      cup.rotation.z = Math.PI / 2; cup.position.set(side * radius, radius * .73, 0); headphones.add(cup);
      const light = new THREE.Mesh(new THREE.TorusGeometry(radius * .22, radius * .025, 6, 24), accentMaterial);
      light.rotation.y = Math.PI / 2; light.position.set(side * radius * 1.15, radius * .73, 0); headphones.add(light);
    }
    head.add(headphones);
  }

  // Retain hair/clothing springs; bust bones are driven per rig below.
  function makeRig(vrm: VRM, baseX: number, accents: { cloth: string; rim: string; hair: string; hairShade: string; phones: string }, profile: CloneProfile | null): Rig {
    for (const joint of vrm.springBoneManager?.joints || []) {
      if (/bust|breast/i.test(joint.bone.name)) vrm.springBoneManager?.deleteJoint(joint);
    }
    VRMUtils.rotateVRM0(vrm);
    vrm.scene.position.x = baseX;
    scene.add(vrm.scene);
    restyle(vrm, accents);
    const baseTurn = vrm.scene.rotation.y;
    const bones = new Map<string, Object3D>();
    for (const name of Object.keys(vtuberPose('idle', 0).rotations)) {
      const node = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (node) bones.set(name, node);
    }
    const hips = vrm.humanoid.getNormalizedBoneNode('hips');
    return {
      avatar: vrm, bones,
      hips: hips ?? null, hipsOrigin: hips?.position.clone() || null,
      torso: bones.get('chest') ?? bones.get('upperChest') ?? bones.get('spine') ?? null,
      baseTurn,
      demo: profile ? buildCodeCustomDemo(THREE, vrm, profile) : null,
      faceOh: profile?.faceOh ?? 0,
    };
  }

  const bounds = new THREE.Box3().setFromObject(avatar.scene);
  const height = bounds.max.y - bounds.min.y;
  const centerY = bounds.max.y - height * .225;
  // Extra transparent room on the left contains the dance gestures while the
  // body stays near the right edge, like a streamer overlay.
  const frameHeight = height * .55;
  camera.position.set(-height * .06, centerY, 3);
  camera.lookAt(-height * .06, centerY, 0);
  const rigs = [
    makeRig(avatar, 0, { cloth: '#101826', rim: '#7fb2ff', hair: '#5b8def', hairShade: '#33549e', phones: '#7fd4ff' }, VICTORIA_PROFILE),
  ];
  for (const rig of rigs) addHeadphones(rig.avatar, height, '#7fd4ff');

  // Breast grab: pointer-down near a bust bone (raycast proximity) starts a
  // hold; dragging moves the spring support so the breast follows with lag,
  // and releasing lets the springs jiggle back with the drag momentum.
  const raycaster = new THREE.Raycaster();
  const bustBones = [
    avatar.scene.getObjectByName('J_Sec_L_Bust1'),
    avatar.scene.getObjectByName('J_Sec_R_Bust1'),
  ];
  let grabSide = -1, grabAnchorX = 0, grabAnchorY = 0, grabY = 0, grabX = 0;
  function ndcOf(event: PointerEvent) {
    const rect = canvas.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) return null;
    return new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
  }
  function bustSideAt(event: PointerEvent) {
    const ndc = ndcOf(event);
    if (!ndc) return -1;
    raycaster.setFromCamera(ndc, camera);
    let best = -1, bestDist = height * .09;
    bustBones.forEach((bone, i) => {
      if (!bone) return;
      const dist = raycaster.ray.distanceToPoint(bone.getWorldPosition(new THREE.Vector3()));
      if (dist < bestDist) { bestDist = dist; best = i; }
    });
    return best;
  }
  function pointerDown(event: PointerEvent) {
    if (grabSide >= 0 || !options.playing || reduced.matches) return;
    if ((event.target as HTMLElement | null)?.closest?.('.vtuber-toolbar, .vtuber-credits')) return;
    const side = bustSideAt(event);
    if (side < 0) return;
    grabSide = side;
    grabAnchorX = event.clientX;
    grabAnchorY = event.clientY;
    grabX = 0; grabY = 0;
    canvas.style.cursor = '';
    document.body.style.cursor = 'grabbing';
    // The canvas passes pointer events through to the desk by design; a
    // capture-phase stop keeps a grab from also clicking whatever is behind.
    event.preventDefault();
    event.stopPropagation();
  }
  function releaseGrab() {
    grabSide = -1;
    grabX = 0; grabY = 0;
    document.body.style.cursor = '';
  }

  function rotateDirection(bone: Object3D, current: Vector3, desired: Vector3) {
    if (current.lengthSq() < 1e-10 || desired.lengthSq() < 1e-10) return;
    const delta = new THREE.Quaternion().setFromUnitVectors(current.normalize(), desired.normalize());
    const world = bone.getWorldQuaternion(new THREE.Quaternion());
    const parent = bone.parent?.getWorldQuaternion(new THREE.Quaternion()) || new THREE.Quaternion();
    bone.quaternion.copy(parent.invert().multiply(delta.multiply(world)));
    bone.updateWorldMatrix(false, true);
  }
  function aimBone(bone: Object3D, child: Object3D, target: Vector3) {
    const origin = bone.getWorldPosition(new THREE.Vector3());
    rotateDirection(bone, child.getWorldPosition(new THREE.Vector3()).sub(origin), target.clone().sub(origin));
  }
  function poseArms(rig: Rig, pose: Pick<ReturnType<typeof vtuberPose>, 'hands' | 'point' | 'pointUp'>) {
    if (!rig.torso) return;
    const anchor = rig.torso.getWorldPosition(new THREE.Vector3());
    for (const side of ['left', 'right'] as const) {
      const upper = rig.bones.get(`${side}UpperArm`), lower = rig.bones.get(`${side}LowerArm`), hand = rig.bones.get(`${side}Hand`);
      if (!upper || !lower || !hand) continue;
      const shoulder = upper.getWorldPosition(new THREE.Vector3());
      const elbow = lower.getWorldPosition(new THREE.Vector3());
      const tip = hand.getWorldPosition(new THREE.Vector3());
      const offset = pose.hands[side];
      const target = anchor.clone().add(new THREE.Vector3(...offset).multiplyScalar(height));
      const outward = Math.sign(shoulder.x - anchor.x) || (side === 'left' ? -1 : 1);
      const pole = shoulder.clone().add(new THREE.Vector3(outward * height * .20, -height * .15, height * .08));
      const solved = solveArmChain(shoulder.toArray() as Point3, target.toArray() as Point3, pole.toArray() as Point3, shoulder.distanceTo(elbow), elbow.distanceTo(tip));
      aimBone(upper, lower, new THREE.Vector3(...solved.elbow));
      aimBone(lower, hand, new THREE.Vector3(...solved.hand));
      const index = rig.bones.get(`${side}IndexProximal`), joint = rig.bones.get(`${side}IndexIntermediate`);
      if (index && joint) {
        const finger = joint.getWorldPosition(new THREE.Vector3()).sub(index.getWorldPosition(new THREE.Vector3()));
        rotateDirection(hand, finger, new THREE.Vector3(pose.point, .12 + pose.pointUp, .3));
      }
    }
  }
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let options = { ...initial }, elapsed = 0, alive = true, frame = 0, previous = 0;
  let pointerX = 0, pointerY = 0, lookX = 0, lookY = 0;
  function draw(dt: number) {
    if (!alive) return;
    const active = options.playing && !reduced.matches;
    if (active) elapsed += dt;
    const blend = dt ? 1 - Math.exp(-dt * 5) : 1;
    lookX += ((active ? pointerX : 0) - lookX) * blend;
    lookY += ((active ? pointerY : 0) - lookY) * blend;
    const reaction = options.reaction;
    const age = reaction ? Math.max(0, (Date.now() - reaction.at) / 1000) : 0;
    const motion = !reduced.matches && reaction && age < REACTION_SECONDS[reaction.kind] ? reaction.kind : 'idle';
    const pose = vtuberPose(motion, reduced.matches ? 0 : elapsed, lookX, lookY, age);
    const excitement = motion === 'win' ? reactionEnvelope('win', age) : 0;
    for (const rig of rigs) {
      rig.avatar.scene.rotation.y = rig.baseTurn + pose.turn;
      for (const [name, rotation] of Object.entries(pose.rotations)) {
        const node = rig.bones.get(name);
        if (node) node.rotation.set(...rotation);
      }
      if (rig.hips && rig.hipsOrigin) rig.hips.position.set(rig.hipsOrigin.x + pose.x, rig.hipsOrigin.y + pose.y, rig.hipsOrigin.z);
      // IK owns the arms only for win/loss gestures; the classic dance drives
      // arms by baked rotations (always connected to the torso chain).
      if (pose.ikArms > 1e-3) poseArms(rig, pose);
      rig.avatar.expressionManager?.setValue('happy', pose.happy);
      rig.avatar.expressionManager?.setValue('sad', pose.sad);
      rig.avatar.expressionManager?.setValue('angry', pose.angry);
      rig.avatar.expressionManager?.setValue('blink', pose.blink);
      rig.avatar.expressionManager?.setValue('blinkRight', pose.wink);
      rig.avatar.expressionManager?.setValue('oh', Math.min(1, pose.mouthOh + rig.faceOh));
      rig.avatar.expressionManager?.setValue('aa', pose.mouthAa);
      rig.avatar.update(dt);
      rig.demo?.update(dt, {
        id: reaction?.id ?? null, excitement,
        pulse: reduced.matches ? 0 : dancePhase(elapsed).pulse,
        grab: grabSide >= 0 ? { side: grabSide, y: grabY, x: grabX } : null,
      });
    }
    renderer.render(scene, camera);
  }
  function tick(now: number) {
    frame = 0;
    if (!alive || !options.playing || reduced.matches || document.hidden) return;
    if (!previous || now - previous >= 1000 / 30) {
      draw(previous ? Math.min((now - previous) / 1000, .05) : 0);
      previous = now;
    }
    frame = requestAnimationFrame(tick);
  }
  function activity() {
    cancelAnimationFrame(frame); frame = 0; previous = 0;
    if (alive && options.playing && !reduced.matches && !document.hidden) frame = requestAnimationFrame(tick);
    else draw(0);
  }
  function resize() {
    if (!alive) return;
    const width = Math.max(1, host.clientWidth), canvasHeight = Math.max(1, host.clientHeight), half = frameHeight / 2;
    camera.left = -half * width / canvasHeight; camera.right = -camera.left;
    camera.top = half; camera.bottom = -half; camera.updateProjectionMatrix();
    renderer.setSize(width, canvasHeight); draw(0);
  }
  function pointer(event: PointerEvent) {
    pointerX = Math.max(-1, Math.min(1, event.clientX / window.innerWidth * 2 - 1));
    pointerY = Math.max(-1, Math.min(1, event.clientY / window.innerHeight * 2 - 1));
    if (grabSide >= 0) {
      // Drag in world units: vertical pull, horizontal sway; the springs
      // chase the moving support and overshoot on release.
      const worldPerPixel = frameHeight / Math.max(1, canvas.clientHeight);
      grabY = Math.max(-height * .035, Math.min(height * .035, (grabAnchorY - event.clientY) * worldPerPixel));
      grabX = Math.max(-height * .07, Math.min(height * .07, (event.clientX - grabAnchorX) * worldPerPixel));
      return;
    }
    document.body.style.cursor = options.playing && !reduced.matches && bustSideAt(event) >= 0 ? 'grab' : '';
  }
  function resetPointer() { pointerX = 0; pointerY = 0; releaseGrab(); }
  const observer = new ResizeObserver(resize); observer.observe(host);
  window.addEventListener('pointermove', pointer, { passive: true });
  window.addEventListener('pointerdown', pointerDown, { capture: true });
  window.addEventListener('pointerup', releaseGrab);
  window.addEventListener('blur', resetPointer);
  document.addEventListener('visibilitychange', activity);
  reduced.addEventListener('change', activity);
  draw(0);
  for (const rig of rigs) for (let i = 0; i < 30; i++) rig.avatar.update(1 / 60);
  elapsed = 0; resize(); activity();
  return {
    setOptions(next) {
      options = { ...next }; draw(0); activity();
    },
    destroy() {
      if (!alive) return;
      alive = false; cancelAnimationFrame(frame); observer.disconnect();
      window.removeEventListener('pointermove', pointer); window.removeEventListener('blur', resetPointer);
      window.removeEventListener('pointerdown', pointerDown, { capture: true }); window.removeEventListener('pointerup', releaseGrab);
      document.removeEventListener('visibilitychange', activity); reduced.removeEventListener('change', activity);
      for (const rig of rigs) VRMUtils.deepDispose(rig.avatar.scene);
      renderer.dispose(); renderer.forceContextLoss(); canvas.remove();
    },
  };
}
