// Diagnostic only: intercept existing IAT references in this process after the
// first frame, recording default-heap allocation stacks in bounded native tables.
// No instruction patching, remote injection, registry change or global tracing.
// Cached function pointers / imports loaded later are not covered. Live counts
// therefore describe observed allocation/free pairs, not a complete heap census.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace {
constexpr unsigned ObjectCapacity = 1u << 19, StackCapacity = 8192, Frames = 16;
constexpr unsigned PatchCapacity = 16384, ModuleCapacity = 1024;
struct Object { void* pointer; SIZE_T size; unsigned stack; };
struct Stack {
    void* frames[Frames]; unsigned depth;
    uint64_t allocated, freed, live, allocations, live_count;
};
struct Patch { void** slot; void* before; void* after; };
using Alloc = PVOID (NTAPI*)(PVOID, ULONG, SIZE_T);
using Realloc = PVOID (NTAPI*)(PVOID, ULONG, PVOID, SIZE_T);
using RtlFree = BOOLEAN (NTAPI*)(PVOID, ULONG, PVOID);
using HeapFreeCall = BOOL (WINAPI*)(HANDLE, DWORD, LPVOID);
using VirtualAllocCall = LPVOID (WINAPI*)(LPVOID, SIZE_T, DWORD, DWORD);
using VirtualFreeCall = BOOL (WINAPI*)(LPVOID, SIZE_T, DWORD);
using NtAllocCall = LONG (NTAPI*)(HANDLE, PVOID*, ULONG_PTR, PSIZE_T, ULONG, ULONG);
using NtFreeCall = LONG (NTAPI*)(HANDLE, PVOID*, PSIZE_T, ULONG);
Object* objects = nullptr;
Stack* stacks = nullptr;
Patch patches[PatchCapacity];
unsigned patch_count = 0, stack_count = 0;
uint64_t dropped_objects = 0, dropped_stacks = 0, unknown_frees = 0;
uint64_t observed_allocated = 0, observed_freed = 0;
Alloc real_alloc = nullptr;
Realloc real_realloc = nullptr;
RtlFree real_rtl_free = nullptr;
HeapFreeCall real_heap_free = nullptr;
VirtualAllocCall real_virtual_alloc = nullptr;
VirtualFreeCall real_virtual_free = nullptr;
NtAllocCall real_nt_alloc = nullptr;
NtFreeCall real_nt_free = nullptr;
bool virtual_only = false;
HANDLE default_heap = nullptr;
HMODULE own_module = nullptr;
SRWLOCK table_lock = SRWLOCK_INIT;
volatile LONG enabled = 0;
thread_local bool inside = false;
void* const Tombstone = reinterpret_cast<void*>(static_cast<uintptr_t>(1));

