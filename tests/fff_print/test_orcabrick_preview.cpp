#include <catch2/catch_all.hpp>

#include <algorithm>
#include <cstdint>
#include <set>
#include <vector>

#include "libslic3r/GCode/GCodeProcessor.hpp"

using namespace Slic3r;

// These tests stand in for the thing that is otherwise only observable by dragging the Preview
// layer slider: whether the G-code the slicer emits maps onto preview layers the way libvgcode
// requires. libvgcode's Layers::update() walks the moves in order and starts a new layer exactly
// when vertex.layer_id == items.size(), then binary searches the layer Zs. Break either and the
// preview shows the wrong geometry, or none.

namespace {

using Move = GCodeProcessorResult::MoveVertex;

Move extrusion(unsigned int layer_id, float z, float height)
{
    Move m;
    m.type           = EMoveType::Extrude;
    m.extrusion_role = erPerimeter;
    m.layer_id       = layer_id;
    m.height         = height;
    m.position       = Vec3f(0.0f, 0.0f, z);
    return m;
}

Move travel(unsigned int layer_id, float z)
{
    Move m;
    m.type     = EMoveType::Travel;
    m.layer_id = layer_id;
    m.position = Vec3f(0.0f, 0.0f, z);
    return m;
}

// One printed layer as Arachne emits it with Bricklaying on: walls inset by inset with the odd
// ones raised by 0.5 * path.height, then infill at the nominal Z, then the move off the layer.
// path.height varies, so the raised walls land at a spread of Zs rather than one.
void append_bricklaying_layer(std::vector<Move> &moves, unsigned int layer_id, float nominal_z,
                              const std::vector<float> &wall_heights)
{
    for (size_t i = 0; i < wall_heights.size(); ++i) {
        const float h = wall_heights[i];
        const bool  raised = (i % 2) == 1;
        moves.emplace_back(extrusion(layer_id, raised ? nominal_z + 0.5f * h : nominal_z, h));
    }
    for (int i = 0; i < 4; ++i)
        moves.emplace_back(extrusion(layer_id, nominal_z, 0.2f)); // infill, nominal height
    moves.emplace_back(travel(layer_id, nominal_z));
}

struct Split
{
    bool                 happened{ false };
    std::vector<float>   zs;
    std::vector<uint8_t> upper_half;
};

Split run(std::vector<Move> &moves, bool spiral_vase = false)
{
    Split out;
    out.happened = GCodeProcessor::split_staggered_preview_layers(moves, out.zs, out.upper_half,
                                                                  spiral_vase);
    return out;
}

// Exactly what libvgcode's Layers::update() assumes about the move stream.
void require_libvgcode_contract(const std::vector<Move> &moves, const Split &split)
{
    REQUIRE(split.zs.size() == split.upper_half.size());

    // ids never go backwards and never skip, so every id starts exactly one layer, which is
    // what Layers::update()'s "vertex.layer_id == items.size()" relies on
    unsigned int previous = 0;
    for (const Move &m : moves) {
        REQUIRE(m.layer_id >= previous);
        REQUIRE(m.layer_id <= previous + 1);
        previous = m.layer_id;
    }
    std::set<unsigned int> ids;
    for (const Move &m : moves)
        ids.insert(m.layer_id);
    REQUIRE(*ids.begin() == 0u);
    REQUIRE(*ids.rbegin() + 1 == ids.size());
    REQUIRE(ids.size() == split.zs.size());

    // the Z sequence is what get_layer_id_at() binary searches
    for (size_t i = 1; i < split.zs.size(); ++i)
        REQUIRE(split.zs[i] >= split.zs[i - 1]);
}

} // namespace

