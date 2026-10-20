@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /O2 /GS- /Zl /LD /Fe:native_thread_activity.dll /Fo:native_thread_activity.obj "F:\project\DLSS5Tool\scripts\native_thread_activity.cpp" /link /NODEFAULTLIB /ENTRY:DllMain kernel32.lib /IMPLIB:native_thread_activity.lib
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /O2 /Ob0 /MT /EHsc /LD /Fe:native_heap_trace.dll /Fo:native_heap_trace.obj "F:\project\DLSS5Tool\scripts\native_heap_trace.cpp" /link psapi.lib /IMPLIB:native_heap_trace.lib
exit /b %errorlevel%
