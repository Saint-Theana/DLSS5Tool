#pragma once
#include <atomic>

namespace Realtime {
inline std::atomic<bool> supervisedStop{false};
inline std::atomic<bool> stopAvailable{false};
inline std::atomic<bool> controlAvailable{false};
inline const char* StopHint() noexcept {
    if (!stopAvailable.load()) return "停止快捷键不可用 · 请回主界面停止";
    if (!controlAvailable.load()) return "Ctrl+Alt+F10 退出增强 · 调参快捷键被占用，请回主界面调参";
    return supervisedStop.load() ? "Ctrl+Alt+F10 退出增强 · Ctrl+Alt+P 调参／返回 · 停止无响应时强制退出"
                                 : "Ctrl+Alt+F10 退出增强 · Ctrl+Alt+P 调参／返回";
}
}
