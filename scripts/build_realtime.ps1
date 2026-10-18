param([ValidateSet('Release','Debug')][string]$Configuration = 'Release',
      [string]$BuildDirectory = '', [string]$OutputDirectory = '', [switch]$QualityOnly)
$ErrorActionPreference = 'Stop'
$realtimeRoot = Split-Path $PSScriptRoot -Parent
$realtimeBuild = Join-Path $realtimeRoot 'tmp/realtime-integration-20261003/build'
$realtimeOutput = Join-Path $realtimeRoot 'runtime/realtime'
if ($BuildDirectory) { $realtimeBuild = [IO.Path]::GetFullPath($BuildDirectory) }
if ($OutputDirectory) { $realtimeOutput = [IO.Path]::GetFullPath($OutputDirectory) }
$qualityOutput = if ($OutputDirectory) { $realtimeOutput } else { Join-Path $realtimeRoot 'runtime' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vsPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$vsPath) { throw 'Visual Studio C++ Build Tools are required.' }
$cmake = Join-Path $vsPath 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
$python = Join-Path $realtimeRoot '.venv/Scripts/python.exe'
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($realtimeRoot).TrimEnd('\').TrimEnd(':'))).Free -lt 19GB) {
    throw 'Realtime build requires 4 GiB task allowance plus 15 GiB reserve.'
}
& $cmake -S "$realtimeRoot/native/realtime" -B $realtimeBuild -G 'Visual Studio 17 2022' -A x64 "-DPython3_EXECUTABLE=$python" "-DREALTIME_OUTPUT_DIR=$realtimeOutput" "-DQUALITY_OUTPUT_DIR=$qualityOutput"
if ($LASTEXITCODE) { throw 'Realtime CMake configuration failed.' }
if ($QualityOnly) {
    & $cmake --build $realtimeBuild --config $Configuration --target dlss5_quality realtime_quality_tests --parallel 4
} else {
    & $cmake --build $realtimeBuild --config $Configuration --parallel 4
}
if ($LASTEXITCODE) { throw 'Realtime native build failed.' }
if ($QualityOnly) {
    Write-Output "Built $qualityOutput/dlss5_quality.dll (no release packaging)"
    exit 0
}
# Only shader sources and open-source license notices are staged; no GPU DLLs.
New-Item -ItemType Directory -Path "$realtimeOutput/effects" -Force | Out-Null
Copy-Item -Path "$realtimeRoot/third_party/realtime/magpie/src/Effects/*" -Destination "$realtimeOutput/effects" -Recurse -Force
Copy-Item -LiteralPath "$realtimeRoot/third_party/realtime/magpie/LICENSE" -Destination "$realtimeOutput/LICENSE-Magpie-GPLv3.txt"
& $python -B "$realtimeRoot/scripts/realtime_provenance.py"
if ($LASTEXITCODE) { throw 'Realtime provenance staging failed.' }
Write-Output "Built $realtimeOutput/dlss5_realtime_host.exe"
