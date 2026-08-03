import { defineConfig, loadEnv, type PreviewServer, type ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import fs from "fs";
import type { IncomingMessage, ServerResponse } from "http";
import { visualizer } from "rollup-plugin-visualizer";
import viteCompression from "vite-plugin-compression";
import compression from "compression";
import { ViteImageOptimizer } from "vite-plugin-image-optimizer";

function isEnvFalse(value: string | undefined) {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return normalized === "false" || normalized === "0" || normalized === "off" || normalized === "no";
}

function sendJson(res: ServerResponse, statusCode: number, body: Record<string, unknown>) {
  if (res.headersSent) return;
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

function rewriteApiPrefix(from: RegExp, to: string) {
  return (requestPath: string) => requestPath.replace(from, to);
}

function mediaLegacyGuardPlugin() {
  const middleware = (req: IncomingMessage, res: ServerResponse, next: (err?: unknown) => void) => {
    const url = req.url || "";
    if (url.startsWith("/media/")) {
      sendJson(res, 410, {
        detail: "Legacy /media/ paths are no longer served by the SPA gateway.",
        use: "/api/media/v1/files/",
      });
      return;
    }
    next();
  };

  return {
    name: "legacy-media-route-guard",
    configureServer(server: ViteDevServer) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server: PreviewServer) {
      server.middlewares.use(middleware);
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const enableDevCompression = env.VITE_DEV_COMPRESSION === "true";

  // HTTPS in dev is opt-in via VITE_DEV_HTTPS=true. Default: plain HTTP on :3000
  // (matches the current docker-compose.dev.yml setup and avoids cert headaches).
  const httpsEnabledByEnv = (env.VITE_DEV_HTTPS || "").trim().toLowerCase() === "true";
  const _certCandidates = httpsEnabledByEnv ? [
    { cert: path.resolve(__dirname, "..", "infra", "certs", "cert.pem"), key: path.resolve(__dirname, "..", "infra", "certs", "key.pem") },
    { cert: path.resolve(process.cwd(), "infra", "certs", "cert.pem"), key: path.resolve(process.cwd(), "infra", "certs", "key.pem") },
    { cert: path.resolve(process.cwd(), "..", "infra", "certs", "cert.pem"), key: path.resolve(process.cwd(), "..", "infra", "certs", "key.pem") },
  ] : [];
  const _found = _certCandidates.find(p => fs.existsSync(p.cert) && fs.existsSync(p.key));
  const httpsConfig = (httpsEnabledByEnv && _found)
    ? { cert: fs.readFileSync(_found.cert), key: fs.readFileSync(_found.key) }
    : undefined;
  console.log("[vite] HTTPS:", httpsConfig ? `enabled (${_found!.cert})` : "disabled (HTTP on :3000)");

  const isHttps = !!httpsConfig;
  // NOTE:
  // 0.0.0.0 is valid as a server bind address, but not as an outbound proxy target.
  // Use loopback defaults so /api and /ws proxies work reliably in local/LAN dev.
  //
  // Миграция FastAPI → Django (фаза 11): девять микросервисов схлопнуты в ОДИН
  // Django-backend. Имена *ServiceTarget сохранены (правила proxy ниже их
  // используют), но все указывают на единый backend; переопределяется одним
  // VITE_BACKEND_TARGET. WS (messenger socket.io) — тот же backend (ASGI).
  const backendTarget = env.VITE_BACKEND_TARGET || "http://127.0.0.1:8000";
  const hrServiceTarget = backendTarget;
  const tasksServiceTarget = backendTarget;
  const userServiceTarget = backendTarget;
  const messengerServiceTarget = backendTarget;
  const mediaServiceTarget = backendTarget;
  const emailServiceTarget = backendTarget;
  const cmsServiceTarget = backendTarget;
  const adminServiceTarget = backendTarget;
  const requestsServiceTarget = backendTarget;
  const contractsServiceTarget = backendTarget;
  const signoffServiceTarget = backendTarget;
  const adminJsTarget = backendTarget;
  // SSE-стрим одобрений (/api/requests/v1/stream) — async-вью, требует ASGI:
  // WSGI (runserver/gunicorn) его не стримит. В dev шлём на отдельный ASGI-процесс
  // (backend-asgi), как это делает прод-nginx. Переопределяется VITE_ASGI_TARGET.
  const asgiTarget = env.VITE_ASGI_TARGET || "http://127.0.0.1:8001";
  // Grafana's HOST port is 3001 (container 3000 is taken by Vite itself);
  // 3100 is Loki — proxying there breaks /grafana with a 404.
  const grafanaTarget = env.VITE_GRAFANA_TARGET || "http://127.0.0.1:3001";
  const prometheusTarget = env.VITE_PROMETHEUS_TARGET || "http://127.0.0.1:9090";
  // Keep SFU upstream plain WS by default (common for local/tunnel mode where TLS
  // is terminated at reverse proxy edge). If your SFU listens with TLS locally,
  // override via VITE_SFU_WS_TARGET=wss://127.0.0.1:4443.
  const sfuWsTarget = env.VITE_SFU_WS_TARGET || "ws://127.0.0.1:4443";
  // Socket.IO мессенджера смонтирован на ASGI-процессе (htqweb/asgi.py,
  // socketio_path="ws/messenger/socket.io") — :8000 это gunicorn/WSGI, там
  // этого маршрута нет и handshake отдаёт 404. Шлём на тот же ASGI-порт, что
  // и SSE выше (так же, как прод-nginx: upstream backend_asgi для /ws/).
  const messengerWsTarget = env.VITE_MESSENGER_WS_TARGET || "ws://127.0.0.1:8001";
  const disableHmr = env.VITE_DISABLE_HMR === "true";
  const tunnelPublicHost = String(env.VITE_TUNNEL_PUBLIC_HOST || "").trim();
  const hmrConfig = disableHmr
    ? false
    : tunnelPublicHost
      ? {
          overlay: false,
          host: tunnelPublicHost,
          protocol: "wss",
          clientPort: 443,
        }
      : {
          overlay: false,
        };
  if (isHttps) {
    console.log("[vite] HTTPS enabled via VITE_DEV_HTTPS=true — LAN devices can access via https://<IP>:3000");
  } else {
    console.log("[vite] HTTP mode on :3000 (set VITE_DEV_HTTPS=true + infra/certs/ to enable TLS)");
  }
  console.log(`[vite] User service proxy target: ${userServiceTarget}`);
  console.log(`[vite] SFU WS proxy target: ${sfuWsTarget}`);
  if (disableHmr) {
    console.log("[vite] HMR disabled via VITE_DISABLE_HMR=true");
  } else if (tunnelPublicHost) {
    console.log(`[vite] HMR pinned to tunnel host: wss://${tunnelPublicHost}:443`);
  }

  const buildProxyConfig = () => ({
    // ─── WebSockets ─────────────────────────────────────────────────────────
    "/ws/sfu": {
      target: sfuWsTarget,
      ws: true,
      changeOrigin: true,
      secure: false, // Allow self-signed SFU cert
      timeout: 15000,
      proxyTimeout: 15000,
    },
    "/ws/sfu/": {
      target: sfuWsTarget,
      ws: true,
      changeOrigin: true,
      secure: false,
      timeout: 15000,
      proxyTimeout: 15000,
    },
    // Messenger socket.io (and any other /ws/* — messenger is the default home
    // for WebSocket traffic after Django removal).
    "^/ws(?!/sfu/?).*": {
      target: messengerWsTarget,
      ws: true,
      changeOrigin: true,
    },
    // Temporary compatibility for cached bundles and old bookmarks.
    "^/api/token(?=/|\\?|$)": {
      target: userServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/token(?=\/|\?|$)/, "/api/users/v1/token"),
    },
    "^/api/register(?=/|\\?|$)": {
      target: userServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/register(?=\/|\?|$)/, "/api/users/v1/register"),
    },
    "^/api/pending-registrations(?=/|\\?|$)": {
      target: userServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(
        /^\/api\/pending-registrations(?=\/|\?|$)/,
        "/api/users/v1/pending-registrations"
      ),
    },
    "^/api/v1/profile(?=/|\\?|$)": {
      target: userServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/v1\/profile(?=\/|\?|$)/, "/api/users/v1/profile"),
    },
    "^/api/v1/admin/users(?=/|\\?|$)": {
      target: userServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/v1\/admin\/users(?=\/|\?|$)/, "/api/users/v1/admin/users"),
    },
    "^/api/users/(?!v1(?:/|\\?|$))": {
      target: userServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/users\//, "/api/users/v1/"),
    },
    "^/api/news(?=/|\\?|$)": {
      target: cmsServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/news(?=\/|\?|$)/, "/api/cms/v1/news"),
    },
    "^/api/contact-requests(?=/|\\?|$)": {
      target: cmsServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/contact-requests(?=\/|\?|$)/, "/api/cms/v1/contact-requests"),
    },
    "^/api/v1/contact-requests(?=/|\\?|$)": {
      target: cmsServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/v1\/contact-requests(?=\/|\?|$)/, "/api/cms/v1/contact-requests"),
    },
    "^/api/calendar-events(?=/|\\?|$)": {
      target: tasksServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/calendar-events(?=\/|\?|$)/, "/api/tasks/v1/calendar"),
    },
    "^/api/calendar-timeline(?=/|\\?|$)": {
      target: tasksServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(
        /^\/api\/calendar-timeline(?=\/|\?|$)/,
        "/api/tasks/v1/calendar/timeline"
      ),
    },
    "^/api/hr/(?!v1(?:/|\\?|$))": {
      target: hrServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/hr\//, "/api/hr/v1/"),
    },
    "^/api/tasks/(?!v1(?:/|\\?|$))": {
      target: tasksServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/tasks\//, "/api/tasks/v1/"),
    },
    "^/api/cms/(?!v1(?:/|\\?|$))": {
      target: cmsServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/cms\//, "/api/cms/v1/"),
    },
    "^/api/email/(?!v1(?:/|\\?|$))": {
      target: emailServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/email\//, "/api/email/v1/"),
    },
    "^/api/messenger/(?!v1(?:/|\\?|$))": {
      target: messengerServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/messenger\//, "/api/messenger/v1/"),
    },
    "^/api/media/v1/(?!files(?:/|\\?|$))": {
      target: mediaServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/media\/v1\//, "/api/media/v1/files/"),
    },
    "^/api/media/(?!v1(?:/|\\?|$))": {
      target: mediaServiceTarget,
      changeOrigin: true,
      rewrite: rewriteApiPrefix(/^\/api\/media\//, "/api/media/v1/files/"),
    },
    // ─── Per-service REST ───────────────────────────────────────────────────
    // One rule per service. All backend routers expose their endpoints under
    // /api/<service>/v1/* — see services/<service>/app/api/v1/*.py.
    "^/api/users/": {
      target: userServiceTarget,
      changeOrigin: true,
    },
    "^/api/hr/": {
      target: hrServiceTarget,
      changeOrigin: true,
    },
    "^/api/tasks/": {
      target: tasksServiceTarget,
      changeOrigin: true,
    },
    "^/api/cms/": {
      target: cmsServiceTarget,
      changeOrigin: true,
    },
    "^/api/media/": {
      target: mediaServiceTarget,
      changeOrigin: true,
    },
    "^/api/messenger/": {
      target: messengerServiceTarget,
      changeOrigin: true,
    },
    "^/api/email/": {
      target: emailServiceTarget,
      changeOrigin: true,
    },
    // Бюджеты / реестр контрагентов / договоры (apps.contracts). Легаси-путей
    // без /v1/ у этого домена нет — он появился уже после обратной миграции,
    // поэтому rewrite-правила выше ему не нужны, только эта строка. Без неё
    // запрос дошёл бы до catch-all `^/api/` ниже и получил 404 от прокси.
    "^/api/contracts/": {
      target: contractsServiceTarget,
      changeOrigin: true,
    },
    // Согласование (apps.signoff) — универсальный движок маршрутов
    // согласования. НЕ путать с /api/requests/ (apps.approvals): тот домен
    // про конструктор динамических форм. Как и у contracts, легаси-путей без
    // /v1/ здесь нет, поэтому одной строки достаточно.
    "^/api/signoff/": {
      target: signoffServiceTarget,
      changeOrigin: true,
    },
    "^/api/requests/v1/stream": {
      target: asgiTarget,
      changeOrigin: true,
    },
    "^/api/requests/": {
      target: requestsServiceTarget,
      changeOrigin: true,
    },
    "^/api/admin/": {
      target: adminServiceTarget,
      changeOrigin: true,
    },
    // apps.core: реестр вкл/выкл сервисов (/api/core/v1/services/), который
    // читает hooks/useServiceStatus.ts. Правила для него тут не было ВООБЩЕ —
    // домен появился уже в Django-монолите, а таблица ниже осталась от эпохи
    // микросервисов, где такого сервиса не существовало. В итоге запрос падал
    // в catch-all `^/api/` и получал синтетический 404 от самого Vite, не
    // доходя до бэкенда (в проде nginx отдаёт его через общий `location
    // /api/`, поэтому там всё работало и расхождение не замечали).
    "^/api/core/": {
      target: backendTarget,
      changeOrigin: true,
    },
    "^/api/": {
      target: userServiceTarget,
      changeOrigin: true,
      bypass(req: IncomingMessage, res: ServerResponse) {
        sendJson(res, 404, {
          detail: "API endpoint not found",
          path: req.url || "/api/",
        });
        return false;
      },
    },
    // ─── Панель БД ──────────────────────────────────────────────────────────
    // Сознательно НЕ на /admin/ — этот неймспейс принадлежит SPA
    // (/admin/users, /admin/chats, /admin/registrations — React-страницы).
    //
    // Было /sqladmin (панель снесённого admin-сервиса) и /mongo-admin
    // (AdminJS на :3300 поверх MongoDB) — оба сервиса удалены при переходе на
    // монолит, оба правила проксировали в никуда. В монолите роль панели БД
    // играет родная админка Django.
    "/django-admin": {
      target: adminServiceTarget,
      // ЕДИНСТВЕННОЕ правило с changeOrigin: false — и это не небрежность.
      // Админка, в отличие от /api/ (JWT + ApiCsrfExemptMiddleware), работает
      // на сессии и живом Django-CSRF. changeOrigin переписывает Host на
      // backend-web:8000, а браузер шлёт Origin: http://localhost:3000 —
      // CsrfViewMiddleware сверяет их и отдаёт 403 «Origin checking failed»
      // на форме входа. Пропуская Host как есть, мы даём Django совпадение
      // (ALLOWED_HOSTS=["*"]) и не заводим CSRF_TRUSTED_ORIGINS со списком
      // хостов, который пришлось бы дописывать под каждый LAN-адрес.
      changeOrigin: false,
    },
    // Статика самой админки (STATIC_URL="static/"): её CSS/JS/иконки плюс
    // фирменная тема backend/static/admin/htqweb.css. Без этого правила
    // /static/... проваливался в SPA-fallback Vite и возвращал index.html с
    // Content-Type: text/html — страница открывалась, но полностью без стилей.
    // Неймспейс /static свободен: у фронта своя статика лежит в /assets,
    // /fonts, /images, /locales (см. frontend/public).
    "/static": {
      target: adminServiceTarget,
      changeOrigin: true,
    },
    // ─── Monitoring (Grafana + Prometheus) ─────────────────────────────────
    "/grafana": {
      target: grafanaTarget,
      changeOrigin: true,
      // SSO: Grafana's [auth.jwt] reads X-JWT-Assertion on every request.
      // The SPA can't attach headers to its own asset/XHR traffic, so the
      // frontend drops the platform JWT into the `htq_access` cookie
      // (path=/grafana) and the edge copies it into the header here.
      // nginx does the same in prod (infra/nginx/default.conf).
      configure: (proxy: any) => {
        proxy.on("proxyReq", (proxyReq: any, req: IncomingMessage) => {
          const match = /(?:^|;\s*)htq_access=([^;]+)/.exec(req.headers.cookie ?? "");
          if (match) proxyReq.setHeader("X-JWT-Assertion", decodeURIComponent(match[1]));
        });
      },
    },
    "/prometheus": {
      target: prometheusTarget,
      changeOrigin: true,
    },
  });

  return {
  server: {
    host: '0.0.0.0',
    port: 3000,
    // Load HTTPS if certs/ exist — required for Secure Context on LAN IPs.
    ...(httpsConfig ? { https: httpsConfig } : {}),
    // Tunnel remote testing (for example ngrok):
    // 1) run frontend: `npm run dev` (3000)
    // 2) run SFU: `npm run dev` inside `sfu/` (4443)
    // 3) tunnel MUST forward app origin to Vite only (3000)
    //    then Vite proxy keeps `/ws/sfu` pinned to 4443.
    //    If tunnel supports route rules, keep `/ws/sfu*` on the same origin.
    allowedHosts: true,
    cors: true,
    hmr: hmrConfig,
    proxy: buildProxyConfig(),
  },
  preview: {
    host: true,
    port: 3000,
    ...(httpsConfig ? { https: httpsConfig } : {}),
    allowedHosts: true,
    cors: true,
    proxy: buildProxyConfig(),
  },
  plugins: [
    mediaLegacyGuardPlugin(),
    // Optional compression for remote dev testing (off by default because it slows local HMR responses).
    ...(enableDevCompression
      ? [{
          name: "dev-server-compression",
          configureServer(server) {
            server.middlewares.use(
              compression({
                level: 5,
                threshold: 1024,
              }) as any
            );
          },
        }]
      : []),
    react({
      babel: {
        plugins: [["babel-plugin-react-compiler", {}]],
      },
    }),
    ViteImageOptimizer({
      webp: {
        quality: 80,
      },
      avif: {
        quality: 80,
      },
      png: {
        quality: 80,
      },
      jpeg: {
        quality: 80,
      },
    }),
    // Bundle analysis — generates bundle-report.html after build
    visualizer({
      filename: "bundle-report.html",
      gzipSize: true,
      brotliSize: true,
    }),
    // Brotli pre-compression (level 11) for CI/CD static serving
    viteCompression({
      algorithm: "brotliCompress",
      ext: ".br",
      threshold: 1024,
      compressionOptions: { level: 11 },
      filter: /\.(js|css|json|svg|html)$/i,
      deleteOriginFile: false,
    }),
    // Gzip fallback for clients without brotli support
    viteCompression({
      algorithm: "gzip",
      ext: ".gz",
      threshold: 1024,
      compressionOptions: { level: 9 },
      filter: /\.(js|css|json|svg|html)$/i,
      deleteOriginFile: false,
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      // Skip lucide-react barrel re-export in dev — faster HMR rebuilds
      "lucide-react": path.resolve(__dirname, "node_modules/lucide-react/dist/esm/lucide-react.js"),
    },
  },
  build: {
    target: "es2020", // Drop legacy polyfills (async/await, optional chaining, etc.)
    chunkSizeWarningLimit: 500, // KB — warn if any chunk exceeds 500 KB
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // React core
          if (
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react/")
          ) {
            return "vendor-react";
          }
          // Router stays separate so public landing page doesn't have to wait on all route internals
          if (id.includes("node_modules/react-router-dom")) {
            return "vendor-router";
          }
          // Radix slot is used in base button and should not pull the whole Radix stack
          if (id.includes("node_modules/@radix-ui/react-slot")) {
            return "vendor-radix-slot";
          }
          // Remaining Radix primitives (dialogs, popovers, etc.) are typically lazy-route dependent
          if (id.includes("node_modules/@radix-ui")) {
            return "vendor-radix";
          }
          if (id.includes("node_modules/cmdk")) {
            return "vendor-cmdk";
          }
          // Utility stack used by many UI components; keep it out of feature chunks.
          if (
            id.includes("node_modules/clsx") ||
            id.includes("node_modules/class-variance-authority") ||
            id.includes("node_modules/tailwind-merge")
          ) {
            return "vendor-utils";
          }
          // recharts + D3 — heavy, loaded only with HRReports lazy chunk
          if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) {
            return "vendor-recharts";
          }
          if (id.includes("node_modules/@tanstack/react-query")) {
            return "vendor-query";
          }
          if (id.includes("node_modules/i18next") || id.includes("node_modules/react-i18next")) {
            return "vendor-i18n";
          }
          if (id.includes("node_modules/i18next-browser-languagedetector")) {
            return "vendor-i18n-detector";
          }
          if (id.includes("node_modules/i18next-http-backend")) {
            return "vendor-i18n-backend";
          }
          if (id.includes("node_modules/axios")) {
            return "vendor-axios";
          }
          if (id.includes("node_modules/date-fns")) {
            return "vendor-date-fns";
          }
          // Forms: zod + react-hook-form
          if (
            id.includes("node_modules/zod") ||
            id.includes("node_modules/react-hook-form") ||
            id.includes("node_modules/@hookform")
          ) {
            return "vendor-forms";
          }
          // Icons — large lib, cache separately so app code changes don't bust it
          if (id.includes("node_modules/lucide-react")) {
            return "vendor-icons";
          }
        },
      },
    },
  },
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-dom/client",
      "react-router-dom",
      "@tanstack/react-query",
      "axios",

      "react-hook-form",
      "@hookform/resolvers/zod",
      "zod",
      "clsx",
      "tailwind-merge",
      "react-i18next",
      "i18next",
      "i18next-browser-languagedetector",
      "i18next-http-backend",
      "sonner",
      "date-fns",
      "embla-carousel-react",
      "class-variance-authority",
      "cmdk",
      "input-otp",
      "vaul",

      // Pre-bundle lucide-react — eliminates 4 MB waterfall in dev
      // (esbuild bundles all icons into one ~156 KB file;
      //  production tree-shaking still produces a small vendor-icons chunk)
      "lucide-react",

      // Theme & UI utilities
      "next-themes",
      "react-day-picker",
      "@hello-pangea/dnd",
      "react-resizable-panels",

      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
      "@radix-ui/react-tooltip",
      "@radix-ui/react-select",
      "@radix-ui/react-tabs",
      "@radix-ui/react-popover",
      "@radix-ui/react-checkbox",
      "@radix-ui/react-label",
      "@radix-ui/react-slot",
      "@radix-ui/react-switch",
      "@radix-ui/react-toast",
      "@radix-ui/react-avatar",
      "@radix-ui/react-scroll-area",
      "@radix-ui/react-separator",
      "@radix-ui/react-accordion",
      "@radix-ui/react-alert-dialog",
      "@radix-ui/react-navigation-menu",
      "@radix-ui/react-radio-group",
      "@radix-ui/react-progress",
      "@radix-ui/react-toggle",
      "@radix-ui/react-toggle-group",
      "@radix-ui/react-collapsible",
      "@radix-ui/react-context-menu",
      "@radix-ui/react-hover-card",
      "@radix-ui/react-menubar",
      "@radix-ui/react-slider",
      "@radix-ui/react-aspect-ratio",
    ],
  }
  };
});
