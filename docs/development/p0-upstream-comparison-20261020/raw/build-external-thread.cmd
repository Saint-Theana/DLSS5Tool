@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++20 /O2 /MT /EHsc /utf-8 "F:\project\DLSS5Tool\scripts\native_external_thread_activity.cpp" /Fe:native_external_thread_activity.exe /link advapi32.lib tdh.lib
exit /b %errorlevel%
