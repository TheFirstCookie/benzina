$ErrorActionPreference = 'Stop'
$taskName = 'ANRE fuel prices - GitHub dispatch'
$python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$script = Join-Path $PSScriptRoot 'dispatch_prices.py'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install requirements.txt before installing the task.'
}
if ((Get-TimeZone).Id -ne 'E. Europe Standard Time') {
    throw 'This task expects the Windows time zone to be Chisinau (E. Europe Standard Time).'
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}"' -f $script) -WorkingDirectory $PSScriptRoot
$triggers = @('12:43', '12:53', '13:03') | ForEach-Object {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $_
    # A boundary without a UTC offset follows the Windows local clock across DST.
    $trigger.StartBoundary = (Get-Date $_).ToString("yyyy-MM-dd'T'HH:mm:ss")
    $trigger
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
    -Principal $principal -Description 'Fetch fresh ANRE history and trigger GitHub delivery for 12:50 Chisinau time.'
