# OrcaBrick

OrcaBrick is the branded OrcaSlicer fork on the `orcabrick-2.4.2` branch.

## Bricklaying behavior

When **Staggered perimeters / Bricklaying** is enabled with Arachne and at least
three wall loops, alternating inner perimeters are emitted at half-layer Z
positions. The affected extrusion flow is scaled by
`staggered_perimeter_flow_ratio`. Disabling the option produces normal
full-layer toolpaths.

The G-code proof slices the same model with the feature OFF and ON. It requires
different output, no half-layer extrusion when OFF, repeated half-layer inner
wall extrusion when ON, and real XY+E motion after each staggered Z move.

## Preview behavior

`;ORCABRICK_LAYER_CHANGE` creates extra layer groups only in Preview. It has a
dedicated preview counter and no longer changes Orca's real print-layer count,
time estimation, temperature logic, or total-layer metadata. This prevents the
black/disappearing model caused by mixing preview half-layers with real layers.

## Theme behavior

The selected accent is applied to Orca teal/green tokens and legacy blue
controls and SVG icons. Orange back/reset controls intentionally remain orange
for contrast. An unset model/filament color follows the accent; any explicit
filament or AMS color wins.

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
