<#
.SYNOPSIS
    Starts Bore (TCP Media) for Mediasoup SFU.

.DESCRIPTION
    This script handles the TCP endpoint for Mediasoup:
      1. Uses Vite to proxy HTTP signaling (so ngrok is skipped here)
      2. Starts bore (tunneling TCP port 44444) -> Extracts bore.pub IP and Port
      3. Injects variables (WEBRTC_ANNOUNCED_IP, WEBRTC_SERVER_PORT, TCP_TUNNEL_MODE)
      4. Runs the SFU (npm run dev)


.EXAMPLE
    .\scripts\start-sfu-tunnel.ps1
#>

$ErrorActionPreference = 'Stop'
[console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ─── Resolve paths ────────────────────────────────────────────────────────────
$RootDir   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SfuDir    = Join-Path $RootDir 'sfu'

# Local tools cache lives outside the repo (per-user) — see docs/local-tools.md
$ToolsDir  = Join-Path $env:LOCALAPPDATA 'HTQWeb\tools'

# Prefer a system-installed bore (winget/choco) if available; otherwise fall back to the cache
$boreCmd = Get-Command bore -ErrorAction SilentlyContinue
if ($boreCmd) {
    $BorePath = $boreCmd.Source
} else {
    $BorePath = Join-Path $ToolsDir 'bore.exe'
}

$NgrokLogOut   = Join-Path $ToolsDir 'ngrok-out.log'
$NgrokLogErr   = Join-Path $ToolsDir 'ngrok-err.log'
$BoreLogOut = Join-Path $ToolsDir 'bore-out.log'
$BoreLogErr = Join-Path $ToolsDir 'bore-err.log'

Write-Host ''
Write-Host ('========================================================') -ForegroundColor Cyan
Write-Host '  HTQWeb SFU -- Tunnel Mode (Bore Only)' -ForegroundColor Cyan
Write-Host ('========================================================') -ForegroundColor Cyan
Write-Host ''

# ─── Step 1: Ensure tools are downloaded ──────────────────────────────────────
Write-Host '[1/5] Checking tools...' -ForegroundColor Yellow

if (-not (Test-Path $ToolsDir)) { New-Item -ItemType Directory -Path $ToolsDir | Out-Null }

if (-not (Test-Path $BorePath)) {
    Write-Host '   Downloading bore (TCP Tunnel)...' -ForegroundColor Gray
    # Assuming AMD64 Windows binary
    $boreUrl = "https://github.com/ekzhang/bore/releases/download/v0.5.2/bore-v0.5.2-x86_64-pc-windows-msvc.zip"
    $boreZip = Join-Path $ToolsDir 'bore.zip'
    Invoke-WebRequest $boreUrl -OutFile $boreZip
    Expand-Archive $boreZip -DestinationPath $ToolsDir -Force
    Remove-Item $boreZip
}
Unblock-File -Path $BorePath -ErrorAction SilentlyContinue
Write-Host '   OK bore.pub CLI' -ForegroundColor Green
Write-Host ''

# ─── Step 2: Stop existing tunnels and clean logs ─────────────────────────────
Write-Host '[2/5] Cleaning up old processes...' -ForegroundColor Yellow

Get-Process -Name 'ngrok','bore' -ErrorAction SilentlyContinue | Stop-Process -Force

# Kill any process still holding SFU ports (previous Node.js instance)
foreach ($port in @(4443, 44444)) {
    $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
    foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
}

Start-Sleep -Seconds 1
foreach ($f in @($BoreLogOut, $BoreLogErr)) {
    if (Test-Path $f) { Remove-Item $f -Force }
}
Write-Host '   OK Cleaned' -ForegroundColor Green
Write-Host ''

# ─── Step 3: Start Tunnels ────────────────────────────────────────────────────
Write-Host '[3/5] Starting Tunnel (Bore)...' -ForegroundColor Yellow

# Start Bore TCP Tunnel for media (44444) -> bore.pub
# bore prints the listening address to stdout.
$boreProcess = Start-Process -FilePath $BorePath `
    -ArgumentList @("local","44444","--to","bore.pub") `
    -RedirectStandardOutput $BoreLogOut `
    -RedirectStandardError  $BoreLogErr `
    -WindowStyle Hidden -PassThru

Write-Host "   Waiting up to 15 seconds for bore to establish..." -ForegroundColor Gray

# Watch logs to extract URL
$borePort = $null

$timeout = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $timeout -and (-not $borePort)) {
    Start-Sleep -Milliseconds 500
    
    if (-not $borePort) {
        foreach ($logFile in @($BoreLogOut, $BoreLogErr)) {
            if (Test-Path $logFile) {
                $boreMatches = Select-String -Path $logFile -Pattern 'listening at bore\.pub:(\d+)'
                if ($boreMatches) { $borePort = $boreMatches[-1].Matches[0].Groups[1].Value; break }
            }
        }
    }
}

