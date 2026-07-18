# InstaTunnel + Nginx (Local Reverse Proxy on 8080)

## Goal

Expose two local services through one entrypoint (`localhost:8080`) before tunneling with InstaTunnel:

- Frontend: `127.0.0.1:3000`
- SFU WebSocket: `127.0.0.1:4443`

This works with changing tunnel domains because `server_name _;` accepts any host header.

## Nginx server block

Use the server block from:

- `infra/nginx/instatunnel-local-8080.conf`

Routing:

- `/` -> `127.0.0.1:3000`
- `/ws/sfu/` -> `127.0.0.1:4443` (TLS upstream, with trailing slash in `proxy_pass` to strip `/ws/sfu/` prefix)

WebSocket headers set:

- `Upgrade: $http_upgrade`
- `Connection: "upgrade"`

## Frontend WebSocket example (dynamic current domain)

```js
// Works for any fresh InstaTunnel domain because host is taken from current page URL.
const sfuWsUrl = `wss://${window.location.host}/ws/sfu/`;

const sfuSocket = new WebSocket(sfuWsUrl);

sfuSocket.onopen = () => console.log("SFU connected:", sfuWsUrl);
sfuSocket.onerror = (event) => console.error("SFU WebSocket error:", event);
sfuSocket.onclose = (event) => console.warn("SFU closed:", event.code, event.reason);
```

If your app is always opened via InstaTunnel HTTPS URL, `wss://` will be used automatically.

## Ubuntu commands (create config + restart Nginx)

```bash
sudo tee /etc/nginx/sites-available/instatunnel-local-8080.conf > /dev/null <<'EOF'
server {
    listen 8080;
    listen [::]:8080;
    server_name _;

    client_max_body_size 10m;

    location = /ws/sfu {
        return 308 /ws/sfu/;
    }

    location /ws/sfu/ {
        proxy_pass https://127.0.0.1:4443/;
        proxy_http_version 1.1;
        proxy_ssl_verify off;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -sfn /etc/nginx/sites-available/instatunnel-local-8080.conf /etc/nginx/sites-enabled/instatunnel-local-8080.conf
sudo nginx -t
sudo systemctl restart nginx
```

## Run InstaTunnel on 8080

```bash
instatunnel 8080
```

## Windows (PowerShell) quick start

Assumption: nginx is installed in `C:\nginx`.

1) Start local services in separate terminals:

Before starting SFU, make sure `sfu/.env` contains:

```dotenv
SIGNALING_WS_PATHS=/,/ws/sfu,/ws/sfu/
```

```powershell
# terminal 1
cd D:\HTQWeb1\frontend
npm run dev
```

```powershell
# terminal 2
cd D:\HTQWeb1\sfu
npm run dev
```

2) Start nginx on `8080` using prepared main config:

```powershell
# terminal 3
C:\nginx\nginx.exe -t -p C:\nginx\ -c D:\HTQWeb1\infra\nginx\instatunnel-windows-main.conf
C:\nginx\nginx.exe -p C:\nginx\ -c D:\HTQWeb1\infra\nginx\instatunnel-windows-main.conf
```

Reload after config changes:

```powershell
C:\nginx\nginx.exe -s reload
```

3) Start tunnel to nginx entrypoint:

```powershell
# terminal 4 (PowerShell execution policy safe)
cmd /c instatunnel 8080
```
