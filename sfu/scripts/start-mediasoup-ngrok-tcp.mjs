#!/usr/bin/env node

import { lookup } from 'node:dns/promises';
import { spawn } from 'node:child_process';
import { copyFile, mkdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const NGROK_API_URL =
  process.env.NGROK_API_URL ?? 'http://127.0.0.1:4040/api/tunnels';
const NGROK_LOCAL_TCP_PORT = Number.parseInt(
  process.env.NGROK_LOCAL_TCP_PORT ?? '44444',
  10
);
const NGROK_WAIT_TIMEOUT_MS = Number.parseInt(
  process.env.NGROK_WAIT_TIMEOUT_MS ?? '45000',
  10
);
const SFU_NPM_SCRIPT = process.env.SFU_NPM_SCRIPT ?? 'start';
const SFU_CWD = process.env.SFU_CWD ?? process.cwd();
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const sfuRootDir = path.resolve(scriptDir, '..');
const MEDIASOUP_WORKER_SOURCE = path.resolve(
  sfuRootDir,
  'node_modules',
  'mediasoup',
  'worker',
  'out',
  'Release',
  'mediasoup-worker.exe'
);
const MEDIASOUP_WORKER_RUNTIME_DIR = path.resolve(sfuRootDir, '.runtime');
const MEDIASOUP_WORKER_RUNTIME_BIN = path.resolve(
  MEDIASOUP_WORKER_RUNTIME_DIR,
  'mediasoup-worker.exe'
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function pickTcpTunnel(payload, targetPort) {
  const tunnels = Array.isArray(payload?.tunnels) ? payload.tunnels : [];
  const tcpTunnels = tunnels.filter((tunnel) =>
    String(tunnel?.public_url || '').startsWith('tcp://')
  );

  if (tcpTunnels.length === 0) {
    throw new Error('No tcp tunnel in ngrok API response');
  }

  const exact = tcpTunnels.find((tunnel) => {
    const addr = String(tunnel?.config?.addr || '');
    return addr === String(targetPort) || addr.endsWith(`:${targetPort}`);
  });

  return exact ?? tcpTunnels[0];
}

function parseNgrokPublicUrl(publicUrl) {
  const url = new URL(publicUrl);
  if (url.protocol !== 'tcp:') {
    throw new Error(`Expected tcp:// public_url, got: ${publicUrl}`);
  }

  const host = url.hostname;
  const port = Number.parseInt(url.port, 10);

  if (!host || !Number.isInteger(port) || port <= 0) {
    throw new Error(`Invalid tcp public_url: ${publicUrl}`);
  }

  return { host, port };
}

async function fetchNgrokTunnels() {
  const response = await fetch(NGROK_API_URL, {
    headers: { Accept: 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`ngrok API ${response.status} ${response.statusText}`);
  }

  return response.json();
}

async function waitForTunnel() {
  const deadline = Date.now() + NGROK_WAIT_TIMEOUT_MS;
  let lastError = null;

  while (Date.now() < deadline) {
    try {
      const payload = await fetchNgrokTunnels();
      return pickTcpTunnel(payload, NGROK_LOCAL_TCP_PORT);
    } catch (error) {
      lastError = error;
      await sleep(1000);
    }
  }

  throw new Error(
    `Timed out waiting for ngrok tunnel (${NGROK_WAIT_TIMEOUT_MS}ms). ` +
      `Last error: ${String(lastError)}`
  );
}

async function main() {
  const tunnel = await waitForTunnel();
  const publicUrl = String(tunnel.public_url);
  const { host, port } = parseNgrokPublicUrl(publicUrl);
  const { address: resolvedIp } = await lookup(host, { family: 4 });

  const env = {
    ...process.env,
    WEBRTC_ENABLE_UDP: 'false',
    WEBRTC_ENABLE_TCP: 'true',
    WEBRTC_PREFER_UDP: 'false',
    WEBRTC_PREFER_TCP: 'true',
    WEBRTC_EXPOSE_INTERNAL_IP: 'false',
    WEBRTC_LISTEN_IPS: '0.0.0.0',
    WEBRTC_ANNOUNCED_IP: resolvedIp,
    WEBRTC_SERVER_PORT: String(NGROK_LOCAL_TCP_PORT),
    NGROK_PUBLIC_URL: publicUrl,
    NGROK_PUBLIC_HOST: host,
    NGROK_PUBLIC_IP: resolvedIp,
    NGROK_PUBLIC_PORT: String(port),
  };

  if (process.platform === 'win32' && !String(env.MEDIASOUP_WORKER_BIN || '').trim()) {
    await mkdir(MEDIASOUP_WORKER_RUNTIME_DIR, { recursive: true });

    let shouldCopyWorker = true;
    try {
      const [srcStat, dstStat] = await Promise.all([
        stat(MEDIASOUP_WORKER_SOURCE),
        stat(MEDIASOUP_WORKER_RUNTIME_BIN),
      ]);
      shouldCopyWorker = srcStat.size !== dstStat.size;
    } catch {
      shouldCopyWorker = true;
    }

    if (shouldCopyWorker) {
      await copyFile(MEDIASOUP_WORKER_SOURCE, MEDIASOUP_WORKER_RUNTIME_BIN);
    }

    env.MEDIASOUP_WORKER_BIN = MEDIASOUP_WORKER_RUNTIME_BIN;
  }

  console.log(
    `[ngrok-wrap] tunnel=${publicUrl} resolved=${resolvedIp}:${port} ` +
      `localPort=${NGROK_LOCAL_TCP_PORT} npmScript=${SFU_NPM_SCRIPT}`
  );
  if (String(env.MEDIASOUP_WORKER_BIN || '').trim()) {
    console.log(`[ngrok-wrap] MEDIASOUP_WORKER_BIN=${env.MEDIASOUP_WORKER_BIN}`);
  }

  const child =
    process.platform === 'win32'
      ? spawn('cmd.exe', ['/d', '/s', '/c', `npm run ${SFU_NPM_SCRIPT}`], {
          cwd: SFU_CWD,
          env,
          stdio: 'inherit',
        })
      : spawn('npm', ['run', SFU_NPM_SCRIPT], {
          cwd: SFU_CWD,
          env,
          stdio: 'inherit',
        });

  child.on('error', (error) => {
    console.error('[ngrok-wrap] Failed to spawn SFU process:', error);
    process.exit(1);
  });

  child.on('exit', (code) => process.exit(code ?? 1));
}

main().catch((error) => {
  console.error('[ngrok-wrap] Fatal:', error);
  process.exit(1);
});
