#include <catch2/catch_all.hpp>
#include "slic3r/GUI/Widgets/StateColor.hpp"

namespace {
struct ThemeReset {
    ThemeReset() { reset(); }
    ~ThemeReset() { reset(); }
    static void reset() {
        StateColor::SetDarkMode(false);
        StateColor::SetAccentColor(wxColour("#00E5FF"));
        for (size_t i = 0; i < static_cast<size_t>(StateColor::ThemeColor::Count); ++i)
            StateColor::SetThemeColor(static_cast<StateColor::ThemeColor>(i), wxColour());
    }
};
}

TEST_CASE("Main interface palette overrides and defaults", "[OrcaBrick][Theme]")
{
    ThemeReset reset;
    using Role = StateColor::ThemeColor;
    StateColor::SetDarkMode(true);
    CHECK(StateColor::darkModeColorFor(wxColour("#FFFFFF")) == wxColour("#2D2D31"));
    StateColor::SetThemeColor(Role::Window, wxColour("#713355"));
    CHECK(StateColor::darkModeColorFor(wxColour("#FFFFFF")) == wxColour("#713355"));
    CHECK(StateColor::lightModeColorFor(wxColour("#2D2D31")) == wxColour("#713355"));
    CHECK(StateColor::IsDarkMode());

    // Choosing the light default explicitly in dark mode must still honour that colour.
    StateColor::SetThemeColor(Role::Window, wxColour("#FFFFFF"));
    CHECK(StateColor::darkModeColorFor(wxColour("#FFFFFF")) == wxColour("#FFFFFF"));
    CHECK(StateColor::IsDarkMode());
    StateColor::SetThemeColor(Role::Window, wxColour());
    CHECK(StateColor::darkModeColorFor(wxColour("#FFFFFF")) == wxColour("#2D2D31"));

    StateColor::SetThemeColor(Role::Text, wxColour("#FEEDAB"));
    CHECK(StateColor::darkModeColorFor(wxColour("#262E30")) == wxColour("#FEEDAB"));
    CHECK(StateColor::lightModeColorFor(wxColour("#EFEFF0")) == wxColour("#FEEDAB"));
    CHECK(StateColor::darkModeColorFor(wxColour("#D01B1B")) == wxColour("#BB2A3A"));
}

TEST_CASE("Accent choices survive token equality and hover overrides", "[OrcaBrick][Theme]")
{
    ThemeReset reset;
    using Role = StateColor::ThemeColor;
    StateColor::SetDarkMode(true);
    StateColor::SetAccentColor(wxColour("#009688"));
    CHECK(StateColor::darkModeColorFor(wxColour("#009688")) == wxColour("#009688"));
    StateColor::SetThemeColor(Role::AccentHover, wxColour("#CC3366"));
    CHECK(StateColor::darkModeColorFor(wxColour("#26A69A")) == wxColour("#CC3366"));
    StateColor::SetThemeColor(Role::AccentLight, wxColour("#443366"));
    CHECK(StateColor::lightModeColorFor(wxColour("#E5F0EE")) == wxColour("#443366"));
}
