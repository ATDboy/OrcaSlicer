///|/ Copyright (c) Prusa Research 2023 Enrico Turri @enricoturri1966
///|/
///|/ libvgcode is released under the terms of the AGPLv3 or higher
///|/
#ifndef VGCODE_GCODEINPUTDATA_HPP
#define VGCODE_GCODEINPUTDATA_HPP

#include "PathVertex.hpp"

namespace libvgcode {

struct GCodeInputData
{
    //
    // Whether or not the gcode was generated with spiral vase mode enabled.
    // Required to properly detect fictitious layer changes when spiral vase mode is enabled.
    //
    bool spiral_vase_mode{ false };
    //
    // List of path vertices (gcode moves)
    // See: PathVertex
    //
    std::vector<PathVertex> vertices;
    //
    // One Z per layer, in layer order, overriding the Z derived from the vertices.
    // Bricklaying needs it: a printed layer becomes two layers over the same moves, one at the
    // nominal Z and one at the raised Z, which cannot be read back off the vertices.
    // Empty means "derive from the vertices", the behaviour for every other print.
    //
    std::vector<float> layer_zs;
    //
    // 1 where a layer is the upper half of a split printed layer, parallel to layer_zs.
    // The two halves are one printed layer, so anything that dims "everything below the top
    // layer" has to treat them as one, or the layer being looked at is dimmed along with the
    // rest. Empty means no layer is a half.
    //
    std::vector<uint8_t> layer_upper_half;
    //
    // Palette for extruders colors
    //
    Palette tools_colors;
    //
    // Palette for color print colors
    //
    Palette color_print_colors;
};

} // namespace libvgcode

#endif // VGCODE_BITSET_HPP
