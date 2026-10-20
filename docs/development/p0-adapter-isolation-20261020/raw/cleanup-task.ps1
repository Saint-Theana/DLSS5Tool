$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$taskRoot = 'F:\project\DLSS5Tool\tmp\p0-adapter-isolation-20261020'
$evidenceRoot = 'F:\project\DLSS5Tool\docs\development\p0-adapter-isolation-20261020'

function Assert-RegularPath([string]$path) {
    $absolute = [IO.Path]::GetFullPath($path)
    if ($absolute -ne $path) { throw "Noncanonical path: $path" }
    $current = Get-Item -LiteralPath $absolute -Force
    while ($null -ne $current) {
        if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $($current.FullName)" }
        $parent = [IO.Directory]::GetParent($current.FullName)
        $current = if ($null -eq $parent) { $null } else { Get-Item -LiteralPath $parent.FullName -Force }
    }
    return $absolute
}

function Read-Tree([string]$path) {
    $queue = [Collections.Generic.Queue[string]]::new()
    $queue.Enqueue($path)
    while ($queue.Count -gt 0) {
        $item = Get-Item -LiteralPath (Assert-RegularPath $queue.Dequeue()) -Force
        $item
        if ($item.PSIsContainer) {
            foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) {
                [void](Assert-RegularPath $child.FullName)
                $queue.Enqueue($child.FullName)
            }
        }
    }
}

[void](Assert-RegularPath $taskRoot)
[void](Assert-RegularPath $evidenceRoot)
$summary = Get-Content -LiteralPath "$evidenceRoot\verification-summary.json" -Raw | ConvertFrom-Json
$retired = Get-Content -LiteralPath "$taskRoot\retirement-final.json" -Raw | ConvertFrom-Json
if (-not $retired.passed) { throw 'Owned process retirement is not verified' }
$plan = Get-Content -LiteralPath "$taskRoot\cleanup-plan.json" -Raw | ConvertFrom-Json
$known = @($plan.paths)
$actual = @(Get-ChildItem -LiteralPath $taskRoot -Force | Where-Object Name -ne 'TASK.md' | ForEach-Object FullName)
if (@(Compare-Object $known $actual).Count -ne 0) { throw 'Task contents changed after the explicit cleanup plan' }

foreach ($entry in $summary.archive) {
    $archived = [IO.Path]::GetFullPath((Join-Path $evidenceRoot $entry.file))
    if (-not $archived.StartsWith($evidenceRoot+'\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive path escaped evidence directory' }
    [void](Assert-RegularPath $archived)
    if ((Get-FileHash -LiteralPath $archived -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.archived_sha256) { throw "Archive hash mismatch: $archived" }
    $fileStream = [IO.File]::OpenRead($archived)
    $decoded = [IO.MemoryStream]::new()
    $gzip = $null
    try {
        if ($archived.EndsWith('.gz')) {
            $gzip = [IO.Compression.GZipStream]::new($fileStream, [IO.Compression.CompressionMode]::Decompress)
            $gzip.CopyTo($decoded)
        } else { $fileStream.CopyTo($decoded) }
        if ($decoded.Length -ne $entry.source_bytes) { throw "Decoded length mismatch: $archived" }
        $decoded.Position = 0
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $hash = ([BitConverter]::ToString($sha.ComputeHash($decoded))).Replace('-','').ToLowerInvariant() }
        finally { $sha.Dispose() }
        if ($hash -ne $entry.source_sha256) { throw "Decoded hash mismatch: $archived" }
    } finally {
        if ($null -ne $gzip) { $gzip.Dispose() }
        $fileStream.Dispose(); $decoded.Dispose()
    }
}

$leaves = @()
foreach ($path in $known) {
    if (-not $path.StartsWith($taskRoot+'\', [StringComparison]::OrdinalIgnoreCase)) { throw "Cleanup escaped task: $path" }
    if ([IO.Path]::GetDirectoryName($path) -ne $taskRoot) { throw "Expected an explicit top-level task child: $path" }
    $leaves += @(Read-Tree $path | Where-Object { -not $_.PSIsContainer })
}
foreach ($file in $leaves) {
    $exclusive = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    $exclusive.Dispose()
}
$logical = ($leaves | Measure-Object Length -Sum).Sum
$beforeFree = (Get-PSDrive -Name F).Free
foreach ($path in $known) {
    [void](Assert-RegularPath $path)
    $target = Get-Item -LiteralPath $path -Force
    if ($target.PSIsContainer) { Remove-Item -LiteralPath $path -Recurse -Force }
    else { Remove-Item -LiteralPath $path -Force }
}
$afterFree = (Get-PSDrive -Name F).Free
$remaining = @(Get-ChildItem -LiteralPath $taskRoot -Force -File)
$result = [ordered]@{
    status = 'completed'; targets = $known; files_removed = $leaves.Count
    logical_bytes_removed = $logical; volume_free_before = $beforeFree; volume_free_after = $afterFree
    observed_volume_bytes_freed = $afterFree-$beforeFree
    remaining_files = @($remaining | ForEach-Object Name)
    remaining_bytes = ($remaining | Measure-Object Length -Sum).Sum
    retained_reason = 'TASK.md records evidence location and reconstruction; no media, binaries or environments retained'
    review_date = '2026-10-27'
}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$evidenceRoot\cleanup-summary.json" -Encoding UTF8
$result | ConvertTo-Json -Depth 3
