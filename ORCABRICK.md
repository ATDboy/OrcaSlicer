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
* The **first layer is never staggered**. It stays flat on the plate.
* The second layer (`layer_id == 1`) is the first staggered course, and extrudes
  its raised walls at **150 %** flow to fill the half layer they leave above the
  flat first layer.
* The penultimate layer extrudes them at **50 %** flow and is **not** staggered,
  which closes the stack flush with the top surface.
* Overhanging and bridged paths are never staggered whatever their inset index.

The 150 % is applied on top of `staggered_perimeter_flow_ratio`, so the user-facing
ratio scales it. The 50 % is not: that wall is not raised, and the ratio only applies
to raised ones.

Stacked up, each course sits exactly on the one below:

| Layer | Occupies | Flow |
| --- | --- | --- |
| 0 (flat) | `0 .. h` | 1x |
| 1 (raised) | `h .. 2.5h` | 1.5x |
| 2 (raised) | `2.5h .. 3.5h` | 1x |
| ... | ... | 1x |
| n-3 (raised, last) | up to `(n-2)h + 0.5h` | 1x |
| n-2 (flat, closing) | `(n-2)h + 0.5h .. (n-1)h` | 0.5x |
| n-1 (flat, top) | nominal | 1x |

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
renumbering is a `static` on `GCodeProcessor` so the test can drive it directly.

Getting it to actually run took a dedicated job. `CMakeLists.txt` defaults `BUILD_TESTS` to
`OFF`; `build_linux.sh` turns it on only with `-t`; and `build_orca.yml` passes `-t` only on the
aarch64 leg, which this workflow does not have. No leg invokes `ctest` either. Build 22 showed
it plainly - its *Upload Test Artifact* step was skipped, so `tests/` was never compiled. The
`unit_tests` job builds with `-t` and runs `scripts/run_unit_tests.sh`, and the smoke test
requires that job to exist.

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

Two G-code post-processors implement the same idea from outside the slicer, and they are
worth reading because they define what the feature is supposed to do:

* **TengerTechnologies/Bricklayers** (`bricklayers.py`) is the reference. It shifts inner
  perimeter blocks by `layer_height * 0.5`, and multiplies extrusion by 1.5 on the first
  layer, 0.5 on the last, and a user ratio in between. It has no notion of wall slope,
  overhangs, or variable layer height - working on finished G-code, it cannot see them.
* **drkpxl/Bricklayers** is a tidier fork of the same script with layer-height and printer
  auto-detection. It documents no edge cases at all.

Running inside the slicer is what makes the geometric guards below possible; a
post-processor has no upper slices to clip against.

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
| First layer lifted off the plate (both upstreams do this) | **Fixed** - layer 0 is never staggered; the 1.5x flow that pairs with it moves to layer 1. See below. |
| Overhanging and bridged paths raised into air (neither upstream guards this) | **Fixed** - `erOverhangPerimeter` and any bridged role stay at nominal Z. |

### The first layer, and why this fork stopped copying it

Nanashi's design and upstream #8181 both stagger layer 0's odd walls, lifting them half a
layer off the plate. This port copied that, and an earlier revision of this document
defended it as one half of a pair with layer 1's 1.5x flow. That was wrong, and the
arithmetic says so without needing a test print:

* A raised wall on layer 0 occupies `0.5h .. 1.5h`. The gap it leaves is `0 .. 0.5h`,
  **at the plate**, under the wall.
* Layer 1's 1.5x flow is deposited at `1.5h .. 2.5h`, above that wall. It cannot reach
  the gap. Meanwhile layer 1's raised wall already lands squarely on layer 0's raised
  wall, so the extra 50 % has nothing to fill and simply over-extrudes.

So the two halves did not compensate each other: the first layer printed into air and the
second over-extruded. There are two self-consistent schemes, and only one of them keeps
the first layer flat:

* **Tenger's post-processor** raises layer 0 *and* gives layer 0 the 1.5x, so the bead is
  1.5 layers tall and reaches the plate.
