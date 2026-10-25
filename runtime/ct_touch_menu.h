// Captain Toad's Android on-screen controls opacity (runtime/ct_touch_menu.cpp): Settings > Display >
// Touch controls and the menu button's menu set it, android TouchControls.java draws with it.
#pragma once

namespace ct_touch {
constexpr float kOpacityMin = 0.1f;
float opacity();            // 0.1..1 (1: as the reference draws the controls), saved in settings.ini
void set_opacity(float o);  // main thread
}  // namespace ct_touch
