# Nova — original adult anime character

**Archived:** the user rejected this 2D region rig. The active app now uses the [Three.js/VRM companion](../victoria/README.md). This directory retains the 2D source artwork, math export and offline preview for reference; there is no longer a PixiJS preview in the app.

Nova is an original 28-year-old nightclub performer. The separated artwork uses red hair, expressive anime eyes, an opaque white blouse, a fitted black waistcoat with pink trim, trousers and heeled boots. The revised torso has a fuller clothed silhouette. No franchise character artwork is included.

## What works now

The app lazily loads PixiJS 8.22.0 and an independently written 17-bone region rig. Shoulders, elbows, hips, knees and head articulate separately; analytical two-bone leg IK maintains authored ankle targets. Four authored clips are included: `dance` (4 s loop), `idle` (4 s loop), `jump` (1.4 s) and `cheer` (2.4 s). Hair and loose fabric use bounded damped springs in the app. Blinking uses separate open/closed-eye artwork. Motion pauses through the desk's DJ control, system reduced-motion preference, offscreen visibility and hidden tabs.

The compact stage has clip selection, hair/fabric motion, a skeleton overlay and an expanded preview. Trading state is independent of the animation.

## Files

- `images/`: 16 transparent separated parts; `source/`: original generated raster sheets.
- `nova.rig.json`: native skeleton, attachments and 30 fps baked animation samples, positive Y downward.
- `nova.spine.json`, `nova.atlas`, `nova.png`: Spine 4.2-format region interchange data and packed texture.
- `preview.gif`, `preview.png`: offline renders of the exported native dance poses, not screenshots of the browser or a licensed Spine renderer.
- `nova-rig.zip`: this asset package, including sources and provenance notes.

The archived preview used our own rig code and PixiJS. **No Spine or Live2D runtime is installed.** The Spine-format export has structural/asset-reference tests but has not been imported into the Spine Editor or validated against its runtime. It is an initial region rig, without deformable meshes or an editable `.spine` editor project. A licensed artist can import and refine it; applicable Spine license requirements must be established separately before runtime integration. See [Spine JSON format](https://esotericsoftware.com/spine-json-format) and [runtime license](https://esotericsoftware.com/spine-runtimes-license).

## Rebuild

From the repository root, crop/pack the supplied sources:

```sh
python3 scripts/build_character_textures.py frontend/public/characters/nova/source/parts-sheet.png --torso frontend/public/characters/nova/source/torso-revision.png
```

From `frontend/`, run `npm run character:export`. From the repository root, run `python3 scripts/render_character_preview.py`, then rerun the export to include the latest previews in the archive. Pillow is required by the asset scripts. Animation source is `frontend/lib/character-rig.ts`; browser lifecycle/rendering is `frontend/lib/character-renderer.ts`.

## Verification limit

The native animation export was rendered and visually inspected. IK contact, loop continuity, finite poses, spring stability and export references have automated tests. Live browser verification for this change was blocked by the browser URL security policy; compact/modal rendering and WebGL lifecycle still need an in-browser check.
