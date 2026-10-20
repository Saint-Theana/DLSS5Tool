// Bounded standalone driver control: no Python, NGX or project runtime DLLs.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi.h>
#include <psapi.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <chrono>
#include <thread>

struct Device {
    ID3D11Device* device=nullptr;
    ID3D11DeviceContext* context=nullptr;
    ID3D11ComputeShader* shader=nullptr;
    bool create() {
        const D3D_FEATURE_LEVEL levels[]={D3D_FEATURE_LEVEL_11_1,D3D_FEATURE_LEVEL_11_0};
        if (FAILED(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,levels,2,D3D11_SDK_VERSION,&device,nullptr,&context))) return false;
        IDXGIDevice* dxgi=nullptr; IDXGIAdapter* adapter=nullptr; DXGI_ADAPTER_DESC desc{};
        if (SUCCEEDED(device->QueryInterface(__uuidof(IDXGIDevice),reinterpret_cast<void**>(&dxgi)))) {
            if (SUCCEEDED(dxgi->GetAdapter(&adapter))) {
                if (SUCCEEDED(adapter->GetDesc(&desc)))
                    std::printf("{\"event\":\"adapter\",\"vendor\":%u,\"luid_high\":%ld,\"luid_low\":%lu}\n",desc.VendorId,desc.AdapterLuid.HighPart,desc.AdapterLuid.LowPart);
                adapter->Release();
            }
            dxgi->Release();
        }
        const char source[]="[numthreads(1,1,1)] void main(uint3 id:SV_DispatchThreadID) {}";
        ID3DBlob* code=nullptr; ID3DBlob* error=nullptr;
        const auto compiled=D3DCompile(source,sizeof(source)-1,nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&code,&error);
        if (error) error->Release();
        if (FAILED(compiled)) return false;
        const auto made=device->CreateComputeShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&shader);
        code->Release();
        if (FAILED(made)) return false;
        context->CSSetShader(shader,nullptr,0); context->Dispatch(1,1,1); context->Flush();
        return true;
    }
    ~Device() {
        if (context) context->ClearState();
        if (shader) shader->Release();
        if (context) { context->Flush(); context->Release(); }
        if (device) std::printf("{\"event\":\"device-release\",\"retained_refs\":%lu}\n",device->Release());
    }
};

void modules() {
    HMODULE entries[512]; DWORD needed=0;
    if (!EnumProcessModules(GetCurrentProcess(),entries,sizeof(entries),&needed) || needed>sizeof(entries)) {
        std::printf("{\"event\":\"module-query-error\"}\n"); return;
    }
    for (unsigned i=0;i<needed/sizeof(HMODULE);++i) {
        wchar_t path[32768]{};
        if (!GetModuleFileNameW(entries[i],path,32768)) continue;
        const wchar_t* name=wcsrchr(path,L'\\'); name=name ? name+1 : path;
        char utf8[2048]{}; WideCharToMultiByte(CP_UTF8,0,name,-1,utf8,sizeof(utf8),nullptr,nullptr);
        std::printf("{\"event\":\"module\",\"name\":\"%s\"}\n",utf8);
    }
}

int main(int argc,char** argv) {
    if (argc!=5) return 2;
    const int cuda=std::atoi(argv[1]),count=std::atoi(argv[2]),churn=std::atoi(argv[3]),seconds=std::atoi(argv[4]);
    if ((cuda!=0&&cuda!=1)||count<1||count>4||churn<1||churn>16||seconds<10||seconds>90) return 2;
    std::printf("{\"event\":\"starting\",\"pid\":%lu,\"cuda\":%d,\"devices\":%d,\"churn\":%d,\"seconds\":%d}\n",GetCurrentProcessId(),cuda,count,churn,seconds);
    if (cuda) {
        auto library=LoadLibraryW(L"nvcuda.dll");
        using Init=int (WINAPI*)(unsigned);
        auto init=library ? reinterpret_cast<Init>(GetProcAddress(library,"cuInit")) : nullptr;
        if (!init || init(0)!=0) return 3;
    }
    for (int round=0;round<churn;++round) {
        std::vector<Device*> devices;
        for (int i=0;i<count;++i) {
            auto device=new Device();
            if (!device->create()) {delete device; for(auto p:devices)delete p; return 4;}
            devices.push_back(device);
        }
        // Keep the last group alive while observing; earlier groups are churn.
        if (round==churn-1) {
            modules();
            const auto start=std::chrono::steady_clock::now();
            for (int i=0;i<=seconds;++i) {
                PROCESS_MEMORY_COUNTERS_EX memory{}; memory.cb=sizeof(memory);
                HEAP_SUMMARY heap{}; heap.cb=sizeof(heap);
                MEMORYSTATUSEX system{}; system.dwLength=sizeof(system);
                if (!GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory),sizeof(memory)) ||
                    !HeapSummary(GetProcessHeap(),0,&heap) || !GlobalMemoryStatusEx(&system)) return 5;
                std::printf("{\"event\":\"sample\",\"seconds\":%.3f,\"private_bytes\":%llu,\"heap_allocated\":%llu,\"heap_committed\":%llu}\n",
                    std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count(),
                    static_cast<unsigned long long>(memory.PrivateUsage),static_cast<unsigned long long>(heap.cbAllocated),static_cast<unsigned long long>(heap.cbCommitted));
                std::fflush(stdout);
                if (memory.PrivateUsage>2ull*1024*1024*1024 || system.ullAvailPhys<8ull*1024*1024*1024 || system.ullAvailPageFile<8ull*1024*1024*1024) return 6;
                if (i<seconds) std::this_thread::sleep_for(std::chrono::seconds(1));
            }
        }
        for(auto device:devices) delete device;
    }
    std::printf("{\"event\":\"closed\"}\n");
    return 0;
}