* **This fork** does not raise layer 0 at all and gives layer 1 the 1.5x, which fills
  `h .. 2.5h` over the flat first layer.

The second is used here. It keeps the first layer flat for adhesion and first-layer
calibration, it does not fight `first_layer_flow_ratio` or the first layer's own line
width, and it was the smaller change - the 1.5x was already on layer 1.

The G-code proof enforces it: with a 0.2 mm layer height, no wall may be raised to 0.4 mm
or below, so a lifted first layer (which would show up at 0.3 mm) fails the build.

Also fixed beyond both upstreams: an overhanging or bridged path is never raised. It has
nothing beneath it by definition, so raising it widens the span it already bridges and
lifts it off the wall it should anchor to. Neither #8181 nor Nanashi's fork guards this.

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

### webkit2gtk, the other host dependency that decides portability

glibc is not the only thing taken from the host. `src/slic3r/CMakeLists.txt` has an
unconditional `pkg_check_modules(webkit2gtk REQUIRED webkit2gtk-4.1)`, and the policy resolves
`libwebkit2gtk-*.so*` from the host too, so **every distro running the AppImage must have the
4.1 ABI**. Arch, Fedora and Debian 13 dropped 4.0 entirely; Ubuntu 22.04 and Debian 12 carry
both.

`scripts/linux.d/debian` used to prefer 4.0 wherever it existed. That predates the 4.1
requirement and is wrong twice over: on Ubuntu 22.04 and Debian 12 the build fails at configure
time because `webkit2gtk-4.1.pc` was never installed, and had it linked, the result would not
start on Arch or Fedora. It now installs 4.1 and only falls back to 4.0 with a warning.
`orcabrick_smoke_test.py` compares the ABI the script installs against the one CMake requires,
so the two cannot drift apart again.

The older base also exposed a latent portability bug. `src/OrcaSlicer.cpp` default-initialised
a `ThumbnailsParams`, whose `sizes` member is a `const Vec2ds` with no initialiser. Default-
initialising a class with a const member is ill-formed unless that member's type has a
user-provided default constructor, and `std::vector`'s is `= default` in libstdc++ 11, so the
implicit constructor is deleted. It compiled on Ubuntu 24.04 by luck. The declaration turned out
to be dead - every use is inside a deeper scope that declares its own brace-initialised copy that
shadows it - so it was simply removed, and the smoke test keeps it from coming back.

### Arch, Fedora and other rolling distros

They need no separate build. Their glibc is newer than either base, and both AppImages link
webkit2gtk 4.1, which is the only ABI those distros ship. Use whichever build you like; the
Ubuntu 22.04 one is the safer default because its glibc floor is lower and nothing else about
it is older.

The audit that follows the container build (`check_appimage_libs.sh`) runs on the runner, not in
the container, so the runner has to have the very libraries the AppImage expects from a host -
otherwise it reports all of them unresolved. The compat job installs the same dependencies before
auditing, which keeps the check meaningful: it asks whether a library is one the host is expected
to provide, not whether this particular runner happens to have it.

### Test status

The `unit_tests` job runs the whole suite. Both OrcaBrick preview tests pass. One unrelated
upstream test, *Placeholder parser coFloatsOrPercents vector access*, segfaults; it came in with
upstream's #14526 and nothing in OrcaBrick touches the placeholder parser. It is deliberately
**not** marked `[NotWorking]` - that would hide an unexplained crash - so the job stays red on it
until it is diagnosed. It does not block any build leg: the installer and both AppImages are
produced by other jobs and are unaffected.

**If an AppImage refuses to start** with a message about `libfuse.so.2`, the host is missing
FUSE 2, which Fedora, Arch and Ubuntu 22.04+ no longer install by default. Either run it as
`./OrcaSlicer_Linux_AppImage_....AppImage --appimage-extract-and-run`, which needs no FUSE at
all, or install the distro's `libfuse2` / `fuse2` / `fuse-libs` package.

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