unsigned ObjectHash(void* p) {
    auto value = reinterpret_cast<uintptr_t>(p) >> 4;
    return static_cast<unsigned>((value * 11400714819323198485ull) >> 45);
}
Object* Find(void* pointer, bool insertion) {
    Object* vacant = nullptr;
    auto start = ObjectHash(pointer);
    for (unsigned i = 0; i < ObjectCapacity; ++i) {
        auto& entry = objects[(start+i) & (ObjectCapacity-1)];
        if (entry.pointer == pointer) return &entry;
        if (entry.pointer == Tombstone && !vacant) vacant = &entry;
        if (!entry.pointer) return insertion ? (vacant ? vacant : &entry) : nullptr;
    }
    return insertion ? vacant : nullptr;
}
void RemoveLocked(void* pointer) {
    auto entry = Find(pointer, false);
    if (!entry) { ++unknown_frees; return; }
    auto& stack = stacks[entry->stack];
    stack.live -= entry->size;
    stack.freed += entry->size;
    --stack.live_count;
    observed_freed += entry->size;
    entry->pointer = Tombstone;
}
__declspec(noinline) void Record(void* pointer, SIZE_T size) {
    void* frames[Frames]{};
    const auto depth = CaptureStackBackTrace(2, Frames, frames, nullptr);
    AcquireSRWLockExclusive(&table_lock);
    unsigned index = 0;
    for (; index < stack_count; ++index) {
        if (stacks[index].depth == depth &&
            std::memcmp(stacks[index].frames, frames, depth*sizeof(void*)) == 0) break;
    }
    if (index == stack_count) {
        if (stack_count == StackCapacity) {
            ++dropped_stacks; ReleaseSRWLockExclusive(&table_lock); return;
        }
        stacks[index].depth = depth;
        std::memcpy(stacks[index].frames, frames, depth*sizeof(void*));
        ++stack_count;
    }
    auto entry = Find(pointer, true);
    if (!entry) { ++dropped_objects; ReleaseSRWLockExclusive(&table_lock); return; }
    if (entry->pointer == pointer) RemoveLocked(pointer);
    *entry = {pointer, size, index};
    auto& stack = stacks[index];
    stack.live += size; stack.allocated += size;
    ++stack.allocations; ++stack.live_count;
    observed_allocated += size;
    ReleaseSRWLockExclusive(&table_lock);
}
PVOID NTAPI ObserveAlloc(PVOID heap, ULONG flags, SIZE_T size) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0)) return real_alloc(heap, flags, size);
    inside = true;
    auto pointer = real_alloc(heap, flags, size);
    const auto error = GetLastError();
    if (pointer && heap == default_heap) Record(pointer, size);
    inside = false; SetLastError(error); return pointer;
}
PVOID NTAPI ObserveRealloc(PVOID heap, ULONG flags, PVOID old, SIZE_T size) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0)) return real_realloc(heap, flags, old, size);
    inside = true;
    auto pointer = real_realloc(heap, flags, old, size);
    const auto error = GetLastError();
    if (pointer && heap == default_heap) {
        AcquireSRWLockExclusive(&table_lock); RemoveLocked(old); ReleaseSRWLockExclusive(&table_lock);
        Record(pointer, size);
    }
    inside = false; SetLastError(error); return pointer;
}
BOOLEAN NTAPI ObserveRtlFree(PVOID heap, ULONG flags, PVOID pointer) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0)) return real_rtl_free(heap, flags, pointer);
    inside = true;
    // Remove before returning the block to the heap; another thread can reuse
    // that address immediately. A rare failed free is counted in diagnostics.
    if (pointer && heap == default_heap) {
        AcquireSRWLockExclusive(&table_lock); RemoveLocked(pointer); ReleaseSRWLockExclusive(&table_lock);
    }
    auto ok = real_rtl_free(heap, flags, pointer);
    const auto error = GetLastError();
    inside = false; SetLastError(error); return ok;
}
BOOL WINAPI ObserveHeapFree(HANDLE heap, DWORD flags, LPVOID pointer) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0)) return real_heap_free(heap, flags, pointer);
    inside = true;
    if (pointer && heap == default_heap) {
        AcquireSRWLockExclusive(&table_lock); RemoveLocked(pointer); ReleaseSRWLockExclusive(&table_lock);
    }
    auto ok = real_heap_free(heap, flags, pointer);
    const auto error = GetLastError();
    inside = false; SetLastError(error); return ok;
}
LPVOID WINAPI ObserveVirtualAlloc(LPVOID address, SIZE_T size, DWORD type, DWORD protect) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0))
        return real_virtual_alloc(address, size, type, protect);
    inside = true;
    auto pointer = real_virtual_alloc(address, size, type, protect);
    auto error = GetLastError();
    if (pointer && size >= 65536 && (type & MEM_COMMIT)) Record(pointer, size);
    inside = false; SetLastError(error); return pointer;
}
BOOL WINAPI ObserveVirtualFree(LPVOID pointer, SIZE_T size, DWORD type) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0))
        return real_virtual_free(pointer, size, type);
    inside = true;
    if (pointer && (type & MEM_RELEASE)) {
        AcquireSRWLockExclusive(&table_lock); RemoveLocked(pointer); ReleaseSRWLockExclusive(&table_lock);
    }
    auto ok = real_virtual_free(pointer, size, type);
    auto error = GetLastError();
    inside = false; SetLastError(error); return ok;
}
LONG NTAPI ObserveNtAlloc(HANDLE process, PVOID* base, ULONG_PTR zero, PSIZE_T size,
                         ULONG type, ULONG protect) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0))
        return real_nt_alloc(process, base, zero, size, type, protect);
    inside = true;
    auto status = real_nt_alloc(process, base, zero, size, type, protect);
    auto error = GetLastError();
    if (status >= 0 && base && *base && size && *size >= 65536 && (type & MEM_COMMIT) &&
        (process == GetCurrentProcess() || GetProcessId(process) == GetCurrentProcessId()))
        Record(*base, *size);
    inside = false; SetLastError(error); return status;
}
LONG NTAPI ObserveNtFree(HANDLE process, PVOID* base, PSIZE_T size, ULONG type) {
    if (inside || !InterlockedCompareExchange(&enabled, 0, 0))
        return real_nt_free(process, base, size, type);
    inside = true;
    if (base && *base && (type & MEM_RELEASE) &&
        (process == GetCurrentProcess() || GetProcessId(process) == GetCurrentProcessId())) {
        AcquireSRWLockExclusive(&table_lock); RemoveLocked(*base); ReleaseSRWLockExclusive(&table_lock);
    }
    auto status = real_nt_free(process, base, size, type);
    auto error = GetLastError();
    inside = false; SetLastError(error); return status;
}
void* Replacement(void* pointer) {
    if (virtual_only) {
        if (pointer == reinterpret_cast<void*>(real_virtual_alloc)) return reinterpret_cast<void*>(&ObserveVirtualAlloc);
        if (pointer == reinterpret_cast<void*>(real_virtual_free)) return reinterpret_cast<void*>(&ObserveVirtualFree);
        if (pointer == reinterpret_cast<void*>(real_nt_alloc)) return reinterpret_cast<void*>(&ObserveNtAlloc);
        if (pointer == reinterpret_cast<void*>(real_nt_free)) return reinterpret_cast<void*>(&ObserveNtFree);
        return nullptr;
    }
    if (pointer == reinterpret_cast<void*>(real_alloc)) return reinterpret_cast<void*>(&ObserveAlloc);
    if (pointer == reinterpret_cast<void*>(real_realloc)) return reinterpret_cast<void*>(&ObserveRealloc);
    if (pointer == reinterpret_cast<void*>(real_rtl_free)) return reinterpret_cast<void*>(&ObserveRtlFree);
    if (pointer == reinterpret_cast<void*>(real_heap_free)) return reinterpret_cast<void*>(&ObserveHeapFree);
    return nullptr;
}
void PatchModule(HMODULE module) {
    if (module == own_module) return;
    auto base = reinterpret_cast<unsigned char*>(module);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base+dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) return;
    auto dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress || dir.VirtualAddress+dir.Size > nt->OptionalHeader.SizeOfImage) return;
    auto descriptor = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base+dir.VirtualAddress);
    for (; descriptor->Name && descriptor->FirstThunk; ++descriptor) {
        auto thunk = reinterpret_cast<IMAGE_THUNK_DATA64*>(base+descriptor->FirstThunk);
        for (; thunk->u1.Function; ++thunk) {
            auto slot = reinterpret_cast<void**>(&thunk->u1.Function);
            void* previous = *slot;
            auto after = Replacement(previous);
            if (!after || patch_count == PatchCapacity) continue;
            DWORD protection = 0;
            if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &protection)) continue;
            void* actual = InterlockedCompareExchangePointer(slot, after, previous);
            DWORD ignored;
            VirtualProtect(slot, sizeof(void*), protection, &ignored);
            if (actual == previous) patches[patch_count++] = {slot, previous, after};
        }
    }
}
bool Write(HANDLE file, const char* text) {
    DWORD written;
    auto size = static_cast<DWORD>(std::strlen(text));
    return WriteFile(file, text, size, &written, nullptr) && written == size;
}
void EscapePath(const wchar_t* path, char* output) {
    char utf8[32768];
    WideCharToMultiByte(CP_UTF8, 0, path, -1, utf8, sizeof(utf8), nullptr, nullptr);
    char* destination = output;
    for (const char* source = utf8; *source; ++source) {
        if (*source == '\\' || *source == '"') *destination++ = '\\';
        *destination++ = *source;
    }
    *destination = 0;
}
}

