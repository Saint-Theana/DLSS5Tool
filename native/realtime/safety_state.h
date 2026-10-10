#pragma once
#include <atomic>
#include <string>

namespace Realtime {
inline std::atomic<bool> supervisedStop{false};
inline std::atomic<bool> stopAvailable{false};
inline std::atomic<bool> controlAvailable{false};
// Set once before rendering starts, then read-only across renderer threads.
inline std::string stopHintText;
inline void ConfigureStopHint(const std::string& stop, const std::string& control) {
    if (!stopAvailable.load()) { stopHintText = "停止快捷键不可用 · 请回主界面停止"; return; }
    stopHintText = stop + " 退出增强 · ";
    stopHintText += controlAvailable.load() ? control + " 调参／返回" : "调参快捷键不可用，请回主界面调参";
    if (supervisedStop.load()) stopHintText += " · 停止无响应时强制退出";
}
inline const char* StopHint() noexcept { return stopHintText.c_str(); }
}
