#include "hotkeys.h"
#include "safety_state.h"
#include <cassert>

int main() {
    using namespace Realtime;
    auto keys = ParseHotkeys(nullptr);
    assert(keys[0].key == VK_F10 && keys[3].key == 'P');
    nlohmann::json value = nlohmann::json::object();
    for (const auto& key : keys)
        value[key.action] = {{"modifiers", key.modifiers}, {"key", key.key}, {"label", key.label}};
    value["stop"] = {{"modifiers", 6}, {"key", VK_F9}, {"label", "Ctrl+Shift+F9"}};
    keys = ParseHotkeys(value);
    assert(keys[0].label == "Ctrl+Shift+F9" && keys[0].modifiers == 6);
    stopAvailable = controlAvailable = supervisedStop = true;
    ConfigureStopHint(keys[0].label, keys[3].label);
    assert(std::string(StopHint()).find("Ctrl+Shift+F9") != std::string::npos);
    assert(std::string(StopHint()).find("Ctrl+Alt+F10") == std::string::npos);
    auto reject = [](const nlohmann::json& bad) {
        bool rejected = false;
        try { ParseHotkeys(bad); } catch (...) { rejected = true; }
        assert(rejected);
    };
    auto invalid = value;
    invalid["compare"] = value["stop"];
    reject(invalid);
    for (int key : {VK_F12, VK_LWIN, VK_SPACE, VK_F24 + 1}) {
        invalid = value;
        invalid["stop"]["key"] = key;
        reject(invalid);
    }
    for (int modifier : {0, 4, 8, 0x4003}) {
        invalid = value;
        invalid["stop"]["modifiers"] = modifier;
        reject(invalid);
    }
    invalid = value;
    invalid["stop"]["label"] = "wrong";
    reject(invalid);
    invalid = value;
    invalid["stop"]["key"] = 120.5;
    reject(invalid);
    invalid = value;
    invalid.erase("stop");
    reject(invalid);
}
