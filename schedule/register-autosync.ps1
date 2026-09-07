#Requires -Version 5.1
<#
  Register Windows Scheduled Tasks for automatic calendar sync.

  Examples:
    .\register-autosync.ps1 -DailyHour 7
    .\register-autosync.ps1 -DailyHour 7 -UsbWatch
    .\register-autosync.ps1 -Unregister
#>
param(
  [int]$DailyHour = 7,
  [int]$DailyMinute = 0,
  [switch]$UsbWatch,
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Sync = Join-Path $Here "sync.ps1"
$Watch = Join-Path $Here "watch-usb.ps1"
$DailyName = "KindleCalendarDailySync"
$UsbName = "KindleCalendarUsbWatch"

if ($Unregister) {
  schtasks /Delete /TN $DailyName /F 2>$null | Out-Null
  schtasks /Delete /TN $UsbName /F 2>$null | Out-Null
  Write-Host "Removed scheduled tasks (if they existed)."
  exit 0
}

if (-not (Test-Path $Sync)) { throw "sync.ps1 not found" }

# Daily generate + deliver (USB and/or SCP)
$dailyCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Sync`" -Quiet"
$time = "{0:D2}:{1:D2}" -f $DailyHour, $DailyMinute
schtasks /Create /TN $DailyName /TR $dailyCmd /SC DAILY /ST $time /F | Out-Null
Write-Host "Registered daily task '$DailyName' at $time every day."
Write-Host "  Command: $dailyCmd"

if ($UsbWatch) {
  if (-not (Test-Path $Watch)) { throw "watch-usb.ps1 not found" }
  # At logon, start USB watcher (runs while you are logged in)
  $usbCmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Watch`""
  schtasks /Create /TN $UsbName /TR $usbCmd /SC ONLOGON /F | Out-Null
  Write-Host "Registered logon task '$UsbName' (auto-sync when Kindle is plugged in)."
  Write-Host "Starting watcher now..."
  Start-Process powershell.exe -ArgumentList @("-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", $Watch) | Out-Null
}

Write-Host ""
Write-Host "Optional Wi-Fi push: set ssh_host in config.toml (KOReader SSH, usually port 2222)."
Write-Host "Wake the Kindle on Wi-Fi around sync time so SCP can connect."
Write-Host ""
Write-Host "Test now:  powershell -ExecutionPolicy Bypass -File .\sync.ps1"
Write-Host "Remove:     powershell -ExecutionPolicy Bypass -File .\register-autosync.ps1 -Unregister"
