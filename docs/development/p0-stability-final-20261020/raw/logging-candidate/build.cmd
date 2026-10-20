@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cd /d "%~dp0"
cl /nologo /std:c++17 /O2 /EHsc /MT /LD /I"F:\project\DLSS5Tool\tmp\RTX_Video_SDK_v1.1.0\include" /Fo"F:\project\DLSS5Tool\tmp\p0-stability-20261019\logging-candidate\vsr_host.obj" "F:\project\DLSS5Tool\tmp\p0-stability-20261019\logging-candidate\vsr_host.cpp" "F:\project\DLSS5Tool\tmp\RTX_Video_SDK_v1.1.0\lib\Windows\x64\nvsdk_ngx_s.lib" D3D12.lib DXGI.lib Advapi32.lib User32.lib /link /OUT:"F:\project\DLSS5Tool\tmp\p0-stability-20261019\logging-candidate\vsr_host.dll" /PDB:"F:\project\DLSS5Tool\tmp\p0-stability-20261019\logging-candidate\vsr_host.pdb" /IMPLIB:"F:\project\DLSS5Tool\tmp\p0-stability-20261019\logging-candidate\vsr_host.lib"
exit /b %errorlevel%
