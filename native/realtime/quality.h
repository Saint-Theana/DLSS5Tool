// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <array>
#include <atomic>
#include <mutex>
#include <d3d11.h>
#include <winrt/base.h>

namespace Realtime {
// Matches Veyra's NrResidualComposite cbuffer. Rectangles are normalized to the
// preserved source, independent of NR's internal extent or output monitor DPI.
struct QualitySettings {
    float total = 1, darken = 1, brighten = 1, color = 1, luminance = 1;
    float protectionEnabled = 0, featherPixels = 12, signedHdr = 0;
    std::array<std::array<float, 4>, 4> regions{};
    float residualInput = 0;
    std::array<float, 3> padding{};
};
static_assert(sizeof(QualitySettings) == 112);
inline std::mutex qualityMutex;
inline QualitySettings qualitySettings;
inline std::atomic<uint64_t> qualityRevision = 0, appliedQualityRevision = 0;
inline void SetQuality(QualitySettings settings) {
    std::lock_guard lock(qualityMutex); qualitySettings = settings; ++qualityRevision;
}
inline QualitySettings GetQuality() {
    std::lock_guard lock(qualityMutex); return qualitySettings;
}

// Owned and used by one NR backend thread. No CPU pixel transfer; resources
// are released only after the owning Magpie backend has joined.
class ResidualComposite {
public:
    bool Draw(ID3D11Device* device, ID3D11DeviceContext* context,
        ID3D11Texture2D* base, ID3D11Texture2D* nrInput,
        ID3D11Texture2D* nrOutput, ID3D11Texture2D* output, bool hdr,
        bool applyControls = true, bool residualInput = false) noexcept;
private:
    winrt::com_ptr<ID3D11ComputeShader> shader;
    winrt::com_ptr<ID3D11Buffer> constants;
    winrt::com_ptr<ID3D11Texture2D> result;
    winrt::com_ptr<ID3D11UnorderedAccessView> uav;
    std::array<winrt::com_ptr<ID3D11ShaderResourceView>, 3> views;
    std::array<ID3D11Texture2D*, 3> textures{};
};
}
