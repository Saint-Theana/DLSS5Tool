// Owned, bounded SDR/scRGB source. No capture, injection or system-setting writes.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellscalingapi.h>
#include <d3d11.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <nlohmann/json.hpp>
#include <chrono>
#include <iostream>
#include <stdexcept>

using Microsoft::WRL::ComPtr;
using nlohmann::json;
static void check(HRESULT hr) { if (FAILED(hr)) throw std::runtime_error("HRESULT " + std::to_string(uint32_t(hr))); }
static LRESULT CALLBACK windowProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_CLOSE) { DestroyWindow(h); return 0; }
    if (m == WM_DESTROY) { PostQuitMessage(0); return 0; }
    if (m == WM_DPICHANGED) {
        auto r = reinterpret_cast<RECT*>(l);
        SetWindowPos(h, nullptr, r->left, r->top, r->right-r->left, r->bottom-r->top, SWP_NOZORDER | SWP_NOACTIVATE);
        return 0;
    }
    return DefWindowProc(h, m, w, l);
}

int main(int argc, char** argv) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    try {
        ComPtr<IDXGIFactory1> factory;
        check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
        if (argc == 2 && std::string(argv[1]) == "--inventory") {
            json adapters = json::array(), monitors = json::array();
            for (UINT i=0;; ++i) {
                ComPtr<IDXGIAdapter1> a;
                auto hr = factory->EnumAdapters1(i, &a);
                if (hr == DXGI_ERROR_NOT_FOUND) break;
                check(hr);
                DXGI_ADAPTER_DESC1 d{}; check(a->GetDesc1(&d));
                adapters.push_back({{"index", i}, {"luid", {d.AdapterLuid.HighPart, d.AdapterLuid.LowPart}},
                    {"software", bool(d.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)}, {"vendor", d.VendorId}, {"device", d.DeviceId}});
            }
            EnumDisplayMonitors(nullptr, nullptr, [](HMONITOR h, HDC, LPRECT r, LPARAM p) -> BOOL {
                UINT x=0, y=0;
                auto hr = GetDpiForMonitor(h, MDT_EFFECTIVE_DPI, &x, &y);
                reinterpret_cast<json*>(p)->push_back({{"rect", {r->left,r->top,r->right,r->bottom}},
                    {"dpi", SUCCEEDED(hr) ? json({x,y}) : json(nullptr)}});
                return TRUE;
            }, reinterpret_cast<LPARAM>(&monitors));
            std::cout << json({{"adapters",adapters},{"monitors",monitors}}).dump() << std::endl;
            return 0;
        }
        if (argc != 5) throw std::runtime_error("Usage: source seconds x y hdr(0/1), or --inventory");
        const int seconds=std::stoi(argv[1]), x=std::stoi(argv[2]), y=std::stoi(argv[3]);
        const bool hdr=std::stoi(argv[4]) != 0;
        if (seconds < 5 || seconds > 1830) throw std::runtime_error("Duration outside 5..1830");
        WNDCLASS wc{}; wc.lpfnWndProc=windowProc; wc.hInstance=GetModuleHandle(nullptr);
        wc.lpszClassName=L"DLSS5ToolOwnedP2Source"; wc.hCursor=LoadCursor(nullptr, IDC_ARROW);
        if (!RegisterClass(&wc)) throw std::runtime_error("RegisterClass");
        HWND hwnd=CreateWindow(wc.lpszClassName, hdr ? L"DLSS5Tool owned scRGB HDR source" : L"DLSS5Tool owned SDR source",
            WS_OVERLAPPEDWINDOW, x,y,800,450,nullptr,nullptr,wc.hInstance,nullptr);
        if (!hwnd) throw std::runtime_error("CreateWindow");
        ShowWindow(hwnd, SW_SHOWNORMAL);
        ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context;
        check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            nullptr,0,D3D11_SDK_VERSION,&device,nullptr,&context));
        ComPtr<IDXGIDevice> dxgiDevice; check(device.As(&dxgiDevice));
        ComPtr<IDXGIAdapter> adapter; check(dxgiDevice->GetAdapter(&adapter));
        ComPtr<IDXGIFactory2> f2; check(adapter->GetParent(IID_PPV_ARGS(&f2)));
        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Format=hdr ? DXGI_FORMAT_R16G16B16A16_FLOAT : DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count=1; desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount=2; desc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
        ComPtr<IDXGISwapChain1> swap; check(f2->CreateSwapChainForHwnd(device.Get(),hwnd,&desc,nullptr,nullptr,&swap));
        ComPtr<IDXGISwapChain3> swap3; check(swap.As(&swap3));
        const auto space=hdr ? DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709 : DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709;
        UINT support=0; check(swap3->CheckColorSpaceSupport(space,&support));
        if (!(support & DXGI_SWAP_CHAIN_COLOR_SPACE_SUPPORT_FLAG_PRESENT)) throw std::runtime_error("Source colorspace unavailable");
        check(swap3->SetColorSpace1(space));
        const char shader[]=R"(
