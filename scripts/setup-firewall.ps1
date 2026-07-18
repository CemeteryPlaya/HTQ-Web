<#
.SYNOPSIS
    Open Windows Firewall ports required for local-network WebRTC testing.

.DESCRIPTION
    Creates inbound TCP+UDP rules for:
    - Port 3000  — Vite dev server (frontend)
    - Port 4443  — SFU Mediasoup signaling (WSS)
    - Port 44444 — Mediasoup WebRTC media (single-port mode)

    Also stops and disables IIS (W3SVC) to free port 80.

.NOTES
    Must be run as Administrator (elevated PowerShell).
    Profile: Private — rules apply only on private/home networks.
#>

# Self-elevate if not running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[Setup] Re-launching as Administrator..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @(
        '-ExecutionPolicy', 'Bypass',
        '-NoExit',
        '-File', "`"$PSCommandPath`""
    )
    exit 0
}

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HTQWeb — Firewall & IIS Setup (LAN Dev)"  -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Stop IIS if running ──────────────────────────
$w3svc = Get-Service -Name W3SVC -ErrorAction SilentlyContinue
if ($w3svc) {
    if ($w3svc.Status -eq 'Running') {
        Write-Host "[IIS] Stopping W3SVC (World Wide Web Publishing Service)..." -ForegroundColor Yellow
        Stop-Service -Name W3SVC -Force
        Write-Host "[IIS] W3SVC stopped." -ForegroundColor Green
    } else {
        Write-Host "[IIS] W3SVC is already stopped." -ForegroundColor Green
    }

    if ($w3svc.StartType -ne 'Disabled') {
        Set-Service -Name W3SVC -StartupType Disabled
        Write-Host "[IIS] W3SVC startup type set to Disabled." -ForegroundColor Green
    }
} else {
    Write-Host "[IIS] W3SVC service not found — IIS is not installed. Skipping." -ForegroundColor Green
}

Write-Host ""

# ── Step 2: Create Firewall Rules ────────────────────────
$rules = @(
    @{ Name = "HTQWeb Frontend (Vite Dev)";  Port = "3000" },
    @{ Name = "HTQWeb SFU (Mediasoup WSS)";  Port = "4443" },
    @{ Name = "HTQWeb SFU Media (WebRtcServer)"; Port = "44444" }
)

foreach ($rule in $rules) {
    # Remove stale rules with the same display name
    Get-NetFirewallRule -DisplayName "$($rule.Name) TCP" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    Get-NetFirewallRule -DisplayName "$($rule.Name) UDP" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    # TCP inbound
    New-NetFirewallRule `
        -DisplayName "$($rule.Name) TCP" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $rule.Port `
        -Action Allow `
        -Profile Private `
        -Enabled True | Out-Null

    # UDP inbound (needed for RTP, also harmless for HTTP ports)
    New-NetFirewallRule `
        -DisplayName "$($rule.Name) UDP" `
        -Direction Inbound `
        -Protocol UDP `
        -LocalPort $rule.Port `
        -Action Allow `
        -Profile Private `
        -Enabled True | Out-Null

    Write-Host "[Firewall] $($rule.Name) — port(s) $($rule.Port) opened (TCP+UDP, Private)" -ForegroundColor Green
}

Write-Host ""

# ── Step 3: Show current LAN IP ─────────────────────────
$lanIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' -and
        $_.PrefixOrigin -ne 'WellKnown'
    } |
    Select-Object -First 1
).IPAddress

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Setup Complete" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
if ($lanIp) {
    Write-Host ""
    Write-Host "  Your LAN IP: $lanIp" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Frontend:  https://${lanIp}:3000" -ForegroundColor White
    Write-Host "  SFU:       wss://${lanIp}:4443/ws/sfu/" -ForegroundColor White
    Write-Host "  Backend:   http://${lanIp}:8000" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "  LAN IP not detected. Check your Wi-Fi connection." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "    1. Generate/regenerate certs:  scripts\generate-certs.ps1" -ForegroundColor White
Write-Host "    2. Start backend:  python manage.py runserver 0.0.0.0:8000" -ForegroundColor White
Write-Host "    3. Start SFU:      cd sfu && npm run dev" -ForegroundColor White
Write-Host "    4. Start frontend: cd frontend && npm run dev" -ForegroundColor White
Write-Host "    5. On mobile:      open https://<LAN_IP>:3000 and accept cert" -ForegroundColor White
Write-Host ""
