// SPDX-License-Identifier: GPL-3.0-only
// Small CPU-pointer bridge for the shared Veyra residual compute shader.
//
// The normal realtime host already owns D3D11 textures.  Local media goes
// through Python shared-memory frames instead, so this adapter deliberately
// keeps the public surface tiny: upload base/NR output, run the same shader,
// and read back one composed frame.  The Python caller keeps a context per
// worker thread and falls back to its reference implementation on any error.

#include "quality.h"

#include <d3d11.h>
#include <winrt/base.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <new>

#pragma comment(lib, "d3d11.lib")

namespace {

class Bridge final {
public:
    bool Initialize() noexcept {
        const D3D_FEATURE_LEVEL levels[] = {
            D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0,
        };
        HRESULT result = D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            levels, ARRAYSIZE(levels), D3D11_SDK_VERSION,
            device.put(), nullptr, context.put());
        // Older Windows 10 drivers reject a feature-level list containing
        // 11_1 with E_INVALIDARG even though 11_0 is fully available.
        if (result == E_INVALIDARG) {
            device = nullptr;
            context = nullptr;
            const D3D_FEATURE_LEVEL fallback = D3D_FEATURE_LEVEL_11_0;
            result = D3D11CreateDevice(
                nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                &fallback, 1, D3D11_SDK_VERSION,
                device.put(), nullptr, context.put());
        }
        if (FAILED(result)) return false;
        return device != nullptr && context != nullptr;
    }

    bool Compose(const void* base, const void* processed, void* output,
        int width, int height, int format_id, const float* values,
        int value_count) noexcept {
        if (!base || !processed || !output || !values || value_count < 32 ||
            width <= 0 || height <= 0 || width > 16384 || height > 16384 ||
            (format_id != 0 && format_id != 1)) return false;
        const DXGI_FORMAT format = format_id == 1
            ? DXGI_FORMAT_R16G16B16A16_FLOAT
            : DXGI_FORMAT_R8G8B8A8_UNORM;
        if (!EnsureTextures(static_cast<UINT>(width), static_cast<UINT>(height), format))
            return false;

        const size_t row_pitch = static_cast<size_t>(width) * (format_id == 1 ? 8u : 4u);
        context->UpdateSubresource(base_texture.get(), 0, nullptr, base, row_pitch, 0);
        context->UpdateSubresource(nr_texture.get(), 0, nullptr, processed, row_pitch, 0);

        Realtime::QualitySettings settings{};
        std::memcpy(&settings, values,
            std::min<size_t>(sizeof(settings), static_cast<size_t>(value_count) * sizeof(float)));
        const bool hdr = settings.signedHdr > 0.5f;
        Realtime::SetQuality(settings);
        if (!composite.Draw(device.get(), context.get(), base_texture.get(),
                base_texture.get(), nr_texture.get(), readback.get(), hdr, true, false))
            return false;

        D3D11_MAPPED_SUBRESOURCE mapped{};
        if (FAILED(context->Map(readback.get(), 0, D3D11_MAP_READ, 0, &mapped)))
            return false;
        auto* destination = static_cast<unsigned char*>(output);
        const auto* source = static_cast<const unsigned char*>(mapped.pData);
        for (UINT row = 0; row < static_cast<UINT>(height); ++row) {
            std::memcpy(destination + static_cast<size_t>(row) * row_pitch,
                source + static_cast<size_t>(row) * mapped.RowPitch, row_pitch);
        }
        context->Unmap(readback.get(), 0);
        return true;
    }

private:
    bool EnsureTextures(UINT width, UINT height, DXGI_FORMAT format) noexcept {
        if (base_texture && width_ == width && height_ == height && format_ == format)
            return true;
        base_texture = nullptr;
        nr_texture = nullptr;
        readback = nullptr;
        composite.Reset();

        D3D11_TEXTURE2D_DESC input{};
        input.Width = width;
        input.Height = height;
        input.MipLevels = 1;
        input.ArraySize = 1;
        input.Format = format;
        input.SampleDesc.Count = 1;
        input.Usage = D3D11_USAGE_DEFAULT;
        input.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        if (FAILED(device->CreateTexture2D(&input, nullptr, base_texture.put())) ||
            FAILED(device->CreateTexture2D(&input, nullptr, nr_texture.put()))) {
            base_texture = nullptr;
            nr_texture = nullptr;
            return false;
        }

        D3D11_TEXTURE2D_DESC staging = input;
        staging.Usage = D3D11_USAGE_STAGING;
        staging.BindFlags = 0;
        staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        if (FAILED(device->CreateTexture2D(&staging, nullptr, readback.put()))) {
            base_texture = nullptr;
            nr_texture = nullptr;
            return false;
        }
        width_ = width;
        height_ = height;
        format_ = format;
        return true;
    }

    winrt::com_ptr<ID3D11Device> device;
    winrt::com_ptr<ID3D11DeviceContext> context;
    winrt::com_ptr<ID3D11Texture2D> base_texture;
    winrt::com_ptr<ID3D11Texture2D> nr_texture;
    winrt::com_ptr<ID3D11Texture2D> readback;
    Realtime::ResidualComposite composite;
    UINT width_ = 0;
    UINT height_ = 0;
    DXGI_FORMAT format_ = DXGI_FORMAT_UNKNOWN;
};

} // namespace

extern "C" __declspec(dllexport) void* dlss5_quality_create() noexcept {
    auto* bridge = new (std::nothrow) Bridge();
    if (!bridge || !bridge->Initialize()) {
        delete bridge;
        return nullptr;
    }
    return bridge;
}

extern "C" __declspec(dllexport) void dlss5_quality_destroy(void* handle) noexcept {
    delete static_cast<Bridge*>(handle);
}

extern "C" __declspec(dllexport) int dlss5_quality_compose(
    void* handle, const void* base, const void* processed, void* output,
    int width, int height, int format_id, const float* values, int value_count) noexcept {
    auto* bridge = static_cast<Bridge*>(handle);
    return bridge && bridge->Compose(base, processed, output, width, height,
        format_id, values, value_count) ? 1 : 0;
}
