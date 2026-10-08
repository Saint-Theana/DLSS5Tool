#include "guidance.h"
#include <string>

namespace Realtime {
namespace {
LRESULT CALLBACK FeedbackProc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam) {
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    if (msg == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
    if (msg == WM_ERASEBKGND) return 1;
    if (msg == WM_PAINT) {
        PAINTSTRUCT paint{};
        HDC dc = BeginPaint(hwnd, &paint);
        RECT rect{}; GetClientRect(hwnd, &rect);
        auto brush = CreateSolidBrush(RGB(24, 29, 36)); FillRect(dc, &rect, brush); DeleteObject(brush);
        const int dpi = int(GetDpiForWindow(hwnd));
        auto font = CreateFontW(-MulDiv(19, dpi, 96), 0, 0, 0, FW_MEDIUM, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
            DEFAULT_PITCH, L"Microsoft YaHei UI");
        auto old = SelectObject(dc, font); SetBkMode(dc, TRANSPARENT); SetTextColor(dc, RGB(240, 246, 251));
        wchar_t text[256]{}; GetWindowTextW(hwnd, text, 256);
        DrawTextW(dc, text, -1, &rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
        SelectObject(dc, old); DeleteObject(font); EndPaint(hwnd, &paint); return 0;
    }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}
std::wstring Message(const GuidanceSnapshot& value) {
    const auto name = value.dlss ? L"DLSS 增强" : L"实时增强";
    switch (value.timing.phase) {
    case FeedbackPhase::Starting: return std::wstring(value.dlss ? L"正在启用 " : L"正在启用") + name + L"…";
    case FeedbackPhase::Running: return std::wstring(name) + L"已开启";
    case FeedbackPhase::Stopping: return L"正在退出增强…";
    case FeedbackPhase::Stopped: return L"已退出增强";
    case FeedbackPhase::Failed: return L"增强未能完成 · 请查看主界面提示";
    default: return {};
    }
}
}
CenterFeedback::CenterFeedback() : _thread([this] { Run(); }) {}
CenterFeedback::~CenterFeedback() { _done = true; if (_thread.joinable()) _thread.join(); }
void CenterFeedback::Run() {
    WNDCLASSW wc{}; wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpfnWndProc = FeedbackProc; wc.lpszClassName = L"DLSS5_RealtimeFeedback";
    if (!RegisterClassW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return;
    HWND hwnd = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED,
        wc.lpszClassName, L"", WS_POPUP, 0, 0, 1, 1, nullptr, nullptr, wc.hInstance, nullptr);
    if (!hwnd) return;
    feedbackWindow = hwnd;
    SetLayeredWindowAttributes(hwnd, 0, 230, LWA_ALPHA);
    SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE);
    std::wstring previous;
    while (!_done) {
        MSG msg{};
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        auto snapshot = ReadGuidance();
        DWORD sourcePid = 0; GetWindowThreadProcessId(snapshot.source, &sourcePid);
        HWND foreground = GetForegroundWindow();
        const bool owned = foreground == snapshot.source || foreground == snapshot.output || foreground == controlWindow.load();
        if (!snapshot.timing.CenterVisible(GuidanceNow()) || !owned || !IsWindow(snapshot.source) ||
            sourcePid != snapshot.sourcePid || IsIconic(snapshot.source)) {
            ShowWindow(hwnd, SW_HIDE);
        } else {
            if (IsWindow(snapshot.output)) GetWindowRect(snapshot.output, &snapshot.bounds);
            else GetWindowRect(snapshot.source, &snapshot.bounds);
            const UINT dpi = GetDpiForWindow(snapshot.source);
            const int width = std::min(int(snapshot.bounds.right - snapshot.bounds.left), MulDiv(460, dpi, 96));
            const int height = MulDiv(62, dpi, 96);
            const auto text = Message(snapshot);
            if (text != previous) { SetWindowTextW(hwnd, text.c_str()); InvalidateRect(hwnd, nullptr, FALSE); previous = text; }
            SetWindowPos(hwnd, HWND_TOPMOST, (snapshot.bounds.left + snapshot.bounds.right - width) / 2,
                (snapshot.bounds.top + snapshot.bounds.bottom - height) / 2, width, height, SWP_NOACTIVATE | SWP_SHOWWINDOW);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
    feedbackWindow = nullptr; DestroyWindow(hwnd);
}
}
