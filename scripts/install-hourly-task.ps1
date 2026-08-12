$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TaskName = "TRZIP X Google Hourly Collector"
$Now = Get-Date
$NextHour = $Now.Date.AddHours($Now.Hour + 1)
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\collect-hourly.ps1`""
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $NextHour `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Runs at minute 00 every hour. Trends MCP is disabled in this scheduled command." `
    -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName
