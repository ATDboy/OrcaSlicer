# OrcaBrick 2.4.2

OrcaBrick is OrcaSlicer 2.4.2 with the native Bricklaying / staggered-wall
feature ported from the latest recoverable Nanashi implementation.

The checkbox is located at **Process > Strength > Walls > Bricklaying
(staggered walls)** in Advanced or Expert mode. Enabling it offers to apply the
required fixed layer height, matching wall widths, Arachne wall generator, and
non-spiral settings automatically. The optional **Staggered wall flow ratio**
appears directly below it.

Bricklaying is experimental. Use a fixed layer height and at least three walls,
inspect the sliced preview, and test a small part before a long print. Adaptive
layer height, sloped walls, internal holes, and objects with too few layers are
known limitations of the upstream implementation.

Sources:

- OrcaSlicer 2.4.2: <https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2>
- Original native implementation: <https://github.com/OrcaSlicer/OrcaSlicer/pull/8181>
- Latest recovered Nanashi source commit: `b1700658fc4d924e87c71d88e97a0602ccc08c67`
