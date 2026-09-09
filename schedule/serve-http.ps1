#Requires -Version 5.1
# Serve board PNGs over plain HTTP for the Kindle (BusyBox wget has no HTTPS).
#
# 1. Generate first (sync.ps1 / generate.py).
# 2. Run this script, note the printed URL.
# 3. On Kindle bin/config set:
#      CALENDAR_URL="http://YOUR_PC_IP:8765/calendar.png"
#    Sibling views (today.png, weather.png, month.png) are derived from that URL.
# 4. KUAL > Tablero > Hoy / Semanal / Calendario / Clima / Mes

param(
  [int]$Port = 8765,
  [string]$Dir = "",
  [switch]$FetchFromPages
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Dir) { $Dir = Join-Path $Here "output" }
$CalendarPng = Join-Path $Dir "calendar.png"

if ($FetchFromPages) {
  Write-Host "Pages no longer hosts the calendar. Generate locally or use the private data repo."
}

if (-not (Test-Path $CalendarPng)) {
  throw "No PNG at $CalendarPng. Run generate/sync first."
}

$allowed = @{
  "/calendar.png" = "calendar.png"
  "/calendar"     = "calendar.png"
  "/weekly.png"   = "weekly.png"
  "/weekly"       = "weekly.png"
  "/today.png"    = "today.png"
  "/today"        = "today.png"
  "/weather.png"  = "weather.png"
  "/weather"      = "weather.png"
  "/month.png"    = "month.png"
  "/month"        = "month.png"
}

Write-Host "Serving $Dir on port $Port"

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
  if (-not $path) { $path = "/calendar.png" }
  $name = $allowed[$path]
  $file = if ($name) { Join-Path $Dir $name } else { $null }
  if ($file -and (Test-Path $file)) {
    $bytes = [IO.File]::ReadAllBytes((Resolve-Path $file))
    $res.StatusCode = 200
    $res.ContentType = "image/png"
    $res.ContentLength64 = $bytes.Length
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
    Write-Host "$(Get-Date -Format HH:mm:ss) $($req.RemoteEndPoint) OK $name $($bytes.Length)B"
  } else {
    $res.StatusCode = 404
    $msg = [Text.Encoding]::UTF8.GetBytes("not found")
    $res.OutputStream.Write($msg, 0, $msg.Length)
    Write-Host "$(Get-Date -Format HH:mm:ss) $($req.RemoteEndPoint) 404 $($req.Url.AbsolutePath)"
  }
  $res.Close()
}
