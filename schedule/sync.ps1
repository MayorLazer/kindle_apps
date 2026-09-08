#Requires -Version 5.1
param(
  [string]$Config = "",
  [string]$KindleRoot = "",
  [string]$Python = "",
  [switch]$SkipGenerate,
  [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Here
$LogDir = Join-Path $Here "output"
$LogFile = Join-Path $LogDir "sync.log"
if (-not $Config) { $Config = Join-Path $Here "config.toml" }

function Write-Log {
  param([string]$Message)
  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
  Add-Content -Path $LogFile -Value $line
  if (-not $Quiet) { Write-Host $Message }
}

function Get-TomlValue {
  param([string]$Path, [string]$Key, [string]$Default = "")
  if (-not (Test-Path $Path)) { return $Default }
  foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
    $t = $line.Trim()
    if ($t.StartsWith("#") -or -not $t) { continue }
    if ($t -match ("^\s*{0}\s*=\s*(.+)$" -f [regex]::Escape($Key))) {
      $raw = $Matches[1].Trim()
      if ($raw -match '^"(.*)"$') { return $Matches[1] }
      if ($raw -match "^'(.*)'$") { return $Matches[1] }
      return $raw.TrimEnd(',')
    }
  }
  return $Default
}

if (-not (Test-Path $Config)) {
  Write-Log "Missing config.toml. Copy config.example.toml to config.toml and add your ICS URL."
  exit 1
}

if (-not $Python) {
  foreach ($cand in @("py", "python")) {
    try {
      $v = & $cand -3.11 -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $v) { $Python = $v.Trim(); break }
    } catch {}
    try {
      $v = & $cand -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $v) { $Python = $v.Trim(); break }
    } catch {}
  }
}
if (-not $Python) { throw "Python not found. Install Python 3.11+." }

$Pdf = Join-Path $Here "output\calendar.pdf"
$Png = Join-Path $Here "output\calendar.png"
$BoardNames = @("calendar.png", "today.png", "weather.png", "month.png")

if (-not $SkipGenerate) {
  Write-Log "Using Python: $Python"
  Write-Log "Installing deps if needed..."
  & $Python -m pip install --quiet "icalendar>=6" "recurring-ical-events>=3" "reportlab>=4" "Pillow>=10" "tzdata>=2024.1"
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

  Write-Log "Generating PDF+PNGs..."
  & $Python (Join-Path $Here "generate.py") --config $Config
  if ($LASTEXITCODE -ne 0) { throw "generate.py failed" }
}

if (-not (Test-Path $Png)) { throw "PNG not found at $Png (needed for KUAL)" }
$BoardPngs = @(
  foreach ($name in $BoardNames) {
    $p = Join-Path $Here "output\$name"
    if (Test-Path $p) { $p }
  }
)

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

function Copy-ToKindlePaths {
  param([string]$Root)
  $copied = @()
  foreach ($src in $BoardPngs) {
    $docPng = Join-Path $Root "documents\$(Split-Path $src -Leaf)"
    Copy-Item -Force $src $docPng
    $copied += $docPng
  }

  $extDir = Join-Path $Root "extensions\calendar"
  if (-not (Test-Path $extDir)) {
    $srcExt = Join-Path $RepoRoot "extensions\calendar"
    if (Test-Path $srcExt) {
      Copy-Item -Recurse -Force $srcExt $extDir
      Write-Log "Installed KUAL extension to $extDir"
    }
  }
  if (Test-Path $extDir) {
    foreach ($src in $BoardPngs) {
      $extPng = Join-Path $extDir (Split-Path $src -Leaf)
      Copy-Item -Force $src $extPng
      $copied += $extPng
    }
    # Refresh scripts (LF-safe copy from repo)
    $srcBin = Join-Path $RepoRoot "extensions\calendar\bin"
    if (Test-Path $srcBin) {
      Get-ChildItem -Path $srcBin -File | Where-Object { $_.Name -ne "config" } | ForEach-Object {
        Copy-Item -Force $_.FullName (Join-Path $extDir "bin\$($_.Name)")
      }
      Copy-Item -Force (Join-Path $RepoRoot "extensions\calendar\menu.json") $extDir
      Copy-Item -Force (Join-Path $RepoRoot "extensions\calendar\config.xml") $extDir
    }
  }

  if (Test-Path $Pdf) {
    Copy-Item -Force $Pdf (Join-Path $Root "documents\calendar.pdf")
    $copied += (Join-Path $Root "documents\calendar.pdf")
  }
  return $copied
}

$delivered = $false

$Root = Find-KindleRoot -Hint $KindleRoot
if (-not [string]::IsNullOrWhiteSpace($Root)) {
  $paths = Copy-ToKindlePaths -Root $Root
  foreach ($p in $paths) { Write-Log "USB: $p" }
  $delivered = $true
}

$SshHost = Get-TomlValue -Path $Config -Key "ssh_host" -Default ""
$SshPort = Get-TomlValue -Path $Config -Key "ssh_port" -Default "2222"
$SshUser = Get-TomlValue -Path $Config -Key "ssh_user" -Default "root"

if (-not [string]::IsNullOrWhiteSpace($SshHost)) {
  $scp = Get-Command scp -ErrorAction SilentlyContinue
  if (-not $scp) {
    Write-Log "scp not found (install OpenSSH Client). Skipping Wi-Fi push."
  } else {
    Write-Log "Trying SCP to ${SshUser}@${SshHost}:${SshPort} ..."
    $ok = $false
    foreach ($src in $BoardPngs) {
      $leaf = Split-Path $src -Leaf
      foreach ($remoteDir in @("/mnt/us/documents", "/mnt/us/extensions/calendar")) {
        $target = "{0}@{1}:{2}/{3}" -f $SshUser, $SshHost, $remoteDir, $leaf
        & scp -P $SshPort -o "StrictHostKeyChecking=accept-new" -o "ConnectTimeout=8" -q $src $target
        if ($LASTEXITCODE -eq 0) {
          Write-Log "SCP OK: $target"
          $ok = $true
        }
      }
    }
    if ($ok) { $delivered = $true }
    else { Write-Log "SCP failed (Kindle asleep/offline?)." }
  }
}

if (-not $delivered) {
  Write-Log "PNG ready at $Png (no Kindle delivery this run)"
  if (-not $Quiet) {
    Write-Host "Plug USB and re-run, or set ssh_host in config.toml."
  }
  exit 0
}

if (-not $Quiet) {
  Write-Host ""
  Write-Host "On Kindle: KUAL > Tablero > Hoy / Calendario / Clima / Mes"
  Write-Host "Exit:      KUAL > Tablero > Salir"
}
