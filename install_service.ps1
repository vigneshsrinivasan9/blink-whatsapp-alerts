<#
.SYNOPSIS
    Install the Blink -> WhatsApp monitor as a Windows Scheduled Task that runs
    24x7: starts at boot, runs whether or not you're logged in, and restarts
    automatically if it ever stops.

.DESCRIPTION
    Registers a Scheduled Task that launches supervisor.py (which in turn runs
    the cloudflared tunnel + monitor and restarts it on crash). This is the most
    robust way to keep the pipeline alive year-round on a Windows machine.

.USAGE
    # Run once, from an *elevated* PowerShell (Run as Administrator):
    powershell -ExecutionPolicy Bypass -File .\install_service.ps1

    # To remove it later:
    powershell -ExecutionPolicy Bypass -File .\install_service.ps1 -Uninstall
#>
param(
    [switch]$Uninstall,
    [string]$TaskName = "BlinkWhatsAppMonitor"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Resolve a REAL Python interpreter that has the project dependencies.
# Avoid the Microsoft Store stub (WindowsApps\python3.exe) which is not a real
# Python and fails with "Python was not found". We validate that the chosen
# interpreter can import a required package (dotenv) before using it.
function Find-Python {
    $candidates = @()
    # Prefer windowless pythonw.exe / python.exe next to known install dirs.
    foreach ($base in @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python*",
        "${env:ProgramFiles(x86)}\Python*"
    )) {
        Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                $candidates += (Join-Path $_.FullName "pythonw.exe")
                $candidates += (Join-Path $_.FullName "python.exe")
            }
    }
    # Then whatever is on PATH (but we'll still validate it).
    foreach ($n in @("pythonw.exe", "python.exe")) {
        $c = (Get-Command $n -ErrorAction SilentlyContinue).Source
        if ($c) { $candidates += $c }
    }
    foreach ($c in ($candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)) {
        if ($c -like "*\WindowsApps\*") { continue }   # skip Store stub
        & $c -c "import dotenv, twilio, blinkpy" 2>$null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    } else {
        Write-Host "No scheduled task named '$TaskName' found." -ForegroundColor Yellow
    }
    return
}

$python = Find-Python
if (-not $python) {
    throw "Could not find a Python interpreter with the required packages " +
          "(dotenv, twilio, blinkpy). Run 'pip install -r requirements.txt' first."
}

$supervisor = Join-Path $ProjectDir "supervisor.py"
if (-not (Test-Path $supervisor)) {
    throw "supervisor.py not found in $ProjectDir"
}

Write-Host "Python   : $python"
Write-Host "Project  : $ProjectDir"
Write-Host "Script   : $supervisor"

# Action: run the supervisor from the project directory.
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$supervisor`"" -WorkingDirectory $ProjectDir

# Trigger: at system startup (no login required).
$triggerBoot = New-ScheduledTaskTrigger -AtStartup

# Settings: keep it alive forever; restart on failure; don't stop on idle/battery.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 999 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

# Run as SYSTEM so it works without an interactive session.
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger $triggerBoot `
    -Settings $settings `
    -Principal $principal `
    -Description "Blink motion -> WhatsApp alert monitor (24x7 supervisor)." | Out-Null

Write-Host "`nInstalled scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "It will start at every boot and restart automatically if it stops."
Write-Host "`nStart it now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Check status with:  Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "View logs:          run from a normal console with 'python supervisor.py' to see live output."
