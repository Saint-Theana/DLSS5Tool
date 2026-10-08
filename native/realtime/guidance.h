#pragma once
#include "guidance_model.h"
#include <windows.h>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>

namespace Realtime {
inline uint64_t GuidanceNow() {
    return uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
struct GuidanceSnapshot {
    GuidanceModel timing;
    HWND source = nullptr, output = nullptr;
    DWORD sourcePid = 0;
    RECT bounds{};
    bool dlss = false;
};
inline std::mutex guidanceMutex;
inline GuidanceSnapshot guidance;
inline std::atomic<int> controlMode{0}; // 0 closed, 1 editing, 2 preview
inline std::atomic<HWND> controlWindow{nullptr}, feedbackWindow{nullptr};
inline std::atomic<float> drawnToolbarAlpha{0}, drawnStopAlpha{0};
inline GuidanceSnapshot ReadGuidance() { std::lock_guard lock(guidanceMutex); return guidance; }
inline void BeginGuidance(HWND source, bool dlss) {
    std::lock_guard lock(guidanceMutex);
    guidance = {}; guidance.source = source; guidance.dlss = dlss;
    GetWindowThreadProcessId(source, &guidance.sourcePid);
    GetWindowRect(source, &guidance.bounds);
    guidance.timing.Start(GuidanceNow());
    controlMode = 0; controlWindow = nullptr;
}
inline void BindGuidanceOutput(HWND output) {
    std::lock_guard lock(guidanceMutex);
    guidance.output = output;
    GetWindowRect(output, &guidance.bounds);
}
inline void GuidancePresented(HWND output) {
    std::lock_guard lock(guidanceMutex);
    if (guidance.output != output) return;
    GetWindowRect(output, &guidance.bounds);
    guidance.timing.Present(GuidanceNow());
}
inline void StopGuidance() { std::lock_guard lock(guidanceMutex); guidance.timing.Stop(GuidanceNow()); }
inline void FailGuidance() { std::lock_guard lock(guidanceMutex); guidance.timing.Fail(GuidanceNow()); }
inline void GuidanceState(int state) {
    std::lock_guard lock(guidanceMutex);
    // Ignore old-session teardown while a replacement has not bound its output.
    if (guidance.timing.phase == FeedbackPhase::Starting && !guidance.output) return;
    if (state == 3) guidance.timing.Stop(GuidanceNow());
    if (state == 0) { guidance.timing.Idle(GuidanceNow()); controlMode = 0; controlWindow = nullptr; }
}
inline float IntroAlpha() { return ReadGuidance().timing.IntroAlpha(GuidanceNow()); }
class CenterFeedback {
public:
    CenterFeedback();
    ~CenterFeedback();
private:
    void Run();
    std::atomic<bool> _done{false};
    std::thread _thread;
};
}
