# OrcaBrick

OrcaBrick is the branded OrcaSlicer fork on the `orcabrick-2.4.2` branch.

## Bricklaying behavior

When **Staggered perimeters / Bricklaying** is enabled with Arachne and at least
three wall loops, alternating inner perimeters (odd `inset_idx`) are emitted at
half-layer Z positions. The affected extrusion flow is scaled by
`staggered_perimeter_flow_ratio`. Disabling the option produces normal
full-layer toolpaths.

The implementation is a port of Nanashi's bricklaying work. It carries that
design's wall-stack special cases, which are easy to mistake for bugs:

* Objects shorter than 4 layers are skipped entirely.
* The second layer (`layer_id == 1`) extrudes the staggered walls at **150 %**
  flow to fill the gap left under the first staggered course.
* The penultimate layer extrudes them at **50 %** flow and is **not** staggered,
  which closes the stack flush with the top surface.

Those multipliers are applied on top of `staggered_perimeter_flow_ratio`, so the
user-facing ratio scales them rather than replacing them.

The G-code proof slices the same model with the feature OFF and ON. It requires
different output, no half-layer extrusion when OFF, repeated half-layer inner
wall extrusion when ON, and real XY+E motion after each staggered Z move.

## Preview behavior

Preview shows the staggered walls at their real half-layer Z, and
`GCodeProcessor::split_staggered_preview_layers()` gives them their own step in the
layer slider, so each printed layer can appear as two: the nominal walls, then the
half-layer walls above them.

The split is deliberately conservative, because libvgcode groups vertices into
layers by runs of equal `layer_id`, keeps one Z per layer (its last extrusion's) and
binary searches those Zs. A layer is only split when its raised extrusions form a
**contiguous tail** after at least one nominal extrusion, and the renumbering is
discarded unless the resulting Z sequence is verified monotonic. Layers that do not
qualify - typically several islands, where Arachne emits nominal and raised walls
per island rather than per layer - stay whole and render as before. Non-Bricklaying
prints have no raised extrusions and are untouched.

Print statistics are unaffected: `MoveVertex::layer_id` feeds the viewer, while time
estimation uses the separate `TimeBlock::layer_id`.

Two earlier attempts were reverted and must not come back:

1. A `;ORCABRICK_LAYER_CHANGE` comment that incremented Orca's real layer counter. It
   corrupted layer statistics, total layer count and time estimation.
2. The same comment driving a dedicated `m_preview_layer_id`. This kept the print
   bookkeeping clean but still produced black or vanishing geometry, because it split
   unconditionally: a Bricklaying course runs Z0.2 -> Z0.3 -> Z0.2, and libvgcode
   requires layer groups to increase monotonically.

`scripts/orcabrick_smoke_test.py` fails the build if either symbol reappears, and
requires the validated splitter and its monotonic bail-out to be present.

For reference, the upstream OrcaSlicer implementation (PR #8181, still open and
alpha) does not touch the preview path at all and has the pre-split behaviour.

## Upstream status and known Bricklaying limits

Two other implementations of this feature exist, and **neither solves the Preview
problem**:

* **OrcaSlicer PR #8181** (vipulrajan) is still open and alpha. Its diff touches
  `ExtrusionEntity`, `GCode.cpp`, `LayerRegion`, `PerimeterGenerator`, `Preset`,
  `PrintConfig`, `ConfigManipulation` and `Tab.cpp` - no `GCodeProcessor`, no
  `libvgcode`, no `GCodeViewer`.
* **NanashiTheNameless' fork**, which this port descends from, is the same: across its
  whole history only merge commits from upstream ever touch the preview sources. His
  own `doc/staggered-perimiters-known-issues.md` lists the preview behaviour as an
  open issue, noting it is "worsened if an object has 2 separate sections of
  outer-walls as they get treated as separate 'towers'" - the multi-island case that
  `split_staggered_preview_layers()` deliberately declines to split.

His known-issue list is worth keeping, because these are print-quality limits rather
than preview cosmetics, and they apply here too:

* With `only_one_wall_first_layer` enabled, the flow correction for the raised inner
  walls is not applied correctly.
* Adaptive layer height is not supported.
* First layer height must equal layer height.

Three of his issues do **not** apply to this branch:

* Staggering ignoring wall slope is handled: `is_covered_from_above()` in
  `PerimeterGenerator.cpp` clips each candidate wall against `upper_slices` and leaves it
  at nominal height unless the layer above covers it completely. The topmost layer has no
  `upper_slices` and is therefore never staggered.

* His multipath handling staggers only the last `ExtrusionMultiPath` of a split run,
  because it runs after the splitting loop. Here the offset is applied to `paths`
  before splitting, so every sub-path is staggered.
* His top-layer check misbehaves with several models of different heights. Here
  `number_of_layers` comes from `layer()->object()->layer_count()`, which is per print
  object, so each object gets its own first/last layer handling.

## Theme behavior

The selected accent is applied to Orca teal/green tokens, legacy blue controls,
SVG icons and the ImGui surfaces of the 3D view (gizmos, G-code legend, slider
text). Orange back/reset controls intentionally remain orange for contrast.

An unset (empty) model/filament colour is the "automatic" sentinel and follows
the accent in both the plater and Preview; any explicit filament or AMS colour
wins. Existing profiles and projects usually already store a colour, so they are
treated as explicit and will not switch to the accent.

Known gaps: the accent has no separate dark-mode variant, web-based panels and
semantically fixed colours (warnings, errors, modified-value markers) do not
follow it, and already-generated project thumbnails are not re-rendered.
Changing the accent requires a restart.

## Branding and packaging

The visible application and installer product name is **OrcaBrick**. Internal
technical build metadata remains available for update/build diagnostics but is
not appended to the visible product name. Windows installers use the stable
filename `OrcaBrick_Setup_x64.exe` or `OrcaBrick_Setup_arm64.exe`.

## Build gate

The Windows workflow first runs Python syntax checks, source-wiring checks, and
`git diff --check`. It then builds OrcaBrick, runs the real ON/OFF G-code proof,
and only afterward creates and uploads the installer. Active builds are not
cancelled by a later push.
