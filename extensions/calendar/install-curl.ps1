#Requires -Version 5.1
# Download a static ARM curl and copy it onto the Kindle for HTTPS calendar fetch.
#
# Usage:
#   1. Plug in the Kindle (USB drive mode)
#   2. powershell -ExecutionPolicy Bypass -File .\extensions\calendar\install-curl.ps1
#
# Default = armhf (firmware ~5.16.3+). If curl fails on device, re-run with -Arch armv7
# (older PW4 / pre-5.16 soft-float).

param(
  [ValidateSet("armhf", "armv7")]
  [string]$Arch = "armhf",
  [string]$KindleRoot = "",
  [switch]$DownloadOnly
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$BinDir = Join-Path $Here "bin"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)

# armhf: modern Kindle hard-float. armv7: older soft-float (from v8.11.0 release).
if ($Arch -eq "armhf") {
  $Url = "https://github.com/moparisthebest/static-curl/releases/latest/download/curl-armhf"
  $LocalName = "curl-armhf"
} else {
  $Url = "https://github.com/moparisthebest/static-curl/releases/download/v8.11.0/curl-armv7"
  $LocalName = "curl-armv7"
}

$LocalPath = Join-Path $BinDir $LocalName
$CurlPath = Join-Path $BinDir "curl"

if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }

Write-Host "Downloading $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $LocalPath -UseBasicParsing
Copy-Item -Force $LocalPath $CurlPath
Write-Host "Saved: $CurlPath ($((Get-Item $CurlPath).Length) bytes) [$Arch]"

function Find-KindleRoot {
  param([string]$Hint)
  if ($Hint -and (Test-Path (Join-Path $Hint "documents"))) {
    return $Hint.TrimEnd('\')
  }
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

if ($DownloadOnly) {
  Write-Host "DownloadOnly: plug Kindle later and re-run without -DownloadOnly."
  exit 0
}

$Root = Find-KindleRoot -Hint $KindleRoot
if (-not $Root) {
  Write-Host ""
  Write-Host "Kindle not found. Plug it in as a USB drive, then re-run this script."
  Write-Host "Binary is ready at: $CurlPath"
  exit 2
}

$DestBin = Join-Path $Root "extensions\calendar\bin"
if (-not (Test-Path $DestBin)) {
  $src = Join-Path $RepoRoot "extensions\calendar"
  if (-not (Test-Path $src)) { throw "Missing calendar extension at $src" }
  Copy-Item -Recurse -Force $src (Join-Path $Root "extensions\calendar")
  Write-Host "Installed calendar extension."
}

Copy-Item -Force $CurlPath (Join-Path $DestBin "curl")
Copy-Item -Force $LocalPath (Join-Path $DestBin $LocalName)
Write-Host "Copied curl -> $DestBin\curl"

# Refresh scripts (not config)
$srcBin = Join-Path $RepoRoot "extensions\calendar\bin"
Get-ChildItem -Path $srcBin -File | Where-Object {
  $_.Name -notin @("config", "curl", "curl-armhf", "curl-armv7")
} | ForEach-Object {
  Copy-Item -Force $_.FullName (Join-Path $DestBin $_.Name)
}

$Cfg = Join-Path $DestBin "config"
$curlLine = 'CURL="/mnt/us/extensions/calendar/bin/curl"'
$urlLine = 'CALENDAR_URL="https://mayorlazer.github.io/kindle_apps/calendar.png"'
if (-not (Test-Path $Cfg)) {
  @(
    'CALENDAR_URL="https://mayorlazer.github.io/kindle_apps/calendar.png"'
    'CURL="/mnt/us/extensions/calendar/bin/curl"'
    'FBINK="/mnt/us/libkh/bin/fbink"'
  ) | Set-Content -Path $Cfg -Encoding ASCII
  Write-Host "Created $Cfg"
} else {
  $text = [IO.File]::ReadAllText($Cfg) -replace "`r`n", "`n"
  if ($text -notmatch '(?m)^CURL=') {
    $text = $text.TrimEnd() + "`n`n$curlLine`n"
  } else {
    $text = [regex]::Replace($text, '(?m)^CURL=.*$', $curlLine)
  }
  if ($text -notmatch '(?m)^CALENDAR_URL=') {
    $text = $urlLine + "`n" + $text
  }
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [IO.File]::WriteAllText($Cfg, ($text -replace "`r`n", "`n" -replace "`r", "`n"), $utf8)
  Write-Host "Updated CURL= in $Cfg"
}

Write-Host ""
Write-Host "Done. Eject the Kindle safely, then:"
Write-Host "  KUAL > Tablero > Hoy > Actualizar y mostrar"
Write-Host ""
Write-Host "If download still fails, re-run with: -Arch armv7"
