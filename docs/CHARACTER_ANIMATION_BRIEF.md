# Original adult club character — rigging brief

## Current status

The active implementation uses **Three.js 0.186.1 + @pixiv/three-vrm 3.5.5** and an existing CC0 Victoria Rubin model in a transparent bottom-right overlay. Its idle loop is now an original classical club dance: smooth sinusoidal side sways, per-beat bobs, flowing unison arm arcs and slow phrase breathing. Analytic 3D arm IK controls the actual hand positions rather than moving a flat portrait.

The character has exactly three states. By default she performs the original classical club dance: smooth sinusoidal side sways, per-beat bobs, flowing unison arm arcs and slow phrase breathing. Confirmed wins trigger a 4.8-second whole-body victory cheer with raised hands and a strong bust bounce from the app-owned per-side springs; confirmed losses trigger a 3.6-second blown-kiss gesture. Accepted entries are silent — she just keeps dancing. Historical snapshots and duplicate responses are silent. Wave remains removed. The original opaque outfit geometry is restored in the file but hidden at runtime; the character's bust bones are detached from the VRM spring manager and driven by the app-owned springs instead. Hair/clothing springs remain active. Runtime colors/headphones, pause/minimize and reduced-motion support remain. This is a pose-based adaptation, not extracted motion capture or a newly sculpted original character. See the [active asset notes](../frontend/public/characters/victoria/README.md).

The single companion avatar is a code-only customized character built from the CC0 base at load: blue long hair, amber eyes, rose lips, a low persistent parted-lip morph, a bind-space bust inflation, and a revealing micro two-piece fitted to it (offset-shell bandeau with a plunging neckline, high-cut shorts, code-built shoulder straps and choker, rebound to the skeleton). A toolbar `T` toggle holds a neutral inspection pose (all motion frozen, arms at the sides via IK) for checking the body before judging motion. The customization is profile-driven (`CloneProfile` in `lib/avatar-code-demo.ts`): a second downloaded base (Sakurada Fumiriya, kept unused under `frontend/public/characters/fumiriya/`) documents the runtime bone-injection path for models without bust bones. This is the intended no-artist pipeline: CC0 base in, code-only original character out.

The earlier Nova work described below is archived and no longer appears in the app. PixiJS has been removed from dependencies. Browser verification is available again through the current HTTP preview tab.

## Archived 2D region-rig status

The Floor portrait wall has been removed. A new original adult character, **Nova (28)**, now has separated anime artwork, a revised fuller clothed torso, a 17-bone articulated region rig, four motion clips and a lazy PixiJS stage. Native rig data, a packed atlas, a Spine 4.2-format interchange export and an animated preview are in [`frontend/public/characters/nova/`](../frontend/public/characters/nova/README.md).

This is an independently implemented region rig, not an imported Spine/Cubism project. No licensed Spine runtime or Live2D runtime is integrated, and the Spine-format export has not been validated in the editor. Deformable meshes and an editable `.spine` project remain future artist work. The implementation includes body dancing, blink and hair/fabric springs, without isolated sexualized breast animation.

Native export rendering and numerical tests have passed. Browser URL security policy blocked the live UI check, so the compact stage, expanded dialog and WebGL behavior are not yet browser-verified. The sections below retain the target requirements for a future licensed production rig.

## Recommended pipeline

Use **Spine 2D + PixiJS** for full-body dancing, jumps and pose changes. The official maintained `spine-pixi-v8` runtime supports PixiJS 8 (currently minimum 8.16) and Spine features. The runtime's major/minor version must match the exported skeleton's major/minor version. Pin the exact versions after choosing the artist's export version. See [official Spine/PixiJS documentation](https://esotericsoftware.com/spine-pixi).

The [Spine Runtimes License](https://esotericsoftware.com/spine-runtimes-license) sets requirements for runtime integration. Establish the applicable editor/runtime rights before adding or distributing the runtime. No license was purchased, accepted or represented as held during this task.

Live2D is an alternative for expression-led close-up characters, but its real Cubism model is compiled model data, not a PNG plus animation settings. See [Cubism model loading](https://docs.live2d.com/en/cubism-sdk-manual/model-web/) and [Cubism Core](https://docs.live2d.com/en/cubism-sdk-manual/cubism-core/).

## Character direction

- Original adult nightclub performer, clearly at least 25, with mature facial proportions. Do not recreate or age-up the youthful franchise characters in the reference images.
- Long red or golden hair, expressive eyes, polished anime linework, black/white short club clothing with violet and pink accents. Translate the broad palette and anime presentation into an original design.
- Work from clean front and three-quarter model sheets. The existing original adult `frontend/public/art/dancer-rose.png` is an optional visual reference, not a rig-ready source.

## Layered art deliverable

Supply editable layered source artwork and separated, transparent parts with painted overlap coverage: face, eyes/eyelids, mouth shapes, front/back hair sections, neck, torso/clothing, upper/lower arms, hands, hips, upper/lower legs, shoes and loose clothing accessories. Paint areas hidden behind limbs so IK movement does not expose holes. Supply a neutral full-body pose and a proportion guide. A flattened screenshot cannot supply these hidden surfaces.

## Rig and motion deliverable

Provide a real skeleton with root, pelvis, spine, neck/head, arm and leg chains; suitable IK constraints; skinned meshes; blink/expression controls; and secondary motion for hair, jacket fabric and loose accessories. Test foot contact and hand placement through the dance loop.

Required named clips:

| Clip | Behavior |
| --- | --- |
| `idle` | Breathing, blink and small weight shifts |
| `dance` | Seamless 4–8 second full-body dance with stable feet |
| `jump` | Anticipation, jump and landing, then return to dance |
| `cheer` | Short celebratory gesture |
| `pause` or setup pose | Stable readable pose when motion is disabled |

Blend clips without snapping. Include tested hair and clothing physics and sensible limits. Provide a preview video demonstrating the actual rig and all animations, not a transformed flat portrait.

## Export package required by the app

For Spine, supply:

1. A `.json` or `.skel` skeleton export, with its Spine version documented.
2. Its `.atlas` file and every referenced texture PNG.
3. Animation names and durations, default skin, authored bounds/scale and physics settings.
4. Source project and the rights/license information needed to use and distribute it.

Suggested destination after delivery: `frontend/public/characters/club-dancer/`. No placeholder model files should be put there or presented as a working rig.

## Frontend integration contract

After those assets and rights are available, load the matching official Spine runtime and PixiJS lazily in a client component. Render the character in a dedicated transparent canvas beside the markets, avoiding price labels and order controls. Play `dance` normally, blend to idle/pause when DJ motion is off, and respect system reduced-motion preferences. Pause the renderer when hidden and destroy its canvas, ticker and assets on unmount.

Keep character state independent of trading state. A future optional `cheer` trigger may use an actual newly resolved stage receipt; it must not invent wins or affect balances, barriers, clocks or order requests. Check rendering lifecycle, resize handling, animation transitions and WebGL/context failure with the actual model before calling the integration complete.
