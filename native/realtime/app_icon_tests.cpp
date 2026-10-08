// Real HWND/resource validation without a renderer, GPU or visible window.
#include "app_icon.h"
#include <cassert>
#include <iostream>

LRESULT CALLBACK IconWndProc(HWND window, UINT message, WPARAM wp, LPARAM lp) {
    Realtime::HandleOutputIconMessage(window, message, wp);
    return DefWindowProcW(window, message, wp, lp);
}

void CheckIconSize(HWND window, UINT dpi, bool isSmall) {
    const auto icon = reinterpret_cast<HICON>(SendMessageW(window, WM_GETICON, isSmall ? ICON_SMALL : ICON_BIG, 0));
    assert(icon);
    ICONINFO info{};
    assert(GetIconInfo(icon, &info));
    BITMAP bitmap{};
    assert(GetObjectW(info.hbmColor, sizeof(bitmap), &bitmap));
    assert(bitmap.bmWidth == GetSystemMetricsForDpi(isSmall ? SM_CXSMICON : SM_CXICON, dpi));
    assert(bitmap.bmHeight == GetSystemMetricsForDpi(isSmall ? SM_CYSMICON : SM_CYICON, dpi));
    DeleteObject(info.hbmColor);
    DeleteObject(info.hbmMask);
}

int main() {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    WNDCLASSW klass{};
    klass.hInstance = GetModuleHandleW(nullptr);
    klass.lpfnWndProc = IconWndProc;
    klass.lpszClassName = L"DLSS5Tool.Icon.Validation";
    assert(RegisterClassW(&klass));
    const HWND warmup = CreateWindowW(klass.lpszClassName, L"Warmup", WS_OVERLAPPEDWINDOW,
        0, 0, 240, 160, nullptr, nullptr, klass.hInstance, nullptr);
    assert(warmup);
    assert(DestroyWindow(warmup));
    const DWORD before = GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS);
    for (int iteration = 0; iteration < 30; ++iteration) {
        const HWND window = CreateWindowW(klass.lpszClassName, L"Icon validation",
            WS_OVERLAPPEDWINDOW, 0, 0, 240, 160, nullptr, nullptr, klass.hInstance, nullptr);
        assert(window);
        const UINT actualDpi = GetDpiForWindow(window);
        CheckIconSize(window, actualDpi, true);
        CheckIconSize(window, actualDpi, false);
        for (const UINT dpi : {96u, 144u, 192u}) {
            SendMessageW(window, WM_DPICHANGED, MAKELONG(dpi, dpi), 0);
            CheckIconSize(window, dpi, true);
            CheckIconSize(window, dpi, false);
        }
        Realtime::ReleaseOutputIcons(window);
        assert(!GetPropW(window, L"DLSS5Tool.Icon.Small"));
        assert(!GetPropW(window, L"DLSS5Tool.Icon.Big"));
        assert(!SendMessageW(window, WM_GETICON, ICON_SMALL, 0));
        assert(!SendMessageW(window, WM_GETICON, ICON_BIG, 0));
        // Restore before destruction to exercise WM_DESTROY cleanup as well.
        Realtime::HandleOutputIconMessage(window, WM_CREATE, 0);
        assert(DestroyWindow(window));
    }
    const DWORD after = GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS);
    std::cout << "GDI " << before << " -> " << after << std::endl;
    assert(after <= before + 2);
    assert(UnregisterClassW(klass.lpszClassName, klass.hInstance));
    std::cout << "Output icons: create, 96/144/192 DPI, release, 30 restarts; GDI "
              << before << " -> " << after << '\n';
}