static int Begin(bool virtual_mode) {
    if (objects) return -1;
    virtual_only = virtual_mode;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                      reinterpret_cast<LPCWSTR>(&Begin), &own_module);
    auto ntdll = GetModuleHandleW(L"ntdll.dll");
    real_alloc = reinterpret_cast<Alloc>(GetProcAddress(ntdll, "RtlAllocateHeap"));
    real_realloc = reinterpret_cast<Realloc>(GetProcAddress(ntdll, "RtlReAllocateHeap"));
    real_rtl_free = reinterpret_cast<RtlFree>(GetProcAddress(ntdll, "RtlFreeHeap"));
    real_heap_free = reinterpret_cast<HeapFreeCall>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "HeapFree"));
    auto kernel = GetModuleHandleW(L"kernel32.dll");
    real_virtual_alloc = reinterpret_cast<VirtualAllocCall>(GetProcAddress(kernel, "VirtualAlloc"));
    real_virtual_free = reinterpret_cast<VirtualFreeCall>(GetProcAddress(kernel, "VirtualFree"));
    real_nt_alloc = reinterpret_cast<NtAllocCall>(GetProcAddress(ntdll, "NtAllocateVirtualMemory"));
    real_nt_free = reinterpret_cast<NtFreeCall>(GetProcAddress(ntdll, "NtFreeVirtualMemory"));
    if (!real_alloc || !real_realloc || !real_rtl_free || !real_heap_free) return -2;
    if (virtual_only && (!real_virtual_alloc || !real_virtual_free || !real_nt_alloc || !real_nt_free)) return -2;
    default_heap = GetProcessHeap();
    objects = static_cast<Object*>(VirtualAlloc(nullptr, sizeof(Object)*ObjectCapacity, MEM_RESERVE|MEM_COMMIT, PAGE_READWRITE));
    stacks = static_cast<Stack*>(VirtualAlloc(nullptr, sizeof(Stack)*StackCapacity, MEM_RESERVE|MEM_COMMIT, PAGE_READWRITE));
    if (!objects || !stacks) return -3;
    HMODULE modules[ModuleCapacity]; DWORD needed = 0;
    if (!EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed) || needed > sizeof(modules)) return -4;
    inside = true;
    for (unsigned i = 0; i < needed/sizeof(HMODULE); ++i) PatchModule(modules[i]);
    InterlockedExchange(&enabled, 1);
    inside = false;
    return static_cast<int>(patch_count);
}

