@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /O2 /GS- /Zl /LD "F:\project\DLSS5Tool\scripts\native_thread_activity.cpp" /Fe:native_thread_activity.dll /link /NODEFAULTLIB /ENTRY:DllMain kernel32.lib
exit /b %errorlevel%
