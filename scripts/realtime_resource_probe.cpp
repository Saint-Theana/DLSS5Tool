// Minimal diagnostic for the unpackaged parameter-localization resource path.
// No capture, GPU work, app settings or registered system configuration changes.
#include <cstdio>
#include <winrt/Windows.ApplicationModel.Resources.h>
#include <winrt/Windows.ApplicationModel.Resources.Core.h>
#include <winrt/Windows.Foundation.Collections.h>

int main() {
    winrt::init_apartment(winrt::apartment_type::single_threaded);
    try {
        using namespace winrt::Windows::ApplicationModel::Resources;
        std::puts("before ResourceContext::GetForViewIndependentUse");
        std::fflush(stdout);
        const auto context = Core::ResourceContext::GetForViewIndependentUse();
        std::puts("after ResourceContext; before language lookup");
        std::fflush(stdout);
        const auto language = context.QualifierValues().Lookup(L"Language");
        std::puts("after language lookup; before ResourceLoader");
        std::fflush(stdout);
        const auto loader = ResourceLoader::GetForViewIndependentUse(L"Magpie/Resources");
        std::puts("after ResourceLoader");
        std::fflush(stdout);
    } catch (const winrt::hresult_error& error) {
        std::printf("caught HRESULT 0x%08x\n", static_cast<unsigned>(error.code()));
        return 2;
    } catch (...) {
        std::puts("caught other exception");
        return 3;
    }
    return 0;
}
