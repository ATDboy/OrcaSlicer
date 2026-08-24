# OrcaBrick 2.4.2

OrcaBrick is an experimental OrcaSlicer 2.4.2 fork with native Bricklaying
(staggered walls), based on the latest recoverable Nanashi implementation.

## Current release status

Do not treat an installer as verified merely because it compiles. A release is
ready only when the Windows workflow is green and its `OrcaBrick_GCode_Proof`
artifact reports `"result": "PASS"`. The proof slices the same cube with
Bricklaying off and on. It requires explicit inner-wall perimeter moves at
several half-layer heights, real XY+E wall extrusion after every move, and zero
half-layer perimeter moves in the off file. The check intentionally follows
the emitted toolpaths rather than relying on optional G-code comments.

The obsolete release-ready notice for the earlier, unverified installer has
been removed.

## Using Bricklaying

The checkbox is under **Process > Strength > Walls > Bricklaying (staggered
walls)** in Advanced or Expert mode. When enabled through the GUI, OrcaBrick
offers to apply these compatibility settings:

- fixed and matching normal/first-layer height;
- matching top-surface and outer-wall width;
- Arachne wall generator;
- at least three walls;
- Spiral vase off;
- Alternate extra wall off;
- Only one wall on first layer off.

Bricklaying deliberately controls wall order to reduce nozzle-collision risk,
so the normal wall-order preference is not authoritative while the feature is
enabled. The safe starting value for **Staggered wall flow ratio** is 1.00.
Higher flow is an experiment, not a universal improvement.

Preview can look subtle because only selected inner perimeters move to
half-layer heights; the whole model does not gain extra logical layers. Inspect
the wall toolpaths closely and test a small part before a long print. Sloped
walls, overhangs, support-contact areas, internal holes, adaptive layer heights,
and very short objects remain known risk areas of the upstream experimental
implementation.

## Appearance and identity

Build 3 uses neon cyan (`#00E5FF`) for the main accent controls by default.
Change it under **Preferences > General > Accent colour** and restart
OrcaBrick. Some specialized icons and views use their own semantic colors and
are intentionally not recolored.

The visible program name is **OrcaBrick**, and the visible version is
**2.4.2 - build 3**. The internal application key remains OrcaSlicer so existing
printer, filament, and process profiles stay compatible. The technical build
version is `2.4.2+OrcaBrick3` and is not used as the normal display name.

## Sources

- OrcaSlicer 2.4.2: <https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2>
- Original native implementation and known issues: <https://github.com/OrcaSlicer/OrcaSlicer/pull/8181>
- Independent strength testing: <https://www.cnckitchen.com/blog/brick-layers-make-3d-prints-stronger>
- Maintained post-processing implementation and notes: <https://github.com/TengerTechnologies/Bricklayers>
- Latest recovered Nanashi source commit: `b1700658fc4d924e87c71d88e97a0602ccc08c67`
