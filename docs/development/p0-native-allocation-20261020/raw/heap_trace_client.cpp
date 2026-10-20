#include <windows.h>
extern "C" __declspec(dllexport) void* test_allocate(SIZE_T size) { return HeapAlloc(GetProcessHeap(), 0, size); }
extern "C" __declspec(dllexport) void* test_reallocate(void* p, SIZE_T size) { return HeapReAlloc(GetProcessHeap(), 0, p, size); }
extern "C" __declspec(dllexport) int test_free(void* p) { return HeapFree(GetProcessHeap(), 0, p); }
