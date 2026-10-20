@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /O2 /MT /EHsc /Fe:native_graphics_memory_probe.exe /Fo:native_graphics_memory_probe.obj "F:\project\DLSS5Tool\scripts\native_graphics_memory_probe.cpp" /link d3d11.lib d3dcompiler.lib dxgi.lib psapi.lib
exit /b %errorlevel%
