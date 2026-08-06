<#
.SYNOPSIS
    Открыть локальный dev-стенд наружу для проверки видеоконференции.

.DESCRIPTION
    Сигналинг и медиа разводятся по двум туннелям, потому что ни один
    HTTP-туннель не несёт UDP:

      [браузер гостя] ──https──> Cloudflare ──> localhost:3000 (Vite)
                                                  /api/*    -> backend-web
                                                  /ws/sfu/  -> sfu:4443
      [браузер гостя] ──tcp────> bore.pub ──────> localhost:44444 (медиа SFU)

    Скрипт поднимает оба туннеля, переключает SFU в TCP-режим с адресом
    bore, печатает публичную ссылку и по Ctrl+C возвращает стенд в
    локальное состояние.

    ВАЖНО: в отличие от старого scripts/start-sfu-tunnel.ps1 здесь НЕ
    убиваются процессы, занявшие порты 4443/44444 — теперь их держит
    Docker, и Stop-Process ударил бы по нему.

.PARAMETER WithTurn
    Дополнительно прописать публичный TURN (OpenRelay). Нужен, если у гостя
    строгий NAT и прямого TCP до bore.pub не получается.

.PARAMETER GuestEmail
    Завести гостевую учётку (сразу active) и напечатать пароль. Без этого
    параметра гостю нужен существующий аккаунт: комната требует входа.

.EXAMPLE
    .\scripts\start-public-test.ps1 -GuestEmail guest@htq.local
#>
[CmdletBinding()]
param(
    [switch]$WithTurn,
    [string]$GuestEmail
)

$ErrorActionPreference = 'Stop'

$RootDir  = Split-Path -Parent $PSScriptRoot
$EnvFile  = Join-Path $RootDir '.env'
$ToolsDir = Join-Path $env:LOCALAPPDATA 'HTQWeb\tools'
$Compose  = @('-f', (Join-Path $RootDir 'docker-compose.yml'),
              '-f', (Join-Path $RootDir 'docker-compose.dev.yml'))

# Маркеры управляемого блока в .env — по ним же он и снимается при откате.
$BlockStart = '# >>> public-test >>>'
$BlockEnd   = '# <<< public-test <<<'

$BoreLogOut  = Join-Path $ToolsDir 'bore-out.log'
$BoreLogErr  = Join-Path $ToolsDir 'bore-err.log'
$CfLogOut    = Join-Path $ToolsDir 'cloudflared-out.log'
$CfLogErr    = Join-Path $ToolsDir 'cloudflared-err.log'

function Write-Step  { param([string]$Text) Write-Host "`n[$(Get-Date -Format HH:mm:ss)] $Text" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Text) Write-Host "  $Text" -ForegroundColor Green }
function Write-Warn2 { param([string]$Text) Write-Host "  $Text" -ForegroundColor Yellow }

# ─── Инструменты ────────────────────────────────────────────────────────────

function Resolve-Tool {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Url,
        [switch]$Zip
    )

    $inPath = Get-Command $Name -ErrorAction SilentlyContinue
    if ($inPath) { return $inPath.Source }

    $exePath = Join-Path $ToolsDir "$Name.exe"
    if (Test-Path $exePath) { return $exePath }

    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    Write-Warn2 "$Name не найден — скачиваю в $ToolsDir"

    if ($Zip) {
        $archive = Join-Path $ToolsDir "$Name.zip"
        Invoke-WebRequest $Url -OutFile $archive
        Expand-Archive -Path $archive -DestinationPath $ToolsDir -Force
        Remove-Item $archive -Force
    } else {
        Invoke-WebRequest $Url -OutFile $exePath
    }

    Unblock-File $exePath -ErrorAction SilentlyContinue
    return $exePath
}

# ─── Управляемый блок в .env ────────────────────────────────────────────────

# Корневой .env — UTF-8 без BOM и почти наполовину состоит из русских
# комментариев, поэтому читать и писать его штатными Get-Content/Set-Content
# нельзя: в PS 5.1 Get-Content без -Encoding разбирает файл как cp1251, а
# Set-Content -Encoding utf8 дописывает BOM. Один такой круг раздувает файл
# с 8.9 КБ до 13.9 КБ нечитаемой двойной перекодировки — вместе со всеми
# секретами стенда. Поэтому работаем через .NET с явной UTF8Encoding($false).
function Read-EnvLines {
    if (-not (Test-Path $EnvFile)) { return @() }
    # StreamReader внутри ReadAllLines сам снимет BOM, если он там окажется.
    return [string[]][System.IO.File]::ReadAllLines($EnvFile, [System.Text.Encoding]::UTF8)
}

function Write-EnvLines {
    param([string[]]$Lines)

    # WriteAllLines поставил бы Environment.NewLine, то есть CRLF, и переписал
    # бы весь файл целиком: сейчас он на LF. Сохраняем то окончание строки и
    # тот хвост, что уже есть, — тогда откат возвращает файл байт в байт.
    $newline = "`n"
    $trailing = $true
    if (Test-Path $EnvFile) {
        $raw = [System.IO.File]::ReadAllText($EnvFile, [System.Text.Encoding]::UTF8)
        $firstLf = $raw.IndexOf("`n")
        if ($firstLf -gt 0 -and $raw[$firstLf - 1] -eq "`r") { $newline = "`r`n" }
        $trailing = $raw.EndsWith("`n")
    }

    $text = [string[]]@($Lines) -join $newline
    if ($trailing) { $text += $newline }

    [System.IO.File]::WriteAllText($EnvFile, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Set-EnvBlock {
    param([Parameter(Mandatory)][hashtable]$Values)

    # @() обязательно: из одной строки Remove-EnvBlock вернул бы скаляр,
    # и `$clean + $block` склеил бы строки вместо сложения массивов.
    $clean = @(Remove-EnvBlock -Lines (Read-EnvLines))

    $block = @($BlockStart, '# Снимается автоматически при остановке скрипта.')
    foreach ($key in $Values.Keys | Sort-Object) {
        $block += "$key=$($Values[$key])"
    }
    $block += $BlockEnd

    Write-EnvLines -Lines ($clean + $block)
}

function Remove-EnvBlock {
    param([string[]]$Lines)

    $result = @()
    $inside = $false
    foreach ($line in $Lines) {
        if ($line -eq $BlockStart) { $inside = $true; continue }
        if ($line -eq $BlockEnd)   { $inside = $false; continue }
        if (-not $inside) { $result += $line }
    }
    # Хвостовые пустые строки, чтобы файл не распухал от перезапусков.
    while ($result.Count -gt 0 -and [string]::IsNullOrWhiteSpace($result[-1])) {
        $result = $result[0..($result.Count - 2)]
    }
    return $result
}

function Restore-Env {
    if (-not (Test-Path $EnvFile)) { return }
    Write-EnvLines -Lines @(Remove-EnvBlock -Lines (Read-EnvLines))
}

function Update-Containers {
    param([string]$Reason)
    Write-Step "Пересоздаю sfu и backend-web ($Reason)"
    & docker compose @Compose up -d --no-deps sfu backend-web | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker compose завершился с кодом $LASTEXITCODE" }
}

# ─── Проверки перед стартом ─────────────────────────────────────────────────

Write-Step 'Проверяю окружение'

& docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker недоступен — запустите Docker Desktop' }
Write-Ok 'Docker на связи'

$sfuState = (& docker compose @Compose ps --format '{{.Service}} {{.State}}' | Select-String '^sfu ')
if (-not $sfuState) { throw 'Контейнер sfu не запущен: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d' }
Write-Ok "sfu: $($sfuState.Line.Trim())"

$viteAlive = $false
try {
    Invoke-WebRequest 'http://localhost:3000/' -TimeoutSec 5 -UseBasicParsing | Out-Null
    $viteAlive = $true
} catch { }
if ($viteAlive) {
    Write-Ok 'Vite отвечает на :3000'
} else {
    Write-Warn2 'Vite на :3000 не отвечает — запустите `cd frontend; npm run dev` во втором окне'
}

$bore = Resolve-Tool -Name 'bore' -Zip `
    -Url 'https://github.com/ekzhang/bore/releases/download/v0.5.2/bore-v0.5.2-x86_64-pc-windows-msvc.zip'
$cloudflared = Resolve-Tool -Name 'cloudflared' `
    -Url 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
Write-Ok "bore: $bore"
Write-Ok "cloudflared: $cloudflared"

$boreProcess = $null
$cfProcess = $null
# Пока .env не тронут, откатывать нечего: без этого флага падение на раннем
# шаге (например, недоступен bore.pub) печатало бы «пересоздаю контейнеры» —
# сообщение о работе, которой не было.
$envTouched = $false

try {
    # ─── Медиа-туннель ──────────────────────────────────────────────────────
    # bore.pub — бесплатный публичный релей, и он регулярно отказывает разово:
    # «could not connect to bore.pub:7835 / timed out», а следующая попытка
    # секундой позже подключается. Поэтому пробуем несколько раз, а не падаем
    # с первого отказа.
    Write-Step 'Поднимаю TCP-туннель для медиа (bore.pub -> localhost:44444)'

    $borePort = $null
    for ($attempt = 1; $attempt -le 4 -and -not $borePort; $attempt++) {
        if ($attempt -gt 1) {
            Write-Warn2 "Попытка $attempt из 4..."
            Start-Sleep -Seconds 3
        }
        Remove-Item $BoreLogOut, $BoreLogErr -ErrorAction SilentlyContinue

        $boreProcess = Start-Process -FilePath $bore `
            -ArgumentList @('local', '44444', '--to', 'bore.pub') `
            -RedirectStandardOutput $BoreLogOut -RedirectStandardError $BoreLogErr `
            -WindowStyle Hidden -PassThru

        for ($i = 0; $i -lt 30 -and -not $borePort; $i++) {
            Start-Sleep -Milliseconds 500
            $text = @()
            foreach ($log in @($BoreLogOut, $BoreLogErr)) {
                if (Test-Path $log) { $text += Get-Content $log -ErrorAction SilentlyContinue }
            }
            $match = $text | Select-String -Pattern 'listening at bore\.pub:(\d+)' | Select-Object -Last 1
            if ($match) { $borePort = $match.Matches[0].Groups[1].Value; break }
            # Отказ виден сразу по смерти процесса — не ждём все 15 секунд.
            if ($boreProcess.HasExited) { break }
        }

        if (-not $borePort) {
            $why = @()
            foreach ($log in @($BoreLogOut, $BoreLogErr)) {
                if (Test-Path $log) { $why += Get-Content $log -ErrorAction SilentlyContinue }
            }
            $reason = ($why | Where-Object { $_ -match 'Error|error' } | Select-Object -First 1)
            Write-Warn2 ("bore не поднялся: " + $(if ($reason) { $reason } else { 'нет ответа за 15 секунд' }))
            if (-not $boreProcess.HasExited) { Stop-Process -Id $boreProcess.Id -Force -ErrorAction SilentlyContinue }
            $boreProcess = $null
        }
    }
    if (-not $borePort) {
        throw "bore.pub не отвечает после 4 попыток — похоже, публичный релей сейчас лежит. Логи: $BoreLogErr"
    }

    # mediasoup кладёт в ICE-кандидаты адрес как есть — hostname он не резолвит.
    $boreIp = [System.Net.Dns]::GetHostAddresses('bore.pub') |
        Where-Object { $_.AddressFamily -eq 'InterNetwork' } |
        Select-Object -First 1 -ExpandProperty IPAddressToString
    if (-not $boreIp) { throw 'Не удалось резолвить bore.pub в IPv4' }
    Write-Ok "медиа: $boreIp`:$borePort (TCP)"

    # ─── Переключаем SFU ────────────────────────────────────────────────────
    Write-Step 'Переключаю SFU в TCP-режим'
    $envValues = @{
        'WEBRTC_ANNOUNCED_IP'   = $boreIp
        'WEBRTC_ANNOUNCED_PORT' = $borePort
        'TCP_TUNNEL_MODE'       = 'true'
        # Пусто = не анонсировать WebTransport: :4433 наружу не выставлен,
        # и гость впустую ждал бы таймаут QUIC на своём же localhost.
        'CONFERENCE_WT_URL'     = ''
    }
    if ($WithTurn) {
        $envValues['TURN_URLS'] = 'turn:openrelay.metered.ca:80,turn:openrelay.metered.ca:443,turn:openrelay.metered.ca:443?transport=tcp'
        $envValues['TURN_USERNAME'] = 'openrelayproject'
        $envValues['TURN_CREDENTIAL'] = 'openrelayproject'
    }
    $envTouched = $true
    Set-EnvBlock -Values $envValues
    Update-Containers -Reason 'адрес туннеля'

    $announced = (& docker compose @Compose logs sfu --tail 40 | Select-String 'announced as' | Select-Object -Last 1)
    if ($announced) { Write-Ok $announced.Line.Trim() }

    # ─── Гостевая учётка ────────────────────────────────────────────────────
    $guestLines = @()
    if ($GuestEmail) {
        Write-Step "Завожу учётку для гостя: $GuestEmail"
        # 2>&1 на нативной команде в PS 5.1 заворачивает КАЖДУЮ строку stderr в
        # ErrorRecord, а при $ErrorActionPreference='Stop' первая же такая
        # строка валит скрипт. Django пишет в stderr безобидное «System check
        # identified some issues» (два W342 в apps.mail) — и на нём терялся
        # весь сеанс, уже после того как учётка была заведена. Гасим Stop
        # только внутри дочерней области видимости, чтобы не трогать остальное.
        $created = & {
            $ErrorActionPreference = 'Continue'
            & docker compose @Compose exec -T backend-web `
                python manage.py create_user --email $GuestEmail --name 'Гость' --reset-if-exists 2>&1
        }
        $guestLines = $created | ForEach-Object { $_.ToString() } | Select-String 'логин:|пароль:'
        if ($guestLines) { $guestLines | ForEach-Object { Write-Ok $_.Line.Trim() } }
        else { Write-Warn2 'Не удалось разобрать вывод create_user — посмотрите вручную' }
    }

    # ─── Сигналинг ──────────────────────────────────────────────────────────
    Write-Step 'Поднимаю Cloudflare Tunnel на Vite (:3000)'
    Remove-Item $CfLogOut, $CfLogErr -ErrorAction SilentlyContinue

    $cfProcess = Start-Process -FilePath $cloudflared `
        -ArgumentList @('tunnel', '--no-autoupdate', '--url', 'http://localhost:3000') `
        -RedirectStandardOutput $CfLogOut -RedirectStandardError $CfLogErr `
        -WindowStyle Hidden -PassThru

    $publicUrl = $null
    for ($i = 0; $i -lt 60 -and -not $publicUrl; $i++) {
        Start-Sleep -Milliseconds 500
        $text = @()
        foreach ($log in @($CfLogOut, $CfLogErr)) {
            if (Test-Path $log) { $text += Get-Content $log -ErrorAction SilentlyContinue }
        }
        $match = $text | Select-String -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1
        if ($match) { $publicUrl = $match.Matches[0].Value }
    }
    if (-not $publicUrl) { throw "cloudflared не отдал URL за 30 секунд. Логи: $CfLogErr" }

    $publicHost = ([System.Uri]$publicUrl).Host

    # ─── Итог ───────────────────────────────────────────────────────────────
    Write-Host ''
    Write-Host '════════════════════════════════════════════════════════════' -ForegroundColor Green
    Write-Host "  Ссылка для гостя: $publicUrl" -ForegroundColor Green
    Write-Host '════════════════════════════════════════════════════════════' -ForegroundColor Green
    if ($guestLines) {
        Write-Host '  Данные для входа:' -ForegroundColor Green
        $guestLines | ForEach-Object { Write-Host "   $($_.Line.Trim())" -ForegroundColor Green }
    }
    Write-Host ''
    Write-Host "  Медиа идёт по TCP через $boreIp`:$borePort — задержка выше обычной."
    Write-Host '  HMR через туннель работать не будет: если нужен, перезапустите Vite так —'
    Write-Host "    `$env:VITE_TUNNEL_PUBLIC_HOST='$publicHost'; npm run dev" -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  Наружу открыт ВЕСЬ стенд, включая /django-admin.' -ForegroundColor Yellow
    Write-Host '  Смените пароль admin перед сеансом и погасите туннель после проверки.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Ctrl+C — остановить туннели и вернуть стенд в локальный режим.'

    while ($true) {
        Start-Sleep -Seconds 5
        if ($boreProcess.HasExited) { throw 'bore завершился — медиа-туннель потерян' }
        if ($cfProcess.HasExited)   { throw 'cloudflared завершился — ссылка больше не работает' }
    }
}
finally {
    foreach ($proc in @($boreProcess, $cfProcess)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if ($envTouched) {
        Write-Step 'Останавливаю туннели и возвращаю локальные настройки'
        Restore-Env
        try { Update-Containers -Reason 'откат к локальному режиму' } catch { Write-Warn2 $_.Exception.Message }
        Write-Ok 'Готово: стенд снова слушает только localhost'
    }
}