SCENARIO("Bricklaying layers become two preview steps", "[OrcaBrick][Preview]")
{
    std::vector<Move> moves;
    moves.emplace_back(travel(0, 0.0f)); // start G-code
    moves.emplace_back(travel(0, 0.0f));
    append_bricklaying_layer(moves, 1, 0.2f, { 0.2f, 0.2f, 0.2f, 0.15f });
    append_bricklaying_layer(moves, 2, 0.4f, { 0.2f, 0.12f, 0.2f, 0.2f });
    append_bricklaying_layer(moves, 3, 0.6f, { 0.2f, 0.2f });

    const Split split = run(moves);

    THEN("the split happens and libvgcode's contract holds") {
        REQUIRE(split.happened);
        require_libvgcode_contract(moves, split);
    }

    THEN("each printed layer contributes a nominal step and a raised one above it") {
        // 1 start layer + 3 printed layers, each split in two
        REQUIRE(split.zs.size() == 7);
        for (size_t i = 1; i + 1 < split.zs.size(); i += 2) {
            REQUIRE(split.upper_half[i] == 0);     // nominal half
            REQUIRE(split.upper_half[i + 1] == 1); // raised half
            REQUIRE(split.zs[i + 1] > split.zs[i]);
        }
    }

    THEN("the nominal step's Z excludes every raised wall, the raised step's includes them all") {
        for (size_t lower = 0; lower + 1 < split.zs.size(); ++lower) {
            if (split.upper_half[lower] || !split.upper_half[lower + 1])
                continue; // not a split pair

            // both halves cover the one printed layer
            float highest = 0.0f;
            bool  any     = false;
            for (const Move &m : moves) {
                if (m.type != EMoveType::Extrude)
                    continue;
                if (m.layer_id != lower && m.layer_id != lower + 1)
                    continue;
                highest = any ? std::max(highest, m.position.z()) : m.position.z();
                any     = true;
            }
            REQUIRE(any);
            // something sits above the nominal step, so the viewer's cutoff hides it there ...
            REQUIRE(highest > split.zs[lower]);
            // ... and nothing sits above the raised step, so it hides nothing there
            REQUIRE(split.zs[lower + 1] >= highest);
        }
    }
}

SCENARIO("Layers that are not Bricklaying are left alone", "[OrcaBrick][Preview]")
{
    GIVEN("a scarf seam, which ramps through a continuum of Zs") {
        std::vector<Move> moves;
        moves.emplace_back(travel(0, 0.0f));
        moves.emplace_back(travel(0, 0.0f));
        for (int i = 0; i <= 40; ++i)
            moves.emplace_back(extrusion(1, 0.2f + 0.2f * float(i) / 40.0f, 0.2f));
        for (int i = 0; i < 4; ++i)
            moves.emplace_back(extrusion(1, 0.2f, 0.2f));

        std::vector<Move> before = moves;
        const Split       split  = run(moves);

        THEN("nothing is split and the layer ids are untouched") {
            REQUIRE_FALSE(split.happened);
            REQUIRE(split.zs.empty());
            for (size_t i = 0; i < moves.size(); ++i)
                REQUIRE(moves[i].layer_id == before[i].layer_id);
        }
    }

    GIVEN("a plain print with one Z per layer") {
        std::vector<Move> moves;
        moves.emplace_back(travel(0, 0.0f));
        for (unsigned int layer = 1; layer <= 3; ++layer)
            for (int i = 0; i < 6; ++i)
                moves.emplace_back(extrusion(layer, 0.2f * float(layer), 0.2f));

        std::vector<Move> before = moves;
        const Split       split  = run(moves);

        THEN("nothing is split") {
            REQUIRE_FALSE(split.happened);
            for (size_t i = 0; i < moves.size(); ++i)
                REQUIRE(moves[i].layer_id == before[i].layer_id);
        }
    }

    GIVEN("spiral vase mode, where Z rises continuously by design") {
        std::vector<Move> moves;
        moves.emplace_back(travel(0, 0.0f));
        for (int i = 0; i < 20; ++i)
            moves.emplace_back(extrusion(1, 0.2f + 0.01f * float(i), 0.2f));

        const Split split = run(moves, /* spiral_vase */ true);

        THEN("it is skipped outright") {
            REQUIRE_FALSE(split.happened);
            REQUIRE(split.zs.empty());
        }
    }
}
