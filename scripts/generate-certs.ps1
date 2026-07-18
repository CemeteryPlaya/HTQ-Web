<#
.SYNOPSIS
    Generate self-signed SSL certificates for local-network WebRTC testing.

.DESCRIPTION
    Uses mkcert (preferred) or openssl to create cert.pem + key.pem
    in the project's certs/ directory. The certificate covers:
    - localhost, 127.0.0.1, ::1
    - 192.168.*.* (common LAN range)
    - 10.*.*.* (corporate LAN range)
    - Your machine's current LAN IP (auto-detected)

.NOTES
    Install mkcert:  choco install mkcert  OR  scoop install mkcert
    mkcert auto-installs a local CA trusted by browsers — no warnings.
#>

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = $PSScriptRoot }
$certsDir = Join-Path $projectRoot 'infra/certs'
$certsDir = (New-Item -ItemType Directory -Force -Path $certsDir).FullName

$certFile = Join-Path $certsDir 'cert.pem'
$keyFile  = Join-Path $certsDir 'key.pem'

# Auto-detect current LAN IP
$lanIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' -and
        $_.PrefixOrigin -ne 'WellKnown'
    } |
    Select-Object -First 1
).IPAddress

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SSL Certificate Generator (LAN Testing)"   -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Output directory: $certsDir"
if ($lanIp) {
    Write-Host "Detected LAN IP:  $lanIp" -ForegroundColor Green
} else {
    Write-Host "LAN IP not detected — certificate will cover common ranges" -ForegroundColor Yellow
}
Write-Host ""

# Build SAN list
$sans = @(
    'localhost',
    '127.0.0.1',
    '::1'
)
if ($lanIp) { $sans += $lanIp }

# ── Try mkcert first ──
$mkcert = Get-Command mkcert -ErrorAction SilentlyContinue
if ($mkcert) {
    Write-Host "[mkcert] Installing local CA into system trust store..." -ForegroundColor Yellow
    & mkcert -install

    Write-Host "[mkcert] Generating certificate for: $($sans -join ', ')" -ForegroundColor Yellow
    & mkcert -cert-file $certFile -key-file $keyFile @sans

    Write-Host ""
    Write-Host "Done! Certificate files:" -ForegroundColor Green
    Write-Host "  cert: $certFile"
    Write-Host "  key:  $keyFile"
    Write-Host ""
    Write-Host "Browsers will trust this certificate automatically (mkcert CA installed)." -ForegroundColor Green
    exit 0
}

# ── Fallback: openssl ──
$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $openssl) {
    Write-Host "ERROR: Neither mkcert nor openssl found in PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install mkcert:  choco install mkcert" -ForegroundColor Yellow
    Write-Host "  OR"
    Write-Host "Install openssl: choco install openssl" -ForegroundColor Yellow
    exit 1
}

Write-Host "[openssl] Generating self-signed certificate..." -ForegroundColor Yellow

# Build SAN extension
$sanEntries = @("DNS:localhost", "IP:127.0.0.1", "IP:::1")
if ($lanIp) { $sanEntries += "IP:$lanIp" }
$sanString = $sanEntries -join ','

$opensslConf = @"
[req]
default_bits = 2048
prompt = no
default_md = sha256
x509_extensions = v3_req
distinguished_name = dn

[dn]
CN = HTQWeb Local Dev

[v3_req]
subjectAltName = $sanString
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
"@

$confFile = Join-Path $certsDir 'openssl.cnf'
Set-Content -Path $confFile -Value $opensslConf -Encoding UTF8

& openssl req -x509 -nodes -newkey rsa:2048 `
    -keyout $keyFile `
    -out $certFile `
    -days 365 `
    -config $confFile

Remove-Item $confFile -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done! Certificate files:" -ForegroundColor Green
Write-Host "  cert: $certFile"
Write-Host "  key:  $keyFile"
Write-Host ""
Write-Host "WARNING: This is a self-signed certificate (no mkcert)." -ForegroundColor Yellow
Write-Host "Browsers will show a security warning. Accept it to proceed." -ForegroundColor Yellow
Write-Host "For automatic trust, install mkcert: choco install mkcert" -ForegroundColor Yellow
