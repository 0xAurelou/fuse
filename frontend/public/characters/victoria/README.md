# Victoria Rubin — 3D VTuber companion

The active Degen avatar is a real skinned VRM model rendered on a transparent Three.js canvas, fixed to the viewport's bottom-right corner. It replaces the former PixiJS/region-sprite stage. Model geometry and texture images are unchanged; runtime material colors use lavender hair and dark violet clothing, with original Three.js headphone accessories.

## Source and permissions

- File: `avatar.vrm`, source [madjin/vrm-samples — Victoria_Rubin.vrm](https://github.com/madjin/vrm-samples/blob/master/vroid/beta/Victoria_Rubin.vrm).
- Original title in embedded VRM metadata: **Victoria Rubin**. Embedded author field is blank; no individual creator is inferred.
- Embedded metadata declares `licenseName: CC0`, `allowedUserName: Everyone`, `commercialUssageName: Allow`. The repository also documents its CC0 model collection: [source README](https://github.com/madjin/vrm-samples).
- [CC0 public-domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).

This is an existing CC0 avatar, not an original model sculpted for FUSE. The archived original Nova 2D art/export remains under `../nova/`; it is not the active renderer.

## Implementation

Pinned libraries: Three.js 0.186.1 and `@pixiv/three-vrm` 3.5.5. Both use the MIT license; see the corresponding package licenses in `node_modules/three/LICENSE` and `node_modules/@pixiv/three-vrm/LICENSE`. [Three-VRM source/license](https://github.com/pixiv/three-vrm/blob/dev/LICENSE), [Three.js license](https://github.com/mrdoob/three.js/blob/dev/LICENSE).

`lib/character-renderer.ts` loads the avatar only in Degen mode. The default dance is an original eight-beat pose interpretation of [the user's POKEDANCE reference](https://www.youtube.com/shorts/mnuHtWQW9IU): alternating side-pointing hands, two extended fingers, counterbalancing weight shifts, head nods and small knee dips. It uses an app-selected 128 BPM timing; it is not extracted motion capture or synchronized audio. No source model, motion download or music from the reference is bundled.

Authored hand targets are solved with analytic two-bone 3D arm IK, with outward elbow poles and wrist/index alignment. `lib/vtuber-ik.ts` clamps unreachable targets and handles coincident/parallel-pole cases. `lib/vtuber-motion.ts` supplies cyclic pose timing, hand targets, finger curls and expressions. Hair/clothing springs remain active. The original opaque dress geometry is restored from the verified source binary; the dress mesh is hidden at runtime by the customization layer below.

The single companion avatar is the code-only customized character built from this CC0 base at load by `lib/avatar-code-demo.ts` — no artist assets. It uses `VICTORIA_PROFILE` (`CloneProfile` in `lib/avatar-code-demo.ts`; `FUMIRIYA_PROFILE` documents a second base with runtime bone injection for models that ship no bust bones, and the downloaded Fumiriya asset remains under [`../fumiriya/README.md`](../fumiriya/README.md) unused). The character: blue long hair with dark-blue lashes/brows, warm amber eyes, rose lips, a persistent parted-lip morph (`faceOh`) at low weight, the dress mesh hidden, a bind-space bust inflation (100mm apex displacement, run before the garments are built), and a revealing micro two-piece fitted to the inflated shape: crimson offset-shell bandeau with a plunging neckline and high-cut shorts, duplicated from body-surface bands along vertex normals and rebound to the skeleton, plus parametric shoulder straps and a choker. She retains the model's own `J_Sec_*` bust bones, detached from the VRM spring manager and driven by app-owned per-side damped-spring physics (left/right de-phased, one-shot win impulse). Bases that paint clothing onto the body texture (Fumiriya) can set `flattenBody` to replace it with plain skin. A toolbar `T` toggle holds a neutral inspection pose: choreography, reactions, expression morphs and spring motion freeze, and the arms hang at the sides via the analytic IK solver instead of the model's stiff authored rest pose.

Confirmed accepted receipts trigger a 5.2-second stronger dance. Newly confirmed `survived` stages trigger a distinct 4.8-second **whole-body** victory hop with raised hands, a smile and STAGE WON caption. A newly confirmed `exploded` outcome retains the 3.6-second blown-kiss loss gesture. All reactions ease back into the same dance loop. Wave/manual gesture buttons remain removed. No webcam, microphone, speech or audio is used.

`lib/avatar-events.ts` is a passive observer shared by actual frontend receipt/poll paths. It skips restored history and deduplicates receipts and terminal transitions. It handles out-of-order simultaneous receipts and brief positions missed between polls. Wins, losses and voids are distinguished; refunds are silent. Within a snapshot, loss takes priority over win, and win over entry. Session changes reset the baseline, and wall-clock expiry prevents replaying old reactions after restore. The Go engine and financial command semantics are unchanged.

The canvas passes pointer events through to the desk. Only the small control bar accepts clicks. Pause stops the avatar; DJ pause also applies. Minimize unmounts the canvas and releases its WebGL resources; restore creates a fresh instance. Hidden tabs and system reduced-motion preferences stop continuous rendering. Pixel ratio is capped at 1.5 and animation at 30 fps. Smaller viewports use a smaller bottom-right overlay.

The model is served locally with embedded textures; the browser does not fetch avatar resources from a third-party host. The model is approximately 15 MB on disk.
