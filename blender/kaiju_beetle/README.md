# Bronze beetle-knight — task 307

Rigid bronze adversary based on the approved `kaiju_beetle_voxel.png`. The
model uses closed faceted solids, segmented abdominal/elytron plates, hex
rivets, angular amber eyes/chest, hinged limbs, and a seven-section drill horn
with a solid helical cutting ridge. No organic mesh deformation is used.

## Deliverables

Outputs live outside Git, in:
`/home/devin/src/2026/videdit/work/kaiju_beetle_307/`

- `kaiju_beetle.blend` — standalone model collection, neutral stance, studio
  lights/camera and floor. Append only **BEETLE | bronze knight** into a scene.
- `beetle_faceoff.blend`, `beetle_clash.blend` — independent, packed posed scenes
  using the original desert arches and the film robot. Each opens at frame 1.
- `beetle_faceoff.png`, `beetle_clash.png` — 1920×1080 Cycles stills, 64 samples.
- `kaiju_beetle_model.png`, `kaiju_beetle_rear.png` — 1080p asset review views.
- `film_look_comparison.png` — teaser endpoint at left, final faceoff at right.
- `verification.json` — closed-solid, hierarchy, grounding, scale, framing,
  resource, original robot face-assignment and mutation-check results.
- `build_manifest.json`, `continuity_restoration.json` — source and setup notes.

These are posed review shots, not an animated fight. The stills were visually
iterated against the actual teaser and reviewed by the PM under Devin's
pre-approval. Draft PNGs are intermediate comparisons; use the filenames above.

## Rebuild

From this repository, with Blender 5.1.2:

```bash
blender -b --python-exit-code 1 --python blender/kaiju_beetle/build.py -- \
  --source /home/devin/src/2026/videdit/work/kaiju_mountain_valley.blend \
  --output /home/devin/src/2026/videdit/work/kaiju_beetle_307

blender -b /home/devin/src/2026/videdit/work/kaiju_beetle_307/beetle_faceoff.blend \
  --python-exit-code 1 --python blender/kaiju_beetle/render.py -- \
  --output /home/devin/src/2026/videdit/work/kaiju_beetle_307/beetle_faceoff.png \
  --samples 64 --device 1050

blender -b --python-exit-code 1 --python blender/kaiju_beetle/verify.py -- \
  --directory /home/devin/src/2026/videdit/work/kaiju_beetle_307 --negative-checks
```

Render the clash and standalone model by changing the input/output names.
For the rear model view, add `--view rear`. For quick drafts, use `--percent 50
--samples 24`. The renderer explicitly selects the GTX 1050 Ti; this leaves the
RTX 3060 free for the separate T306 sequence. Select another CUDA device by name
when rebuilding on a different workstation. Rendering does not overwrite the
saved scene settings. The builder only writes its own named output files.

## Joints for animation

Blender axes are **+Z up, -Y forward**; dimensions use the existing film scene's
units. Place/rotate/uniformly scale `BK | ROOT | placement`. Every mesh has an
empty parent; local mesh geometry remains rigid. These controls are an FK
hierarchy, not an armature or an IK system. Limits below are guidance, recorded
as custom properties; constraints do not enforce them.

| Control | Purpose and suggested rotation |
| --- | --- |
| `pelvis` | Body height, whole-body anticipation/crouch; parent of legs. |
| `waist` | Torso lean X ±20°, roll Y ±12°, turn Z ±25°; parent of head/arms/shell. |
| `neck` | Head pitch X −25°..15°, yaw Z ±30°. |
| `shoulder L/R` | Arm swing X −100°..35°, Y ±35°, Z ±25°. |
| `elbow L/R` | Mechanical flexion X −110°..0°. |
| `wrist L/R`, `claw L1..R3` | Small wrist articulation and individual rigid fingers. |
| `hip L/R` | Leg swing X ±35°, Y/Z ±15°. |
| `knee L/R` | Flexion X 0°..75°. |
| `ankle L/R` | Ground contact compensation X ±25°, Y ±12°. |
| `elytron hinge L/R` | Split dorsal shell articulation about Z, up to 25° outward. |
| `drill spindle` | Local Z spin; initial 22° rake is part of its orientation. |

Key local empty rotations for motion. Preserve the drill's authored scale and
rake; use local-Z rotation or a new child spin control for continuous spinning.
Armor seams allow modest articulation, but broad action will need collision and
foot-lock passes. Static pose grounding uses evaluated vertex minima after all
rotations; it does not solve contact throughout future animation.

## Film continuity

The saved valley file differs from the footage: its robot has one reflective
rust override, and new wide camera angles expose an unrelated HDRI hillside.
`../kaiju_liftoff/restore_teaser_state.py` is a reusable **opt-in** preparation
step for new shots. It does not alter T305/T306 or any source `.blend`.

The helper restores the native robot mesh, weights and ten face material
assignments from `voxel-shorts/assets/character-kaiju-robot.blend`, retaining
the scene rig. Named shot-material copies mute the master asset's red/emerald
slots and darken gunmetal to match the actual teaser frame. The master asset is
untouched. All robot materials remain nonemissive: blue is a lighting spill,
as the blue in the teaser came from plasma-ring reflections. Amber belongs to
the beetle. This is a reviewed continuity reconstruction, not a pixel-identical
recovery of an archived render setup.

The original overcast HDRI still lights the scene; camera rays sample its upper
sky. Original ground PBR textures are retained on a larger plane with matched UV
scale. Height-faded fog replaces the constant-density slab. Storm exposure and
broad, dim lights retain readable silhouettes in the denser air. The earlier
T305 camera recovery remains independent of this new-shot helper.

`verify.py --negative-checks` temporarily injects a deforming modifier, opens a
solid, crops the camera and removes a robot material slot. Each must fail its
intended assertion; exact in-memory backups are restored and re-audited. No
mutated file is saved. Visual review additionally checks pose readability,
terrain occlusion, material identity and weather against the teaser.
