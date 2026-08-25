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

Preview shows the staggered walls at their real half-layer Z, drawn inside the
nominal layer they belong to. **They are not separate steps in the layer
slider**, and making them so is still unsolved.

Two earlier attempts were reverted and must not come back:

1. A `;ORCABRICK_LAYER_CHANGE` comment that incremented Orca's real layer
   counter. It corrupted layer statistics, total layer count and time
   estimation.
2. The same comment driving a dedicated `m_preview_layer_id`. This kept the
   print bookkeeping clean but still produced black or vanishing geometry,
   because a Bricklaying course runs Z0.2 -> Z0.3 -> Z0.2 while libvgcode
   requires layer groups to increase monotonically.

`scripts/orcabrick_smoke_test.py` fails the build if either symbol reappears in
`GCode.cpp`, `GCodeProcessor.cpp` or `GCodeProcessor.hpp`. Any future attempt has
to make libvgcode itself accept non-monotonic groups, not synthesise layers
around it.

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
