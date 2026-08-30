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
layer slider, so each printed layer appears as two: the layer without its raised walls,
then the same layer with them.

**Why the split cannot be positional.** libvgcode groups vertices into layers by runs of
equal `layer_id`, so a layer is a contiguous run of the print-order vertex buffer. The
raised walls are not a contiguous run: Arachne emits walls inset by inset, raising the odd
ones, and the infill follows at nominal Z. Nominal and raised extrusions are therefore
interleaved, and **no split point separates them**. Two earlier attempts failed on exactly
this. Requiring the raised walls to be the layer's tail never fired at all, because a
nominal extrusion always follows them. Splitting at the first raised extrusion did fire -
it is what produced twice the slider steps - but its upper step carried the raised walls
*together with* all the nominal infill and the remaining nominal walls, so no step ever
showed the raised walls on their own and the slider looked unchanged.

**What works instead.** Both steps cover the same moves and differ only in the Z they
declare: the lower one states the layer's nominal Z, the upper one its raised Z. The upper
step owns the layer's final move so that selecting it widens the vertex range back over
the whole layer. `ViewerImpl::update_enabled_entities()` then drops any extrusion above the
topmost visible layer's Z, which is what leaves the raised walls out of the lower step -
the render path filters per vertex, so an arbitrary subset is expressible even though a
layer's *range* is not.

Those Zs cannot be read back off the vertices, so they are stated:
`GCodeProcessorResult::preview_layer_zs` -> `GCodeInputData::layer_zs` -> `Layers::set_zs()`.
Both the cutoff and the stated Zs are gated on `Layers::has_explicit_zs()`, so every
non-Bricklaying print renders exactly as before. That gate matters: a derived layer Z is
only the highest extrusion seen in a layer, which sequential printing makes meaningless,
because the second object restarts near the bed while the first still towers over it.

A layer is split only when there is an **empty gap directly above its nominal Z**: the lowest
raised extrusion has to clear the nominal one by at least 40% of the layer's total raise. That
is what separates Bricklaying from a scarf seam, which ramps up from the nominal Z and so puts
extrusions immediately above it. Spiral vase is skipped outright, and the renumbering is
discarded unless the resulting Z sequence verifies as monotonic.

Only the *lower* edge of the raised band may be tested. The raised walls are not all at one Z:
the raise is `staggered_z_offset * path.height` and `path.height` varies across a layer
(overhangs, thin walls, bridges), so the band is ragged. An earlier rule required nothing to
lie between the nominal Z and the highest raised one, which a ragged band always violates - it
suppressed the split on essentially every real layer while still passing on a uniform test
model. The splitter now logs how many layers it split, so that failure mode is visible in the
log instead of only in the viewer.

**The two halves are one printed layer, and anything reasoning about "the top layer" has to
know that.** `update_colors_texture()` dims every vertex whose `layer_id` is below the topmost
one to `DUMMY_COLOR`. With the upper half on top, every vertex of that same printed layer
carries the lower id, so the whole layer being looked at was dimmed - the model turned black as
the slider passed each half layer. `update_view_full_range()`'s top-layer-only range had the
same flaw. Both now go through `Layers::print_layer_start()`, which maps an upper half back to
its lower one. `preview_layer_upper_half` carries the pairing alongside the Zs.

Known cost: the upper step owns a single move, so its entry in the per-layer *time* figures
is near zero. The layer-time view mode therefore reads oddly for Bricklaying prints. The
layer slider, which is what the split exists for, is correct.

`tests/fff_print/test_orcabrick_preview.cpp` checks the mapping from G-code moves to preview
layers against libvgcode's actual contract - dense ids from zero that never skip or go
backwards, one Z per layer, a non-decreasing Z sequence, and for every split pair that the
nominal step's Z excludes the raised walls while the raised step's includes them all. It also
pins the cases that must be left whole: a scarf ramp, a plain layer, spiral vase. The
renumbering is a `static` on `GCodeProcessor` so the test drives it directly, which is why the
Linux job matters: it is the only leg that compiles `tests/`.

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
* Linux: **two** AppImages, one per glibc floor. Download either, `chmod +x` it and
  run it - there is no installation step.
  * `OrcaSlicer_Linux_ubuntu_2404_V2.4.2+OrcaBrick<n>` - built on Ubuntu 24.04
    (glibc 2.39). For Ubuntu 24.04+, Fedora 40+, Arch, Debian 13.
  * `OrcaSlicer_Linux_ubuntu_2204_V2.4.2+OrcaBrick<n>` - built on Ubuntu 22.04
    (glibc 2.35). For everything older: Debian 12, Ubuntu 22.04, Linux Mint 21,
    openSUSE Leap 15.6. It runs on the newer distros too, so pick this one if unsure.

  The filenames keep the `OrcaSlicer` prefix because they are derived from
  `SLIC3R_APP_KEY`, which is deliberately unchanged so existing printer, filament
  and process profiles keep working. The application inside is branded OrcaBrick.

### Why two Linux builds

An AppImage deliberately does not bundle everything. `scripts/appimage_lib_policy.sh`
resolves glibc, GTK, the GL stack, GStreamer and WebKit from the host, because bundling
those breaks on drivers and themes. The consequence is that **the build host's glibc is the
floor for every system the AppImage can run on**: one built on Ubuntu 24.04 links against
glibc 2.39 and exits with a `GLIBC_2.39 not found` error on Debian 12 (2.36), Ubuntu 22.04
and Mint 21 (2.35), or openSUSE Leap 15.6 (2.38).

The second build lowers that floor to 2.35. It runs inside an `ubuntu:22.04` container on
the normal runner rather than on an `ubuntu-22.04` runner, so it does not depend on that
runner label continuing to exist. `build_linux.sh -g` with `ORCA_DOCKER_BASE_IMAGE` already
does exactly this, and `scripts/linux.d/debian` already special-cases Ubuntu 22.x (it adds
`curl libfuse-dev m4` and picks webkit2gtk 4.0 over 4.1), so no new build logic was needed.
Its dependency cache is keyed separately - deps built against a different glibc must never
be restored into the other build.

**If an AppImage refuses to start** with a message about `libfuse.so.2`, the host is missing
FUSE 2, which Fedora, Arch and Ubuntu 22.04+ no longer install by default. Either run it as
`./OrcaSlicer_Linux_AppImage_....AppImage --appimage-extract-and-run`, which needs no FUSE at
all, or install the distro's `libfuse2` / `fuse-libs` package.

`scripts/orcabrick_smoke_test.py` fails the build if either platform's job is
removed, so both deliverables stay guaranteed.

Adding the Linux job also put `tests/` under CI for the first time: the Windows
leg never compiles them. That immediately exposed a Bricklaying unit test which
had never compiled, because it named an `ExtrusionRole` that does not exist. The
smoke test now checks the roles that test uses against the enum, so the same
mistake fails in seconds rather than forty minutes into a build.

The workflow file is still named `orcabrick_windows.yml` even though it now builds
both; renaming it would have to be done together with the `paths` filter that
references it.

## Build gate

The Windows workflow first runs Python syntax checks, source-wiring checks, and
`git diff --check`. It then builds OrcaBrick, runs the real ON/OFF G-code proof,
and only afterward creates and uploads the installer. Active builds are not
cancelled by a later push.
