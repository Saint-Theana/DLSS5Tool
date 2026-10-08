// SPDX-License-Identifier: GPL-3.0-only
#include "quality.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace Realtime;
using Pixel = std::array<float, 4>;

int main() {
    try {
        winrt::com_ptr<ID3D11Device> device;
        winrt::com_ptr<ID3D11DeviceContext> context;
        winrt::check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
            nullptr, 0, D3D11_SDK_VERSION, device.put(), nullptr, context.put()));
        auto texture = [&](uint32_t w, uint32_t h, Pixel color, bool staging = false) {
            D3D11_TEXTURE2D_DESC d{};
            d.Width = w; d.Height = h; d.MipLevels = 1; d.ArraySize = 1;
            d.SampleDesc.Count = 1; d.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
            d.Usage = staging ? D3D11_USAGE_STAGING : D3D11_USAGE_DEFAULT;
            d.BindFlags = staging ? 0 : D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
            d.CPUAccessFlags = staging ? D3D11_CPU_ACCESS_READ : 0;
            std::vector<Pixel> values(w*h, color);
            D3D11_SUBRESOURCE_DATA data{values.data(), w*sizeof(Pixel), 0};
            winrt::com_ptr<ID3D11Texture2D> t;
            winrt::check_hresult(device->CreateTexture2D(&d, staging ? nullptr : &data, t.put()));
            return t;
        };
        uint32_t tests = 0;
        auto run = [&](const char* label, Pixel b, Pixel n, QualitySettings q,
                       float expected, bool hdr = false, uint32_t lowW = 7, uint32_t lowH = 5,
                       int checkX = 3, int checkY = 2) {
            auto base = texture(7,5,b), input = texture(lowW,lowH,b), nr = texture(lowW,lowH,n);
            auto output = texture(7,5,{}), readback = texture(7,5,{},true);
            SetQuality(q);
            ResidualComposite composite;
            if (!composite.Draw(device.get(), context.get(), base.get(), input.get(), nr.get(), output.get(), hdr))
                throw std::runtime_error(std::string(label)+": draw failed");
            context->CopyResource(readback.get(), output.get());
            D3D11_MAPPED_SUBRESOURCE mapped{};
            winrt::check_hresult(context->Map(readback.get(),0,D3D11_MAP_READ,0,&mapped));
            bool valid = true;
            for (uint32_t y=0;y<5;++y) for (uint32_t x=0;x<7;++x) {
                const auto& p = reinterpret_cast<const Pixel*>(static_cast<const uint8_t*>(mapped.pData)+y*mapped.RowPitch)[x];
                for (float v:p) valid &= std::isfinite(v);
                if (x == checkX && y == checkY) valid &= std::abs(p[0]-expected) < 2e-4f;
                valid &= std::abs(p[3]-b[3]) < 1e-6f;
            }
            context->Unmap(readback.get(),0);
            if (!valid) throw std::runtime_error(std::string(label)+": pixel mismatch / nonfinite");
            ++tests; std::cout << label << " passed\n";
        };
        QualitySettings q;
        Pixel base{.4f,.4f,.4f,.7f}, changed{.5f,.5f,.5f,.2f};
        run("identity", base, changed, q, .5f);
        q.total=0; run("zero strength exact base", base, changed,q,.4f);
        q={}; run("valid zero residual",base,base,q,.4f);
        q.protectionEnabled=1; q.featherPixels=0; q.regions[0]={0,0,1,1};
        run("protected region exact base",base,changed,q,.4f);
        q.featherPixels=1; run("inward feather edge",base,changed,q,.45f,false,7,5,0,2);
        q={}; run("odd extent low resolution",base,changed,q,.5f,false,3,2);
        q.total=2; run("shadow safe overdrive",{.1f,.1f,.1f,1},{.05f,.05f,.05f,1},q,.025f);
        q={}; run("signed HDR",{-.2f,-.2f,-.2f,1},{-.3f,-.3f,-.3f,1},q,-.3f,true);
        run("HDR highlight unclipped",{3,3,3,1},{4,4,4,1},q,4,true);
        q.darken=0; run("darken suppression",base,{.3f,.3f,.3f,1},q,.4f);
        std::cout << "GPU quality cases: " << tests << " passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; }
      catch (const winrt::hresult_error& e) { std::cerr << "HRESULT " << int32_t(e.code()) << '\n'; }
    return 1;
}
