// SPDX-License-Identifier: GPL-3.0-only
#include "telemetry.h"
#include <cassert>

int main() {
    using namespace Realtime;
    ResetMetrics();
    Captured(0);
    Submitted(0, 0, false, 1);
    Submitted(0, 0, false, 1); // static quality redraw is not frame generation
    auto m = ReadMetrics();
    assert(m.real == 1 && m.submitted == 2 && m.generated == 0);
    assert(m.ageSamples == 1);
    Submitted(0, 0, true, 1);
    Captured(1);
    Submitted(1, 0, false, 3);
    m = ReadMetrics();
    assert(m.real == 2 && m.generated == 3 && m.submitted == 4);
    Submitted(2, 0, false, std::nullopt);
    assert(!ReadMetrics().generatedKnown);
    ResetMetrics();
    Submitted(1, 0, false, 1);
    assert(ReadMetrics().ageSamples == 0); // never reuse another run's dequeue
    CaptureDrained(5);
    CaptureDrained(0);
    NrEvaluated(true); NrEvaluated(false);
    m = ReadMetrics();
    assert(m.droppedCapture == 4 && m.nrEvaluations == 1 && m.nrFailures == 1);
    for (uint64_t i = 2; i < 602; ++i) {
        Captured(i); Submitted(i, 0, false, 1); Processed(1); NrGpu(2);
    }
    m = ReadMetrics();
    assert(m.ageSamples == 512 && m.processSamples == 512);
    assert(m.nrGpuP95 == 2 && m.processP95 == 1);
}
