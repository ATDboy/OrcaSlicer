///|/ Copyright (c) Prusa Research 2023 Enrico Turri @enricoturri1966, Pavel Mikuš @Godrak
///|/
///|/ libvgcode is released under the terms of the AGPLv3 or higher
///|/
#include "Layers.hpp"

#include "../include/PathVertex.hpp"
#include "Utils.hpp"

#include <assert.h>
#include <algorithm>

namespace libvgcode {

static bool is_colorprint_option(const PathVertex& v)
{
    return v.type == EMoveType::PausePrint || v.type == EMoveType::CustomGCode;
}

void Layers::update(const PathVertex& vertex, uint32_t vertex_id)
{
    if (m_items.empty() || vertex.layer_id == m_items.size()) {
        // this code assumes that gcode paths are sent sequentially, one layer after the other
        assert(vertex.layer_id == static_cast<uint32_t>(m_items.size()));
        Item& item = m_items.emplace_back(Item());
        // OrcaBrick: highest extrusion, not the last one - see the else branch below.
        if (vertex.type == EMoveType::Extrude && vertex.role != EGCodeExtrusionRole::Custom)
            item.z = vertex.position[2];
        item.range.set(vertex_id, vertex_id);
        item.times = vertex.times;
        item.contains_colorprint_options |= is_colorprint_option(vertex);
    }
    else {
        Item& item = m_items.back();
        // OrcaBrick: take the layer's highest extrusion rather than its last. Upstream's "last
        // extrusion wins" is arbitrary whenever a layer contains more than one Z - with Bricklaying
        // a layer ends on nominal-height infill, so the last extrusion would report the nominal Z
        // for a group whose whole point is the raised walls, and the Z sequence handed to
        // get_layer_id_at()'s binary search below would stop increasing.
        if (vertex.type == EMoveType::Extrude && vertex.role != EGCodeExtrusionRole::Custom &&
            vertex.position[2] > item.z)
            item.z = vertex.position[2];
        item.range.set_max(vertex_id);
        for (size_t i = 0; i < TIME_MODES_COUNT; ++i) {
            item.times[i] += vertex.times[i];
        }
        item.contains_colorprint_options |= is_colorprint_option(vertex);
    }
}

void Layers::reset()
{
    m_items.clear();
    m_view_range.reset();
    m_explicit_zs = false;
}

std::vector<float> Layers::get_times(ETimeMode mode) const
{
    std::vector<float> ret;
    if (mode < ETimeMode::COUNT) {
        for (const Item& item : m_items) {
            ret.emplace_back(item.times[static_cast<size_t>(mode)]);
        }
    }
    return ret;
}

std::vector<float> Layers::get_zs() const
{
    std::vector<float> ret;
    ret.reserve(m_items.size());
    for (const Item& item : m_items) {
        ret.emplace_back(item.z);
    }
    return ret;
}

void Layers::set_zs(const std::vector<float>& zs)
{
    if (zs.empty() || zs.size() != m_items.size())
        return;
    for (size_t i = 0; i < m_items.size(); ++i) {
        m_items[i].z = zs[i];
    }
    m_explicit_zs = true;
}

size_t Layers::get_layer_id_at(float z) const
{
    auto iter = std::upper_bound(m_items.begin(), m_items.end(), z, [](float z, const Item& item) { return item.z < z; });
    return std::distance(m_items.begin(), iter);
}

size_t Layers::size_in_bytes_cpu() const
{
    size_t ret = STDVEC_MEMSIZE(m_items, Item);
    return ret;
}

} // namespace libvgcode