cbuffer C : register(b0) { float time; float width; float height; float peak; }
float4 vs(uint id:SV_VertexID):SV_Position { return float4(id==2?3:-1,id==1?3:-1,0,1); }
float4 ps(float4 p:SV_Position):SV_Target {
    float2 uv=p.xy/float2(width,height);
    float v=floor(uv.x*16)/15*peak;
    float3 c=v.xxx;
    if (uv.y>.5) c=float3(uv.x*peak,0.1,0.3);
    if (uv.y>.75) c=float3(-.05,.3,uv.x*peak);
    if (abs(uv.x-frac(time*.18))<.025 && uv.y>.25 && uv.y<.75) c=peak.xxx;
    if (fmod(p.x,32)<1 || fmod(p.y,32)<1) c*=.5;
    return float4(c,1);
})";
        ComPtr<ID3DBlob> vsCode, psCode, error;
        check(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"vs","vs_5_0",0,0,&vsCode,&error));
        check(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"ps","ps_5_0",0,0,&psCode,&error));
        ComPtr<ID3D11VertexShader> vs; ComPtr<ID3D11PixelShader> ps;
        check(device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs));
        check(device->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&ps));
        D3D11_BUFFER_DESC cb{}; cb.ByteWidth=16; cb.Usage=D3D11_USAGE_DEFAULT; cb.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        ComPtr<ID3D11Buffer> constants; check(device->CreateBuffer(&cb,nullptr,&constants));
        std::cout << json({{"hwnd",reinterpret_cast<uintptr_t>(hwnd)},{"pid",GetCurrentProcessId()},
            {"hdr",hdr},{"format",int(desc.Format)},{"color_space",int(space)}, {"dpi",GetDpiForWindow(hwnd)},
            {"linear_range",hdr ? json({-.05,4.0}) : json({0.0,1.0})}}).dump() << std::endl;
        const auto begin=std::chrono::steady_clock::now();
        unsigned frames=0;
        while (IsWindow(hwnd)) {
            MSG msg; while (PeekMessage(&msg,nullptr,0,0,PM_REMOVE)) { TranslateMessage(&msg); DispatchMessage(&msg); }
            if (!IsWindow(hwnd)) break;
            float t=std::chrono::duration<float>(std::chrono::steady_clock::now()-begin).count();
            if (t>=seconds) break;
            ComPtr<ID3D11Texture2D> buffer; check(swap->GetBuffer(0,IID_PPV_ARGS(&buffer)));
            D3D11_TEXTURE2D_DESC td{}; buffer->GetDesc(&td);
            ComPtr<ID3D11RenderTargetView> target; check(device->CreateRenderTargetView(buffer.Get(),nullptr,&target));
            D3D11_VIEWPORT viewport{0,0,float(td.Width),float(td.Height),0,1};
            context->RSSetViewports(1,&viewport); context->OMSetRenderTargets(1,target.GetAddressOf(),nullptr);
            float values[]={t,float(td.Width),float(td.Height),hdr?4.0f:1.0f};
            context->UpdateSubresource(constants.Get(),0,nullptr,values,0,0);
            context->PSSetConstantBuffers(0,1,constants.GetAddressOf());
            context->VSSetShader(vs.Get(),nullptr,0); context->PSSetShader(ps.Get(),nullptr,0);
            context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            context->Draw(3,0); check(swap->Present(1,0)); ++frames;
        }
        if (IsWindow(hwnd)) DestroyWindow(hwnd);
        std::cout << json({{"frames",frames},{"exit_ok",true}}).dump() << std::endl;
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << std::endl;
        return 1;
    }
}
