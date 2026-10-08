[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WorkDirectory)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$workRoot = [IO.Path]::GetFullPath($WorkDirectory)
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw 'Visual Studio C++ Build Tools are required.' }
$compiler = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC/Tools/MSVC') -Directory |
    Sort-Object Name -Descending | Select-Object -First 1
$sdk = 'C:/Program Files (x86)/Windows Kits/10'
$sdkVersion = '10.0.26100.0'
$rc = Join-Path $sdk "bin/$sdkVersion/x64/rc.exe"
$cl = Join-Path $compiler.FullName 'bin/Hostx64/x64/cl.exe'
$resourceFile = Join-Path $workRoot 'app_icon.rc'
$resourceObject = Join-Path $workRoot 'app_icon.res'
$testExe = Join-Path $workRoot 'realtime_app_icon_tests.exe'
$template = Get-Content -LiteralPath (Join-Path $projectRoot 'native/realtime/app_icon.rc.in') -Raw
Set-Content -LiteralPath $resourceFile -Value $template.Replace('@ROOT@', $projectRoot.Replace('\', '/')) -Encoding ascii
& $rc /nologo "/fo$resourceObject" $resourceFile
if ($LASTEXITCODE) { throw 'Logo resource compilation failed.' }
$arguments = @('/nologo', '/std:c++20', '/EHsc', '/MT', '/UNDEBUG',
    "/I$(Join-Path $compiler.FullName 'include')",
    "/I$sdk/Include/$sdkVersion/ucrt", "/I$sdk/Include/$sdkVersion/shared", "/I$sdk/Include/$sdkVersion/um",
    "/Fo$(Join-Path $workRoot 'app_icon_tests.obj')", "/Fe$testExe",
    (Join-Path $projectRoot 'native/realtime/app_icon_tests.cpp'), $resourceObject,
    '/link', "/LIBPATH:$(Join-Path $compiler.FullName 'lib/x64')",
    "/LIBPATH:$sdk/Lib/$sdkVersion/ucrt/x64", "/LIBPATH:$sdk/Lib/$sdkVersion/um/x64", 'user32.lib', 'gdi32.lib')
& $cl @arguments
if ($LASTEXITCODE) { throw 'Logo window validation build failed.' }
& $testExe
if ($LASTEXITCODE) { throw 'Logo window validation failed.' }
