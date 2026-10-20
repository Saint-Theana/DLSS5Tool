$ErrorActionPreference = 'Stop'
$projectRoot = 'F:\project\DLSS5Tool'
$taskRoot = Join-Path $projectRoot 'tmp\p0-completion-20261020'
$candidatePath = Join-Path $taskRoot 'flush-candidate\dlss5_quality.dll'
$runtimePath = Join-Path $projectRoot 'runtime\dlss5_quality.dll'
$rollbackPath = Join-Path $taskRoot 'rollback\dlss5_quality.dll'
$stagePath = Join-Path $taskRoot 'promotion-staging.dll'

function Assert-PlainPath([string]$Path, [string]$Boundary) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $boundaryAbsolute = [IO.Path]::GetFullPath($Boundary).TrimEnd('\')
    if (!$absolute.StartsWith($boundaryAbsolute + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside intended boundary: $absolute"
    }
    $cursor = $absolute
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($null -ne $item) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $cursor" }
            if ($item.FullName -ne $cursor) { throw "Unexpected resolved path: $cursor" }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

Assert-PlainPath $candidatePath $taskRoot
Assert-PlainPath $rollbackPath $taskRoot
Assert-PlainPath $stagePath $taskRoot
Assert-PlainPath $runtimePath $projectRoot
if ((Get-PSDrive -Name F).Free -lt 15GB + 1MB) { throw 'Insufficient disk headroom' }
$assessment = Get-Content -LiteralPath (Join-Path $taskRoot 'comparison-final.json') -Raw | ConvertFrom-Json
foreach ($label in @('native-composer-fixed-idle300', 'native-composer-resize-long', 'images-native-fix30')) {
    $entry = @($assessment.cases | Where-Object label -eq $label)
    if ($entry.Count -ne 1 -or !$entry[0].processing_and_exit_passed) { throw "Incomplete processing/exit gate: $label" }
    if ($label -eq 'images-native-fix30') { $band = $entry[0].gui_within_declared_band }
    else { $band = $entry[0].within_declared_private_commit_band }
    if (!$band -or !$entry[0].source_comparison.unchanged) { throw "Memory/source gate failed: $label" }
}
$oldHash = '32EA271A83786B1533F4074CB29534CF866B4778D68B0B823DBF4C5DBAF544B6'
if ((Get-FileHash -LiteralPath $rollbackPath -Algorithm SHA256).Hash -ne $oldHash) { throw 'Rollback hash mismatch' }
if ((Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash -ne $oldHash) { throw 'Runtime changed since baseline' }
$candidateHash = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash
$runManifest = Get-Content -LiteralPath (Join-Path $taskRoot 'native-composer-resize-long\run-manifest-after.json') -Raw | ConvertFrom-Json
$expected = @($runManifest.files | Where-Object file -eq 'tmp\p0-completion-20261020\flush-candidate\dlss5_quality.dll')
if ($expected.Count -ne 1 -or $expected[0].sha256 -ne $candidateHash) { throw 'Candidate differs from accepted binary' }
$exclusive = [IO.File]::Open($runtimePath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$exclusive.Dispose()
if (!(Test-Path -LiteralPath $stagePath)) {
    Copy-Item -LiteralPath $candidatePath -Destination $stagePath
}
if ((Get-FileHash -LiteralPath $stagePath -Algorithm SHA256).Hash -ne $candidateHash) { throw 'Staging verification failed' }
Assert-PlainPath $stagePath $taskRoot
Assert-PlainPath $runtimePath $projectRoot
if ([IO.Path]::GetPathRoot($stagePath) -ne [IO.Path]::GetPathRoot($runtimePath)) { throw 'Promotion must stay on one volume' }
[IO.File]::Move($stagePath, $runtimePath, $true)
if ((Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash -ne $candidateHash) { throw 'Promoted runtime verification failed' }
@{ success = $true; runtime = $runtimePath; old_sha256 = $oldHash; new_sha256 = $candidateHash;
   rollback = $rollbackPath; rollback_verified = $true; promoted_utc = [DateTime]::UtcNow.ToString('o') } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'runtime-promotion.json') -Encoding utf8
Write-Output 'Accepted local composer runtime installed; original DLL preserved in task rollback.'
