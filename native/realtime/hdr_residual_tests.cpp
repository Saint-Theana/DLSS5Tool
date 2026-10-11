// SPDX-License-Identifier: GPL-3.0-only
#include <d3d11.h>
#include <d3dcompiler.h>
#include <winrt/base.h>
#include <array>
#include <cmath>
#include <iostream>
#include <string>
#include <vector>
using Pixel = std::array<float, 4>;

int main(int argc, char** argv) {
    try {
        winrt::com_ptr<ID3D11Device> device;
        winrt::com_ptr<ID3D11DeviceContext> context;
        const auto driver = argc > 1 && std::string(argv[1]) == "hardware" ? D3D_DRIVER_TYPE_HARDWARE : D3D_DRIVER_TYPE_WARP;
        winrt::check_hresult(D3D11CreateDevice(nullptr, driver, nullptr, 0, nullptr, 0,
            D3D11_SDK_VERSION, device.put(), nullptr, context.put()));
        winrt::com_ptr<ID3DBlob> blob, errors;
        const HRESULT compiled = D3DCompileFromFile(HDR_TEST_SHADER, nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE,
            "main", "cs_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, blob.put(), errors.put());
        if (FAILED(compiled) && errors) std::cerr << static_cast<const char*>(errors->GetBufferPointer());
        winrt::check_hresult(compiled);
        winrt::com_ptr<ID3D11ComputeShader> shader;
        winrt::check_hresult(device->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, shader.put()));
        constexpr unsigned width=7, height=5;
        std::vector<Pixel> base(width*height), nr(width*height);
        for (unsigned i=0;i<base.size();++i) {
            base[i] = {i%3 == 0 ? -.2f : 2.f, .4f, 3.f, .7f};
            nr[i] = base[i];
            if (i%4) for (unsigned c=0;c<3;++c) nr[i][c] += (i%2 ? 1.f : -1.f) * .1f * (c+1);
            nr[i][3] = .2f;
        }
        auto texture = [&](const std::vector<Pixel>* pixels, bool staging=false) {
            D3D11_TEXTURE2D_DESC d{};
            d.Width=width; d.Height=height; d.MipLevels=d.ArraySize=d.SampleDesc.Count=1;
            d.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
            d.Usage=staging ? D3D11_USAGE_STAGING : D3D11_USAGE_DEFAULT;
            d.BindFlags=staging ? 0 : D3D11_BIND_SHADER_RESOURCE|D3D11_BIND_UNORDERED_ACCESS;
            d.CPUAccessFlags=staging ? D3D11_CPU_ACCESS_READ : 0;
            D3D11_SUBRESOURCE_DATA data{pixels ? pixels->data() : nullptr, width*sizeof(Pixel), 0};
            winrt::com_ptr<ID3D11Texture2D> t;
            winrt::check_hresult(device->CreateTexture2D(&d, pixels ? &data : nullptr, t.put()));
            return t;
        };
        auto b=texture(&base), n=texture(&nr), out=texture(nullptr), staging=texture(nullptr,true);
        winrt::com_ptr<ID3D11ShaderResourceView> bs, ns;
        winrt::com_ptr<ID3D11UnorderedAccessView> uav;
        winrt::check_hresult(device->CreateShaderResourceView(b.get(),nullptr,bs.put()));
        winrt::check_hresult(device->CreateShaderResourceView(n.get(),nullptr,ns.put()));
        winrt::check_hresult(device->CreateUnorderedAccessView(out.get(),nullptr,uav.put()));
        D3D11_BUFFER_DESC cb{}; cb.ByteWidth=32; cb.Usage=D3D11_USAGE_DEFAULT; cb.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        winrt::com_ptr<ID3D11Buffer> constants;
        winrt::check_hresult(device->CreateBuffer(&cb,nullptr,constants.put()));
        std::array<std::array<float,8>,7> cases{{
            {1,1,1,1,1}, {2,1,1,1,1}, {1,0,1,1,1}, {1,1,0,1,1},
            {1,1,1,0,1}, {1,1,1,1,0}, {1.7f,.6f,1.4f,.8f,1.3f}}};
        unsigned count=0;
        for (const auto& settings:cases) {
            context->UpdateSubresource(constants.get(),0,nullptr,settings.data(),0,0);
            auto* buffer=constants.get(); auto* target=uav.get(); ID3D11ShaderResourceView* views[]{bs.get(),ns.get()};
            context->CSSetShader(shader.get(),nullptr,0);
            context->CSSetShaderResources(0,2,views); context->CSSetUnorderedAccessViews(0,1,&target,nullptr);
            context->CSSetConstantBuffers(0,1,&buffer); context->Dispatch(1,1,1);
            ID3D11ShaderResourceView* none[2]{}; ID3D11UnorderedAccessView* noTarget=nullptr;
            context->CSSetShaderResources(0,2,none); context->CSSetUnorderedAccessViews(0,1,&noTarget,nullptr);
            context->CopyResource(staging.get(),out.get());
            D3D11_MAPPED_SUBRESOURCE map{}; winrt::check_hresult(context->Map(staging.get(),0,D3D11_MAP_READ,0,&map));
            bool valid=true;
            for (unsigned y=0;y<height;++y) for (unsigned x=0;x<width;++x) {
                unsigned i=y*width+x;
                const auto& pixel=reinterpret_cast<Pixel*>(static_cast<char*>(map.pData)+y*map.RowPitch)[x];
                std::array<double,3> d{}; constexpr double weights[]{.2126,.7152,.0722}; double dy=0;
                for (unsigned c=0;c<3;++c) {d[c]=(nr[i][c]-base[i][c])*settings[0];dy+=d[c]*weights[c];}
                const double direction=dy<0 ? settings[1] : dy>0 ? settings[2] : 1;
                dy=0; for (unsigned c=0;c<3;++c) {d[c]*=direction;dy+=d[c]*weights[c];}
                for (unsigned c=0;c<3;++c) {
                    double expected=base[i][c]+dy*settings[4]+(d[c]-dy)*settings[3];
                    valid &= std::isfinite(pixel[c]) && std::abs(pixel[c]-expected)<2e-5;
                }
                valid &= pixel[3]==base[i][3];
            }
            context->Unmap(staging.get(),0);
            if (!valid) throw std::runtime_error("HDR residual pixel mismatch");
            ++count;
        }
        std::cout << "HDR residual: " << count << " cases, signed/highlight/zero/odd extent/alpha passed\n";
        return 0;
    } catch (const winrt::hresult_error& error) {std::cerr << "HRESULT " << int32_t(error.code()) << '\n';}
      catch (const std::exception& error) {std::cerr << error.what() << '\n';}
    return 1;
}