if (-not $borePort) {
    Write-Host "ERROR: Failed to extract Bore TCP port. Check $BoreLogOut / $BoreLogErr" -ForegroundColor Red
    $boreProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    exit 1
}

# Resolve bore.pub to an IP address (Mediasoup needs an IP, not a hostname)
$boreIp = [System.Net.Dns]::GetHostAddresses('bore.pub') | Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1 -ExpandProperty IPAddressToString

Write-Host ''
Write-Host "   OK Signaling URL : Automatically proxied by Vite" -ForegroundColor Green
Write-Host "   OK Media IP      : $boreIp" -ForegroundColor Green
Write-Host "   OK Media Port    : $borePort" -ForegroundColor Green
Write-Host ''

# ─── Step 4: Inject Environment Variables ─────────────────────────────────────
Write-Host '[4/5] Injecting SFU environment variables...' -ForegroundColor Yellow

$env:WEBRTC_ANNOUNCED_IP            = $boreIp
$env:WEBRTC_ANNOUNCED_PORT          = $borePort
$env:WEBRTC_SERVER_PORT             = '44444'
$env:WEBRTC_ENABLE_UDP              = 'false'
$env:WEBRTC_ENABLE_TCP              = 'true'
$env:WEBRTC_PREFER_UDP              = 'false'
$env:WEBRTC_PREFER_TCP              = 'true'
$env:TCP_TUNNEL_MODE                = 'true'
$env:SIGNALING_REQUIRE_TLS          = 'false'
$env:SIGNALING_DISABLE_ORIGIN_CHECK = 'true'
$env:SIGNALING_ALLOW_NO_ORIGIN      = 'true'

# OpenRelay Free TURN Server to guarantee ICE connectivity around strict NATs and TCP proxy STUN mapping issues.
$env:TURN_URLS                      = "turn:openrelay.metered.ca:80,turn:openrelay.metered.ca:443,turn:openrelay.metered.ca:443?transport=tcp"
$env:TURN_USERNAME                  = "openrelayproject"
$env:TURN_CREDENTIAL                = "openrelayproject"

Write-Host "   WEBRTC_ANNOUNCED_IP = $($env:WEBRTC_ANNOUNCED_IP)" -ForegroundColor DarkCyan
Write-Host "   WEBRTC_ANNOUNCED_PORT = $($env:WEBRTC_ANNOUNCED_PORT) (Bore remote port)" -ForegroundColor DarkCyan
Write-Host "   WEBRTC_SERVER_PORT  = $($env:WEBRTC_SERVER_PORT) (Local bind port)" -ForegroundColor DarkCyan
Write-Host "   TCP_TUNNEL_MODE     = true (UDP disabled)" -ForegroundColor DarkCyan
Write-Host "   TURN_URLS           = Free OpenRelay active" -ForegroundColor DarkCyan
Write-Host ''

# ─── Step 5: Start SFU ────────────────────────────────────────────────────────
Write-Host '[5/5] Starting Mediasoup SFU...' -ForegroundColor Yellow
Write-Host ''
Write-Host '  Clients should connect to:' -ForegroundColor Magenta
Write-Host "    WS signaling : Current Ngrok/Vite Origin + /ws/sfu" -ForegroundColor Magenta
Write-Host "    ICE media    : $($boreIp):$($borePort) (TCP)" -ForegroundColor Magenta
Write-Host ''
Write-Host '  Press Ctrl+C to stop the SFU.' -ForegroundColor DarkGray
Write-Host "  To stop tunnels: Stop-Process -Name bore" -ForegroundColor DarkGray
Write-Host ('-' * 56) -ForegroundColor DarkGray

Push-Location $SfuDir
try {
    npm run dev
} finally {
    Pop-Location
    # Auto-cleanup tunnels on exit
    $boreProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "Tunnels stopped." -ForegroundColor DarkGray
}
