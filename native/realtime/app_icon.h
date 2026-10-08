#pragma once
#include <windows.h>

namespace Realtime {
// Owned handles are kept on this output window only. DPI changes replace them;
// shutdown releases them. No dependency on an external icon path at runtime.
inline void ReleaseOutputIcon(HWND window, bool isSmall) noexcept {
    const auto key = isSmall ? L"DLSS5Tool.Icon.Small" : L"DLSS5Tool.Icon.Big";
    const auto icon = reinterpret_cast<HICON>(RemovePropW(window, key));
    if (icon) {
        SendMessageW(window, WM_SETICON, isSmall ? ICON_SMALL : ICON_BIG, 0);
        DestroyIcon(icon);
    }
}

inline void ReleaseOutputIcons(HWND window) noexcept {
    ReleaseOutputIcon(window, true);
    ReleaseOutputIcon(window, false);
}

inline bool SetOutputIcon(HWND window, UINT dpi, bool isSmall) noexcept {
    const auto key = isSmall ? L"DLSS5Tool.Icon.Small" : L"DLSS5Tool.Icon.Big";
    const int width = GetSystemMetricsForDpi(isSmall ? SM_CXSMICON : SM_CXICON, dpi);
    const int height = GetSystemMetricsForDpi(isSmall ? SM_CYSMICON : SM_CYICON, dpi);
    const auto icon = static_cast<HICON>(LoadImageW(GetModuleHandleW(nullptr),
        MAKEINTRESOURCEW(101), IMAGE_ICON, width, height, 0));
    if (!icon) return false;
    const auto previous = reinterpret_cast<HICON>(GetPropW(window, key));
    if (!SetPropW(window, key, icon)) {
        DestroyIcon(icon);
        return false;
    }
    SendMessageW(window, WM_SETICON, isSmall ? ICON_SMALL : ICON_BIG, reinterpret_cast<LPARAM>(icon));
    if (previous) DestroyIcon(previous);
    return true;
}

inline void HandleOutputIconMessage(HWND window, UINT message, WPARAM wp) noexcept {
    if (message == WM_CREATE || message == WM_DPICHANGED) {
        const UINT dpi = message == WM_DPICHANGED ? HIWORD(wp) : GetDpiForWindow(window);
        SetOutputIcon(window, dpi ? dpi : 96, true);
        SetOutputIcon(window, dpi ? dpi : 96, false);
    } else if (message == WM_DESTROY) {
        ReleaseOutputIcons(window);
    }
}
}
