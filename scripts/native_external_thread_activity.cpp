// Bounded ETW counter for one exact process identity; no injection or ETL file.
// Only matching thread starts/stops and start addresses are retained.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>
#include <tdh.h>
#include <cstdio>
#include <cstdint>
#include <map>
#include <thread>
#include <string>

namespace {
const GUID provider{0x22fb2cd6,0x0e7b,0x422b,{0xa0,0xc7,0x2f,0xad,0x1f,0xd0,0xe7,0x16}};
DWORD target = 0;
DWORD collector_thread = 0;
uint64_t starts = 0, stops = 0, schema_errors = 0, address_errors = 0;
std::map<uint64_t,uint64_t> addresses;
bool property(EVENT_RECORD* record, const wchar_t* name, void* value, ULONG bytes) {
    PROPERTY_DATA_DESCRIPTOR desc{};
    desc.PropertyName = reinterpret_cast<ULONGLONG>(name);
    desc.ArrayIndex = ULONG_MAX;
    return TdhGetProperty(record,0,nullptr,1,&desc,bytes,static_cast<BYTE*>(value)) == ERROR_SUCCESS;
}
void WINAPI event(EVENT_RECORD* record) {
    const auto id = record->EventHeader.EventDescriptor.Id;
    if (id != 3 && id != 4) return;
    DWORD pid = 0;
    if (!property(record,L"ProcessID",&pid,sizeof(pid))) { ++schema_errors; return; }
    if (pid != target) return;
    DWORD tid=0;
    if (!property(record,L"ThreadID",&tid,sizeof(tid))) { ++schema_errors; return; }
    if (tid == collector_thread) return; // Self-test reader is not a test worker.
    if (id == 4) { ++stops; return; }
    ++starts;
    uint64_t address = 0;
    if (!property(record,L"Win32StartAddr",&address,sizeof(address)) || !address) {
        ++address_errors; return;
    }
    ++addresses[address];
}
uint64_t creation(HANDLE handle) {
    FILETIME a{},b{},c{},d{};
    if (!GetProcessTimes(handle,&a,&b,&c,&d)) return 0;
    return uint64_t(a.dwHighDateTime) << 32 | a.dwLowDateTime;
}
struct Properties { EVENT_TRACE_PROPERTIES p; wchar_t name[128]; };
}

int wmain(int argc, wchar_t** argv) {
    if (argc >= 4 && std::wstring(argv[argc-2]) == L"--output") {
        FILE* output=nullptr;
        if (_wfreopen_s(&output,argv[argc-1],L"w",stdout)) return 2;
        argc-=2;
    }
    const bool self = argc == 2 && std::wstring(argv[1]) == L"--self-test";
    if (!self && argc != 4) {
        std::fprintf(stderr,"usage: counter PID CREATION_FILETIME SECONDS | --self-test\n");
        return 2;
    }
    target = self ? GetCurrentProcessId() : wcstoul(argv[1],nullptr,10);
    const uint64_t expected = self ? 0 : _wcstoui64(argv[2],nullptr,10);
    const unsigned seconds = self ? 3 : wcstoul(argv[3],nullptr,10);
    if (!target || !seconds || seconds > 180) return 2;
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,FALSE,target);
    if (!process) return 3;
    const auto created = creation(process);
    if (!created || (!self && created != expected)) { CloseHandle(process); return 3; }
    Properties props{};
    swprintf_s(props.name,L"DLSS5Tool-P0-Threads-%lu",GetCurrentProcessId());
    props.p.Wnode.BufferSize = sizeof(props);
    props.p.Wnode.Flags = WNODE_FLAG_TRACED_GUID;
    props.p.Wnode.ClientContext = 1;
    props.p.BufferSize = 64;
    props.p.MinimumBuffers = 8;
    props.p.MaximumBuffers = 64;
    props.p.FlushTimer = 1;
    props.p.LogFileMode = EVENT_TRACE_REAL_TIME_MODE;
    props.p.LoggerNameOffset = offsetof(Properties,name);
    TRACEHANDLE session = 0;
    ULONG status = StartTraceW(&session,props.name,&props.p);
    if (status) {
        std::printf("{\"stage\":\"StartTrace\",\"error\":%lu}\n",status);
        CloseHandle(process); return 4;
    }
    status = EnableTraceEx2(session,&provider,EVENT_CONTROL_CODE_ENABLE_PROVIDER,4,0x20,0,1000,nullptr);
    EVENT_TRACE_LOGFILEW log{};
    log.LoggerName = props.name;
    log.ProcessTraceMode = PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD;
    log.EventRecordCallback = event;
    TRACEHANDLE consumer = status ? INVALID_PROCESSTRACE_HANDLE : OpenTraceW(&log);
    ULONG consumed = ERROR_SUCCESS;
    const auto began = GetTickCount64();
    if (!status && consumer != INVALID_PROCESSTRACE_HANDLE) {
        std::thread reader([&]{collector_thread=GetCurrentThreadId(); consumed=ProcessTrace(&consumer,1,nullptr,nullptr);});
        if (self) {
            Sleep(500);
            for (unsigned i=0;i<50;++i) { std::thread([]{}).join(); }
            Sleep(seconds*1000);
        } else {
            WaitForSingleObject(process,seconds*1000);
        }
        EnableTraceEx2(session,&provider,EVENT_CONTROL_CODE_DISABLE_PROVIDER,0,0,0,1000,nullptr);
        ControlTraceW(session,nullptr,&props.p,EVENT_TRACE_CONTROL_STOP);
        reader.join();
        CloseTrace(consumer);
    } else {
        if (!status) status = GetLastError();
        ControlTraceW(session,nullptr,&props.p,EVENT_TRACE_CONTROL_STOP);
    }
    std::printf("{\"pid\":%lu,\"created\":%llu,\"self_test\":%s,\"elapsed_ms\":%llu,"
        "\"enable_error\":%lu,\"consume_error\":%lu,\"events_lost\":%lu,\"buffers_lost\":%lu,"
        "\"started\":%llu,\"stopped\":%llu,\"schema_errors\":%llu,\"address_errors\":%llu,\"addresses\":[",
        target,created,self?"true":"false",GetTickCount64()-began,status,consumed,
        props.p.EventsLost,props.p.RealTimeBuffersLost,starts,stops,schema_errors,address_errors);
    bool comma=false;
    for (const auto& [address,count] : addresses) {
        std::printf("%s{\"start_address\":%llu,\"count\":%llu}",comma?",":"",address,count);
        comma=true;
    }
    std::printf("]}\n");
    CloseHandle(process);
    return status || consumed || props.p.EventsLost || props.p.RealTimeBuffersLost || schema_errors ||
        (self && (starts != 50 || stops != 50)) ? 1 : 0;
}
