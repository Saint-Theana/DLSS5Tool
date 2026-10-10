#pragma once
#include <Windows.h>
#include <nlohmann/json.hpp>
#include <array>
#include <set>
#include <stdexcept>
#include <string>

namespace Realtime {
struct Hotkey {
    const char* action;
    UINT modifiers;
    UINT key;
    std::string label;
};
using Hotkeys = std::array<Hotkey, 4>;

inline Hotkeys ParseHotkeys(const nlohmann::json& value) {
    Hotkeys keys{{{"stop", 3, VK_F10, "Ctrl+Alt+F10"}, {"compare", 3, 'C', "Ctrl+Alt+C"},
                  {"profiler", 3, 'F', "Ctrl+Alt+F"}, {"parameters", 3, 'P', "Ctrl+Alt+P"}}};
    if (value.is_null()) return keys;
    if (!value.is_object() || value.size() != keys.size()) throw std::runtime_error("Invalid hotkey settings");
    std::set<std::string> labels;
    for (auto& binding : keys) {
        const auto& entry = value.at(binding.action);
        if (!entry.at("modifiers").is_number_integer() || !entry.at("key").is_number_integer())
            throw std::runtime_error("Invalid hotkey numbers");
        const int modifiers = entry.at("modifiers").get<int>(), key = entry.at("key").get<int>();
        if (modifiers < 1 || modifiers > 7 || !(modifiers & (MOD_CONTROL | MOD_ALT)) ||
            !((key >= 'A' && key <= 'Z') || (key >= '0' && key <= '9') || (key >= VK_F1 && key <= VK_F24 && key != VK_F12)) ||
            (key == VK_F4 && (modifiers & MOD_ALT) && !(modifiers & MOD_CONTROL)))
            throw std::runtime_error("Unsupported hotkey combination");
        std::string label;
        if (modifiers & MOD_CONTROL) label += "Ctrl+";
        if (modifiers & MOD_ALT) label += "Alt+";
        if (modifiers & MOD_SHIFT) label += "Shift+";
        label += key >= VK_F1 ? "F" + std::to_string(key - VK_F1 + 1) : std::string(1, char(key));
        if (entry.at("label") != label || !labels.insert(label).second)
            throw std::runtime_error("Duplicate or mismatched hotkey label");
        binding.modifiers = UINT(modifiers);
        binding.key = UINT(key);
        binding.label = std::move(label);
    }
    return keys;
}

inline Hotkeys LoadHotkeys() {
    char buffer[4096]{};
    const DWORD size = GetEnvironmentVariableA("DLSS5_REALTIME_HOTKEYS", buffer, DWORD(sizeof(buffer)));
    if (size >= sizeof(buffer)) throw std::runtime_error("Hotkey settings too large");
    return ParseHotkeys(size ? nlohmann::json::parse(buffer) : nlohmann::json());
}
}
