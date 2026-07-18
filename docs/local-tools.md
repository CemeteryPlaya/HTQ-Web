# Local development tools

This project relies on a few local CLIs for tunneling and Windows-specific dev workflows. They are **not vendored** in the repo — install them per-machine and make sure they are on `PATH`.

## Required tools

| Tool | Purpose | Used by |
|---|---|---|
| `ngrok` | HTTPS tunnel for the dev server / SFU signaling | `scripts/setup-firewall.ps1` (LAN-only flow), manual exposure |
| `bore` | Raw TCP tunnel (bore.pub) for Mediasoup media on `:44444` | `scripts/start-sfu-tunnel.ps1` |
| `cloudflared` | Cloudflare Tunnel — alternative to ngrok | manual |
| `nginx` | Local reverse proxy (alternative to running nginx in Docker) | `nginx/instatunnel-*.conf` (manual) |

## Installation

### Windows (winget — preferred)

```powershell
winget install ngrok.ngrok
winget install Cloudflare.cloudflared
winget install nginx.nginx
# bore is not in winget yet — see manual section below
```

### Windows (chocolatey)

```powershell
choco install ngrok cloudflared nginx
# bore — manual
```

### macOS (Homebrew)

```bash
brew install ngrok/ngrok/ngrok
brew install cloudflared
brew install nginx
brew install bore-cli
```

### Linux (Debian/Ubuntu)

```bash
# ngrok
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
  && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list \
  && sudo apt update && sudo apt install ngrok

# cloudflared
sudo mkdir -p --mode=0755 /usr/share/keyrings \
  && curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null \
  && echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list \
  && sudo apt update && sudo apt install cloudflared

# nginx
sudo apt install nginx

# bore
cargo install bore-cli
# or download a release binary: https://github.com/ekzhang/bore/releases
```

### Manual `bore` install (Windows)

If `bore` is not on `PATH`, [scripts/start-sfu-tunnel.ps1](../scripts/start-sfu-tunnel.ps1) auto-downloads it into `%LOCALAPPDATA%\HTQWeb\tools\bore.exe` on first run. To install system-wide instead:

1. Download the AMD64 Windows zip from <https://github.com/ekzhang/bore/releases/latest>
2. Extract `bore.exe` somewhere on `PATH` (e.g. `%USERPROFILE%\bin\`)

## Configuration

- **ngrok** authtoken: `ngrok config add-authtoken <YOUR_TOKEN>`
- **cloudflared** login: `cloudflared tunnel login`

Tunnel-specific configs live in [nginx/](../nginx/) (or [infra/nginx/](../infra/nginx/) after Phase 1.2 of the FastAPI migration) and in `sfu/ngrok.tcp.yml`.
