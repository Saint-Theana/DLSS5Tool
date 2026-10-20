@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++20 /O2 /MT /EHsc /utf-8 /UNDEBUG /DNOMINMAX /DWIN32_LEAN_AND_MEAN /I"F:\project\DLSS5Tool\native\realtime" /Iflush-candidate\generated "F:\project\DLSS5Tool\native\realtime\quality_tests.cpp" "F:\project\DLSS5Tool\native\realtime\quality.cpp" /Fe:realtime_quality_tests.exe /link d3d11.lib windowsapp.lib
if errorlevel 1 exit /b %errorlevel%
realtime_quality_tests.exe
exit /b %errorlevel%
