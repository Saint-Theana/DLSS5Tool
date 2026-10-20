$ErrorActionPreference='Stop'
$serviceName='NVDisplay.ContainerLocalSystem'
$taskRoot='F:\project\DLSS5Tool\tmp\p0-completion-20261020'
$current=Get-Item -LiteralPath $taskRoot -Force
while ($null -ne $current) {
    if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point rejected' }
    $parent=[IO.Directory]::GetParent($current.FullName)
    $current=if ($null -eq $parent) { $null } else { Get-Item -LiteralPath $parent.FullName -Force }
}
if (-not (Test-Path -LiteralPath ($taskRoot+'\TASK.md'))) { throw 'Missing task registration' }
$service=Get-Service -Name $serviceName
$initial=$service.Status.ToString()
$startType=$service.StartType.ToString()
$record=[ordered]@{service=$serviceName;initial_status=$initial;initial_start_type=$startType;started_utc=[DateTime]::UtcNow.ToString('o');success=$false;error=$null}
$controller=[System.ServiceProcess.ServiceController]::new($serviceName)
try {
    if ($initial -ne 'Running') { throw 'Unexpected initial service status' }
    $controller.Stop()
    $controller.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped,[TimeSpan]::FromSeconds(20))
    $controller.Start()
    $controller.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running,[TimeSpan]::FromSeconds(20))
    $record.success=$true
} catch {
    $record.error=$_.Exception.ToString()
} finally {
    $controller.Refresh()
    # If a stop completed but the normal start failed, attempt restoration once.
    if ($controller.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        try {
            $controller.Start()
            $controller.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running,[TimeSpan]::FromSeconds(15))
        } catch { $record.error=($record.error+'; restoration: '+$_.Exception.Message) }
    }
    $service=Get-Service -Name $serviceName
    $record.final_status=$service.Status.ToString()
    $record.final_start_type=$service.StartType.ToString()
    $record.startup_unchanged=$record.final_start_type -eq $startType
    $record.ended_utc=[DateTime]::UtcNow.ToString('o')
    $record.success=$record.success -and $record.final_status -eq 'Running' -and $record.startup_unchanged
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ($taskRoot+'\nvidia-service-restart-result.json') -Encoding UTF8
    $controller.Dispose()
}
if (-not $record.success) { exit 1 }
