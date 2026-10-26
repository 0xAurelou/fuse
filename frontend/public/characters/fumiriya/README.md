# Sakurada Fumiriya — code-only clone base

Second base model for the VTuber companion's side-by-side code-only customization demo. The right avatar is the base Victoria model; this model is loaded for the left avatar and fully customized at runtime by `frontend/lib/avatar-code-demo.ts` (body inflation, injected bust bones with re-skinned vertices, offset-shell garments, straps, restyle). No authored customization assets exist for it on disk.

## Source and permissions

- File: `avatar.vrm`, source [madjin/vrm-samples — Sakurada_Fumiriya.vrm](https://github.com/madjin/vrm-samples/blob/master/vroid/beta/Sakurada_Fumiriya.vrm) ([repository](https://github.com/madjin/vrm-samples)).
- Embedded metadata declares `licenseName: CC0`, `allowedUserName: Everyone`, `commercialUssageName: Allow`.
- [CC0 public-domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).
- See [`SOURCE.json`](./SOURCE.json) for the recorded provenance.

This is an existing CC0 avatar, not an original model sculpted for FUSE. The embedded model file is byte-identical to the upstream sample; every visual difference in the app is runtime code.
