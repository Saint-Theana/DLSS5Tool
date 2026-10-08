#pragma once
#include <algorithm>
#include <cstdint>

namespace Realtime {
enum class FeedbackPhase { None, Starting, Running, Stopping, Stopped, Failed };
// Milliseconds supplied by the caller keep timing deterministic and testable.
struct GuidanceModel {
    FeedbackPhase phase = FeedbackPhase::None;
    uint64_t firstFrame = 0, changed = 0;
    bool presented = false;
    void Start(uint64_t now) { phase = FeedbackPhase::Starting; changed = now; firstFrame = 0; presented = false; }
    void Present(uint64_t now) {
        if (phase != FeedbackPhase::Starting) return;
        phase = FeedbackPhase::Running; firstFrame = changed = now; presented = true;
    }
    void Stop(uint64_t now) {
        if (phase == FeedbackPhase::Starting || phase == FeedbackPhase::Running) {
            phase = FeedbackPhase::Stopping; changed = now;
        }
    }
    void Idle(uint64_t now) {
        if (phase == FeedbackPhase::Stopping || phase == FeedbackPhase::Running) {
            phase = FeedbackPhase::Stopped; changed = now;
        }
    }
    void Fail(uint64_t now) { phase = FeedbackPhase::Failed; changed = now; }
    float IntroAlpha(uint64_t now) const {
        if (!presented || phase != FeedbackPhase::Running) return 0;
        return std::clamp(1.0f - float(now - firstFrame > 5000 ? now - firstFrame - 5000 : 0) / 300, 0.0f, 1.0f);
    }
    bool CenterVisible(uint64_t now) const {
        switch (phase) {
        case FeedbackPhase::Starting: case FeedbackPhase::Stopping: return true;
        case FeedbackPhase::Running: case FeedbackPhase::Stopped: return now - changed < 1000;
        case FeedbackPhase::Failed: return now - changed < 3500;
        default: return false;
        }
    }
};
}
