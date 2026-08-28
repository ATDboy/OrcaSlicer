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

The split point is the layer's first raised extrusion. Everything from there on - the
raised walls, and the nominal-height infill that follows them - becomes the upper step.
An earlier version required the raised walls to be the layer's *tail*; that never fired,
because perimeters are emitted before infill, so a nominal extrusion always follows them.

libvgcode groups vertices into layers by runs of equal `layer_id` and binary searches one
Z per layer, so a layer's Z is taken as its **highest** extrusion rather than its last
(`Layers::update()`). Upstream's "last extrusion wins" is arbitrary for any layer holding
more than one Z, and here it would report the nominal Z for a group whose point is the
raised walls. The renumbering is still discarded unless the resulting Z sequence verifies
as monotonic, and a layer with no nominal extrusion before its first raised one is left
whole. Non-Bricklaying prints have no raised extrusions and are untouched.

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

His known-issue list is worth tracking, because those are print-quality limits rather
than preview cosmetics. Every entry is now either fixed here or refused up front:

| Nanashi's issue | State here |
| --- | --- |
| Staggering ignores wall slope, raising walls that end up visible from above | **Fixed** - `is_covered_from_above()` clips each candidate wall against `upper_slices` and leaves it at nominal height unless the layer above covers it. The topmost layer has no `upper_slices` and is never staggered. |
| `only_one_wall_first_layer` breaks the flow correction | **Refused** - `ConfigManipulation` forces it off when Bricklaying is enabled. |
| Adaptive layer height unsupported | **Refused** - a layer whose height differs from the configured `layer_height` is left at nominal, so height-range modifiers and adaptive layers simply do not stagger. |
| First layer height must equal layer height | **Refused** - `ConfigManipulation` forces them equal. |
| Several models of different heights confuse the top-layer check | **Not applicable** - `number_of_layers` comes from `layer()->object()->layer_count()`, which is per print object. |
| Preview groups one layer as several | **Partly addressed** - see Preview behavior above. Multi-island layers still render as one. |

One thing from his design is kept deliberately: layer 0's odd walls are staggered, lifting
them half a layer off the bed, and layer 1 carries a 1.5x flow multiplier that compensates
for it. Upstream #8181 does the same. The two halves only make sense together, so neither
was changed without a physical print to judge it.

His multipath handling staggers only the last `ExtrusionMultiPath` of a split run, because
it runs after the splitting loop. Here the offset is applied to `paths` before splitting, so
every sub-path is staggered.

## Theme behavior

The selected accent is applied to Orca teal/green tokens, legacy blue controls,
SVG icons and the ImGui surfaces of the 3D view (gizmos, G-code legend, slider
text). Orange back/reset controls intentionally remain orange for contrast.

An unset (empty) model/filament colour is the "automatic" sentinel and follows
the **Model colour** preference in both the plater and Preview; any explicit
filament or AMS colour wins. Existing profiles and projects usually already store
a colour, so they are treated as explicit and keep it.

**Model colour** (Preferences) is the colour those automatic models are painted.
It is a separate picker from the accent, with a *Follow accent colour* tick that
clears it; clearing it stores an empty `model_color` key, which `StateColor`
reads back as "follow the accent". Changing either picker re-resolves the volume
colours on the plate and in the assembly view straight away, without a restart.

Widgets reach the accent through `StateColor`, which substitutes the accent for
the known Orca tokens whenever a colour is resolved. Code that paints a token
straight onto a `wxDC` or hands it to `SetForegroundColour`/`SetBackgroundColour`
bypasses that, so those sites call `StateColor::darkModeColorFor()` explicitly -
the selected-tab underline, the task and machine list pages, the switch buttons,
notification hyperlinks, the 3D selection rectangle and the rest. Wrapping at the
point of use, rather than at a file-scope `static const wxColour`, matters:
statics are initialised before the accent is read from the config, so a wrapped
static would freeze the built-in default. `scripts/orcabrick_smoke_test.py` fails
the build if any of those sites reverts to a raw literal.

The release-notes webview takes its link colour from the accent too.

Known gaps: the accent has no separate dark-mode variant, so a very light or very dark
choice will have poor contrast in one theme; semantically fixed colours (warnings, errors,
modified-value markers) deliberately do not follow it; remaining web-based panels and
already-generated project thumbnails are not re-rendered. SVG icons are recoloured
through the bitmap cache at load time, so icon colours still need a restart.

## Branding and packaging

The visible application and installer product name is **OrcaBrick**. Internal
technical build metadata remains available for update/build diagnostics but is
not appended to the visible product name.

Every build produces installables for **both Windows and Linux**:

* Windows: `OrcaBrick_Setup_x64.exe` (or `_arm64`), artifact
  `OrcaBrick_Windows_Setup_x64`.
* Linux: an AppImage, artifact `OrcaSlicer_Linux_ubuntu_2404_V2.4.2+OrcaBrick<n>`
  containing `OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2+OrcaBrick<n>.AppImage`.
  The filename keeps the `OrcaSlicer` prefix because it is derived from
  `SLIC3R_APP_KEY`, which is deliberately unchanged so existing printer, filament
  and process profiles keep working. The application inside is branded OrcaBrick.
  Download it, `chmod +x` it, and run it - no installation step is needed.

`scripts/orcabrick_smoke_test.py` fails the build if either platform's job is
removed, so both deliverables stay guaranteed.

The workflow file is still named `orcabrick_windows.yml` even though it now builds
both; renaming it would have to be done together with the `paths` filter that
references it.

## Build gate

The Windows workflow first runs Python syntax checks, source-wiring checks, and
`git diff --check`. It then builds OrcaBrick, runs the real ON/OFF G-code proof,
and only afterward creates and uploads the installer. Active builds are not
cancelled by a later push.
