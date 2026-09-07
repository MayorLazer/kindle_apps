#Requires -Version 5.1
# Watches for Kindle USB mount and runs sync.ps1 (generate + copy).
param(
  [int]$PollSeconds = 15,
  [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Sync = Join-Path $Here "sync.ps1"
$State = Join-Path $Here "output\last-usb-root.txt"
if (-not (Test-Path (Join-Path $Here "output"))) {
  New-Item -ItemType Directory -Path (Join-Path $Here "output") | Out-Null
}

function Find-KindleRoot {
  foreach ($drive in (Get-PSDrive -PSProvider FileSystem)) {
    $root = "$($drive.Name):"
    $docs = Join-Path $root "documents"
    $sys = Join-Path $root "system"
    $ext = Join-Path $root "extensions"
    if ((Test-Path $docs) -and ((Test-Path $sys) -or (Test-Path $ext))) {
      return $root
    }
  }
  return $null
}

$last = ""
if (Test-Path $State) { $last = (Get-Content $State -Raw).Trim() }

Write-Host "USB watch started. Poll=${PollSeconds}s. Ctrl+C to stop."
while ($true) {
  $root = Find-KindleRoot
  if ($root -and $root -ne $last) {
    Write-Host "$(Get-Date -Format o) Kindle detected at $root - syncing..."
    $args = @("-ExecutionPolicy", "Bypass", "-File", $Sync)
    if ($Config) { $args += @("-Config", $Config) }
    & powershell @args
    Set-Content -Path $State -Value $root -Encoding ASCII
    $last = $root
  }
  if (-not $root) {
    if ($last) {
      Write-Host "$(Get-Date -Format o) Kindle disconnected."
      Set-Content -Path $State -Value "" -Encoding ASCII
      $last = ""
    }
  }
  Start-Sleep -Seconds $PollSeconds
}
