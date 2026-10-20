@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
if not exist generated\shaders mkdir generated\shaders
"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\fxc.exe" /nologo /O3 /T cs_5_0 /E main /Vn VeyraResidualCS /I"F:\project\DLSS5Tool\third_party\realtime\veyra\shaders" /Fh generated\shaders\VeyraResidualCS.h generated\VeyraResidual.hlsl
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++20 /O2 /MT /EHsc /utf-8 /DNOMINMAX /DWIN32_LEAN_AND_MEAN /LD /I"F:\project\DLSS5Tool\native\realtime" /Igenerated quality_bridge.cpp quality.cpp "F:\project\DLSS5Tool\native\realtime\quality_gpu_output.cpp" /Fe:dlss5_quality.dll /link d3d11.lib d3d12.lib dxgi.lib windowsapp.lib
exit /b %errorlevel%