extern "C" __declspec(dllexport) int trace_begin() { return Begin(false); }
extern "C" __declspec(dllexport) int trace_begin_virtual() { return Begin(true); }

extern "C" __declspec(dllexport) int trace_dump(const wchar_t* path) {
    if (!objects) return -1;
    inside = true;
    auto file = CreateFileW(path, GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) { inside = false; return -2; }
    HMODULE modules[ModuleCapacity]; DWORD needed = 0;
    bool ok = EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed) && needed <= sizeof(modules);
    char text[70000];
    if (ok) for (unsigned i = 0; i < needed/sizeof(HMODULE); ++i) {
        wchar_t path_buffer[32768]{}; char escaped[65536]{};
        MODULEINFO info{};
        if (!GetModuleFileNameW(modules[i], path_buffer, 32768) ||
            !GetModuleInformation(GetCurrentProcess(), modules[i], &info, sizeof(info))) { ok = false; break; }
        EscapePath(path_buffer, escaped);
        std::snprintf(text, sizeof(text), "{\"kind\":\"module\",\"base\":\"0x%llx\",\"size\":%lu,\"path\":\"%s\"}\n",
            reinterpret_cast<uintptr_t>(info.lpBaseOfDll), info.SizeOfImage, escaped);
        if (!Write(file, text)) { ok = false; break; }
    }
    AcquireSRWLockExclusive(&table_lock);
    std::snprintf(text, sizeof(text),
        "{\"kind\":\"summary\",\"pid\":%lu,\"patches\":%u,\"stacks\":%u,\"object_capacity\":%u,"
        "\"dropped_objects\":%llu,\"dropped_stacks\":%llu,\"unknown_frees\":%llu,"
        "\"observed_allocated\":%llu,\"observed_freed\":%llu,\"scope\":\"%s; existing IAT references only\"}\n",
        GetCurrentProcessId(), patch_count, stack_count, ObjectCapacity,
        dropped_objects, dropped_stacks, unknown_frees, observed_allocated, observed_freed,
        virtual_only ? "VirtualAlloc/NtAllocateVirtualMemory commits >=64KiB, MEM_RELEASE pairs; partial decommit untracked" : "default heap");
    ok = Write(file, text) && ok;
    for (unsigned i = 0; i < stack_count; ++i) {
        const auto& stack = stacks[i];
        auto length = std::snprintf(text, sizeof(text),
            "{\"kind\":\"stack\",\"index\":%u,\"allocated\":%llu,\"freed\":%llu,\"live\":%llu,"
            "\"allocations\":%llu,\"live_count\":%llu,\"frames\":[", i,
            stack.allocated, stack.freed, stack.live, stack.allocations, stack.live_count);
        for (unsigned f = 0; f < stack.depth; ++f)
            length += std::snprintf(text+length, sizeof(text)-length, "%s\"0x%llx\"", f ? "," : "", reinterpret_cast<uintptr_t>(stack.frames[f]));
        std::snprintf(text+length, sizeof(text)-length, "]}\n");
        if (!Write(file, text)) { ok = false; break; }
    }
    ReleaseSRWLockExclusive(&table_lock);
    CloseHandle(file); inside = false;
    return ok ? 0 : -3;
}

extern "C" __declspec(dllexport) int trace_end() {
    InterlockedExchange(&enabled, 0);
    inside = true;
    unsigned restored = 0;
    for (unsigned i = patch_count; i > 0; --i) {
        auto& patch = patches[i-1]; DWORD protection = 0;
        if (!VirtualProtect(patch.slot, sizeof(void*), PAGE_READWRITE, &protection)) continue;
        if (InterlockedCompareExchangePointer(patch.slot, patch.before, patch.after) == patch.after) ++restored;
        DWORD ignored; VirtualProtect(patch.slot, sizeof(void*), protection, &ignored);
    }
    // Keep the pinned DLL and bounded tables until process exit: a thread may
    // already be in one of the wrappers while IAT references are restored.
    inside = false;
    return static_cast<int>(restored);
}
