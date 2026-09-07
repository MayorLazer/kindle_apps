#Requires -Version 5.1
# Serve calendar.png over plain HTTP for the Kindle (BusyBox wget has no HTTPS).
#
# 1. Generate or download a PNG first (sync.ps1 / browser).
# 2. Run this script, note the printed URL.
# 3. On Kindle bin/config set:
#      CALENDAR_URL="http://YOUR_PC_IP:8765/calendar.png"
# 4. KUAL > Calendario > Actualizar y mostrar (Kindle on same Wi-Fi).

param(
  [int]$Port = 8765,
  [string]$Png = "",
  [switch]$FetchFromPages
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Png) { $Png = Join-Path $Here "output\calendar.png" }

if ($FetchFromPages -or -not (Test-Path $Png)) {
  $url = "https://mayorlazer.github.io/kindle_apps/calendar.png"
  Write-Host "Downloading $url ..."
  $dir = Split-Path -Parent $Png
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  Invoke-WebRequest -Uri $url -OutFile $Png -UseBasicParsing
}

if (-not (Test-Path $Png)) {
  throw "No PNG at $Png. Run generate/sync first, or pass -FetchFromPages."
}

$bytes = [IO.File]::ReadAllBytes((Resolve-Path $Png))
Write-Host "Serving $Png ($($bytes.Length) bytes) on port $Port"

$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
  Select-Object -ExpandProperty IPAddress -Unique)
if (-not $ips) { $ips = @("YOUR_PC_IP") }

Write-Host ""
Write-Host "Put this in Kindle extensions/calendar/bin/config :"
foreach ($ip in $ips) {
  Write-Host ("  CALENDAR_URL=`"http://{0}:{1}/calendar.png`"" -f $ip, $Port)
}
Write-Host ""
Write-Host "Ctrl+C to stop."

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add("http://+:${Port}/")
try {
  $listener.Start()
} catch {
  Write-Host "Bind on all interfaces failed; trying localhost only. Run as Admin for LAN."
  $listener = [System.Net.HttpListener]::new()
  $listener.Prefixes.Add("http://127.0.0.1:${Port}/")
  $listener.Start()
  Write-Host "WARNING: only localhost — Kindle on Wi-Fi cannot reach this. Re-run elevated."
}

while ($listener.IsListening) {
  $ctx = $listener.GetContext()
  $req = $ctx.Request
  $res = $ctx.Response
  $path = $req.Url.AbsolutePath.TrimEnd("/")
  if ($path -eq "" -or $path -eq "/calendar.png" -or $path -eq "/calendar") {
    $res.StatusCode = 200
    $res.ContentType = "image/png"
    $res.ContentLength64 = $bytes.Length
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
    Write-Host "$(Get-Date -Format HH:mm:ss) $($req.RemoteEndPoint) OK $($bytes.Length)B"
  } else {
    $res.StatusCode = 404
    $msg = [Text.Encoding]::UTF8.GetBytes("not found")
    $res.OutputStream.Write($msg, 0, $msg.Length)
    Write-Host "$(Get-Date -Format HH:mm:ss) $($req.RemoteEndPoint) 404 $($req.Url.AbsolutePath)"
  }
  $res.Close()
}
