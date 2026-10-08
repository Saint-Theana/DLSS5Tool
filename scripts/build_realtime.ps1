param([ValidateSet('Release','Debug')][string]$Configuration = 'Release')
$ErrorActionPreference = 'Stop'
$realtimeRoot = Split-Path $PSScriptRoot -Parent
$realtimeBuild = Join-Path $realtimeRoot 'tmp/realtime-integration-20261003/build'
$realtimeOutput = Join-Path $realtimeRoot 'runtime/realtime'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vsPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$vsPath) { throw 'Visual Studio C++ Build Tools are required.' }
$cmake = Join-Path $vsPath 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
$python = Join-Path $realtimeRoot '.venv/Scripts/python.exe'
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($realtimeRoot).TrimEnd('\').TrimEnd(':'))).Free -lt 19GB) {
    throw 'Realtime build requires 4 GiB task allowance plus 15 GiB reserve.'
}
& $cmake -S "$realtimeRoot/native/realtime" -B $realtimeBuild -G 'Visual Studio 17 2022' -A x64 "-DPython3_EXECUTABLE=$python"
if ($LASTEXITCODE) { throw 'Realtime CMake configuration failed.' }
& $cmake --build $realtimeBuild --config $Configuration --parallel 4
if ($LASTEXITCODE) { throw 'Realtime native build failed.' }
# Only shader sources and open-source license notices are staged; no GPU DLLs.
New-Item -ItemType Directory -Path "$realtimeOutput/effects" -Force | Out-Null
Copy-Item -Path "$realtimeRoot/third_party/realtime/magpie/src/Effects/*" -Destination "$realtimeOutput/effects" -Recurse -Force
Copy-Item -LiteralPath "$realtimeRoot/third_party/realtime/magpie/LICENSE" -Destination "$realtimeOutput/LICENSE-Magpie-GPLv3.txt"
& $python -B "$realtimeRoot/scripts/realtime_provenance.py"
if ($LASTEXITCODE) { throw 'Realtime provenance staging failed.' }
Write-Output "Built $realtimeOutput/dlss5_realtime_host.exe"
