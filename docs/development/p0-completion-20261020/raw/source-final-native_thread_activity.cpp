// Diagnostic DLL: count this process's thread notifications without allocating.
// No hooks, remote injection, driver changes, CRT, or registry configuration.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>

namespace {
using QueryThread = LONG (NTAPI*)(HANDLE, ULONG, void*, ULONG, ULONG*);
QueryThread query_thread = nullptr;
volatile LONG64 started = 0, detached = 0, dropped = 0;
struct Entry { void* volatile address; volatile LONG64 count; };
Entry entries[64]{};
}

extern "C" __declspec(dllexport) void thread_activity_read(uint64_t* values) {
    if (!values) return;
    values[0] = InterlockedCompareExchange64(&started, 0, 0);
    values[1] = InterlockedCompareExchange64(&detached, 0, 0);
    values[2] = InterlockedCompareExchange64(&dropped, 0, 0);
    for (unsigned i=0; i<64; ++i) {
        values[3+i*2] = reinterpret_cast<uintptr_t>(InterlockedCompareExchangePointer(&entries[i].address, nullptr, nullptr));
        values[4+i*2] = InterlockedCompareExchange64(&entries[i].count, 0, 0);
    }
}

extern "C" BOOL WINAPI DllMain(HINSTANCE, DWORD reason, void*) {
    if (reason == DLL_PROCESS_ATTACH) {
        query_thread = reinterpret_cast<QueryThread>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryInformationThread"));
    } else if (reason == DLL_THREAD_ATTACH) {
        InterlockedIncrement64(&started);
        void* address = nullptr;
        if (!query_thread || query_thread(GetCurrentThread(), 9, &address, sizeof(address), nullptr) < 0 || !address) {
            InterlockedIncrement64(&dropped);
            return TRUE;
        }
        for (auto& entry : entries) {
            void* previous = InterlockedCompareExchangePointer(&entry.address, address, nullptr);
            if (!previous || previous == address) {
                InterlockedIncrement64(&entry.count);
                return TRUE;
            }
        }
        InterlockedIncrement64(&dropped);
    } else if (reason == DLL_THREAD_DETACH) {
        InterlockedIncrement64(&detached);
    }
    return TRUE;
}
