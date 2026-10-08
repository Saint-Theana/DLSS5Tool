#include "guidance_model.h"
#include <cassert>
using namespace Realtime;
int main() {
    GuidanceModel m;
    assert(!m.CenterVisible(0));
    m.Start(100);
    assert(m.CenterVisible(60000) && m.IntroAlpha(60000) == 0);
    m.Present(70000);
    assert(m.phase == FeedbackPhase::Running && m.IntroAlpha(75000) == 1);
    assert(m.CenterVisible(70999) && !m.CenterVisible(71000));
    assert(m.IntroAlpha(75150) > .49f && m.IntroAlpha(75150) < .51f);
    assert(m.IntroAlpha(75300) == 0);
    m.Present(76000); assert(m.firstFrame == 70000);
    m.Stop(76000); m.Present(76001);
    assert(m.phase == FeedbackPhase::Stopping && m.IntroAlpha(76001) == 0);
    m.Idle(76002); assert(m.CenterVisible(76002) && !m.CenterVisible(77002));
    m.Start(80000); m.Stop(80001); m.Idle(80002);
    assert(m.phase == FeedbackPhase::Stopped && !m.presented);
    m.Start(90000); m.Fail(90100); m.Idle(90101); m.Present(90102);
    assert(m.phase == FeedbackPhase::Failed && !m.presented);
    assert(m.CenterVisible(93599) && !m.CenterVisible(93600));
    m.Start(100000); assert(!m.presented && m.firstFrame == 0);
}
