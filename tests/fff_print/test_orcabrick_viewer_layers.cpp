#include <catch2/catch_all.hpp>
#include "libvgcode/src/Layers.hpp"
#include "libvgcode/include/PathVertex.hpp"

using namespace libvgcode;

TEST_CASE("Bricklaying halves select physical walls in interleaved G-code", "[OrcaBrick][Preview]")
{
    Layers layers;
    std::vector<PathVertex> vertices(5);
    // The final nominal extrusion carries the upper storage id. Both halves must still
    // include it as a candidate, then classify by Z. No trailing travel is required.
    const float zs[] = {0.2f, 0.3f, 0.2f, 0.275f, 0.2f};
    for (size_t i = 0; i < vertices.size(); ++i) {
        vertices[i].type = EMoveType::Extrude;
        vertices[i].role = EGCodeExtrusionRole::Perimeter;
        vertices[i].position = {float(i), 0.0f, zs[i]};
        vertices[i].layer_id = i == 4 ? 1 : 0;
        layers.update(vertices[i], uint32_t(i));
    }
    layers.set_zs({0.2f, 0.3f}, {0, 1});
    REQUIRE(layers.print_layer_start(1) == 0);
    REQUIRE(layers.print_layer_end(0) == 1);
    const size_t expected[] = {0, 1, 0, 1, 0};
    for (size_t i = 0; i < vertices.size(); ++i)
        REQUIRE(layers.preview_layer_id(vertices[i]) == expected[i]);

    for (uint32_t half = 0; half < 2; ++half) {
        layers.set_view_range(half, half);
        for (size_t i = 0; i < vertices.size(); ++i)
            REQUIRE(layers.extrusion_in_view(vertices[i]) == (expected[i] == half));
    }
    layers.set_view_range(0, 1);
    for (const auto& vertex : vertices)
        REQUIRE(layers.extrusion_in_view(vertex));

    SECTION("Z hop is not mistaken for a raised extrusion") {
        auto hop = vertices.front();
        hop.type = EMoveType::Travel;
        hop.position[2] = 1.0f;
        REQUIRE(layers.preview_layer_id(hop) == 0);
    }
    SECTION("Reset removes the split metadata") {
        layers.reset();
        REQUIRE_FALSE(layers.has_explicit_zs());
        REQUIRE(layers.preview_layer_id(vertices[1]) == vertices[1].layer_id);
    }
}
