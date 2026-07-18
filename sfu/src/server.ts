/**
 * SFU Server Entry Point
 *
 * - Creates Mediasoup Workers
 * - Starts WSS signaling server
 * - Handles Protobuf-serialized messages
 * - Manages rooms and peer connections
 *
 * Architecture:
 *   Client ──WSS──> Server ──Protobuf──> Room Manager ──Mediasoup──> Workers
 */

import { createServer as createHttpsServer } from 'https';
import {
  createServer as createHttpServer,
  type IncomingMessage,
} from 'http';
import type { Duplex } from 'stream';
import { readFileSync, existsSync } from 'fs';
import * as net from 'net';
import { WebSocketServer, WebSocket } from 'ws';
import * as mediasoup from 'mediasoup';
import { types as mediasoupTypes } from 'mediasoup';
import { v4 as uuidv4 } from 'uuid';

import { config } from './config.js';
import { Room, ActiveSpeakerInfo } from './room.js';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

interface PeerConnection {
  peerId: string;
  ws: WebSocket;
  roomId: string | null;
  displayName: string;
  rtpCapabilities: mediasoupTypes.RtpCapabilities | null;
  sendTransportId: string | null;
  recvTransportId: string | null;
  isAlive: boolean;
  cleanedUp: boolean;
}

// Simple JSON signaling (Protobuf integration described below)
interface SignalingMessage {
  id: number;
  type?: string;
  method?: string;
  roomId?: string;
  data?: unknown;
  response?: boolean;
  ok?: boolean;
  error?: string;
}

interface QualityReportPayload {
  packetLossRate: number;
  rttMs: number;
}

// ═══════════════════════════════════════════════════════════
// Global State
// ═══════════════════════════════════════════════════════════

const workers: mediasoupTypes.Worker[] = [];
const webRtcServers: Map<mediasoupTypes.Worker, mediasoupTypes.WebRtcServer> = new Map();
const rooms: Map<string, Room> = new Map();
const peerConnections: Map<string, PeerConnection> = new Map();
const roomMembers: Map<string, Set<string>> = new Map();
let nextWorkerIdx = 0;
const WS_HEARTBEAT_INTERVAL_MS = 15_000;

function closeMediasoupResources(reason?: string): void {
  if (reason) {
    console.log(`[Server] Cleaning up mediasoup resources (${reason})...`);
  }

  for (const [worker, webRtcServer] of webRtcServers) {
    try {
      webRtcServer.close();
    } catch (error) {
      console.warn(
        `[Server] Failed to close WebRtcServer for worker ${worker.pid}:`,
        error
      );
    }
  }
  webRtcServers.clear();

  for (const worker of workers) {
    try {
      worker.close();
    } catch (error) {
      console.warn(`[Server] Failed to close worker ${worker.pid}:`, error);
    }
  }

  workers.length = 0;
  nextWorkerIdx = 0;
}

// ═══════════════════════════════════════════════════════════
// Mediasoup Workers
// ═══════════════════════════════════════════════════════════

async function createWorkers(): Promise<void> {
  const requestedWorkers = Math.max(1, config.mediasoup.numWorkers);
  let numWorkers = requestedWorkers;
  const { listenIps, webRtcServerPort } = config.mediasoup;

  // In single-port mode all workers would try to bind the same UDP/TCP port.
  // That causes EADDRINUSE on worker #2 and process startup failure.
  if (requestedWorkers > 1) {
    numWorkers = 1;
    console.warn(
      `[Server] WEBRTC_SERVER_PORT=${webRtcServerPort} is single-port mode. ` +
      `Clamping MEDIASOUP_WORKERS from ${requestedWorkers} to 1 to avoid bind conflicts. ` +
      'Set MEDIASOUP_WORKERS=1 in sfu/.env to silence this warning.'
    );
  }

  console.log(`[Server] Creating ${numWorkers} Mediasoup workers...`);

  // Use the first listenIp entry for the WebRtcServer bind address.
  const bindIp = listenIps[0]?.ip ?? '0.0.0.0';
  const announcedAddress = listenIps[0]?.announcedIp ?? undefined;

  for (let i = 0; i < numWorkers; i++) {
    const worker = await mediasoup.createWorker(
      config.mediasoup.workerSettings
    );

    worker.on('died', (error) => {
      console.error(
        `[Server] Mediasoup worker ${worker.pid} died:`,
        error
      );
      // In production: restart worker or exit process
      setTimeout(() => process.exit(1), 2000);
    });

    // ── Single-port WebRtcServer (replaces rtcMinPort/rtcMaxPort range) ──
    // Binds one or more sockets on webRtcServerPort.
    // In TCP_TUNNEL_MODE only a TCP socket is created — TCP-only tunnels cannot forward UDP,
    // so binding UDP here would produce unreachable ICE candidates in the SDP.
    let webRtcServer: mediasoupTypes.WebRtcServer;

    // Build listenInfos based on whether UDP is permitted.
    // config.mediasoup.webRtcTransport reflects TCP_TUNNEL_MODE overrides.
    const { enableUdp, enableTcp } = config.mediasoup.webRtcTransport;

    type ListenInfo = { protocol: 'udp' | 'tcp'; ip: string; announcedAddress?: string; port: number };
    const listenInfos: ListenInfo[] = [];

    if (enableUdp) {
      listenInfos.push({ protocol: 'udp', ip: bindIp, announcedAddress, port: webRtcServerPort });
    }
    if (enableTcp) {
      listenInfos.push({ protocol: 'tcp', ip: bindIp, announcedAddress, port: webRtcServerPort });
    }
    // Safety net — should never happen due to config validation, but guard anyway.
    if (listenInfos.length === 0) {
      listenInfos.push({ protocol: 'tcp', ip: bindIp, announcedAddress, port: webRtcServerPort });
      console.warn('[Server] Neither UDP nor TCP enabled — falling back to TCP-only.');
    }

    const protocolLabel = listenInfos.map((l) => l.protocol.toUpperCase()).join('+');

    if (config.tcpTunnelMode) {
      console.warn(
        `[Server] TCP_TUNNEL_MODE: WebRtcServer starting TCP-only. ` +
        `UDP disabled — tunnel has no UDP support. ` +
        `announcedAddress=${announcedAddress ?? bindIp} port=${webRtcServerPort}`
      );
    }

    try {
      webRtcServer = await worker.createWebRtcServer({ listenInfos });
    } catch (error) {
      try {
        worker.close();
      } catch (closeError) {
        console.warn(
          `[Server] Failed to close worker ${worker.pid} after bind failure:`,
          closeError
        );
      }
      throw error;
    }

    webRtcServers.set(worker, webRtcServer);
    workers.push(worker);
    console.log(
      `[Server] Worker ${i + 1}/${numWorkers} created (PID ${worker.pid}), ` +
      `WebRtcServer bound on ${bindIp}:${webRtcServerPort} (${protocolLabel}) ` +
      `announced as ${announcedAddress ?? bindIp}`
    );
  }
}

/**
 * Round-robin worker selection for load distribution.
 */
function getNextWorker(): mediasoupTypes.Worker {
  const worker = workers[nextWorkerIdx];
  nextWorkerIdx = (nextWorkerIdx + 1) % workers.length;
  return worker;
}

// ═══════════════════════════════════════════════════════════
// Room Management
// ═══════════════════════════════════════════════════════════

async function getOrCreateRoom(roomId: string): Promise<Room> {
  let room = rooms.get(roomId);
  if (room) return room;

  const worker = getNextWorker();
  const webRtcServer = webRtcServers.get(worker);
  if (!webRtcServer) {
    throw new Error(`[Server] No WebRtcServer found for worker ${worker.pid}`);
  }

  room = await Room.create(worker, webRtcServer, roomId, {
    onActiveSpeakersChanged: (speakers: ActiveSpeakerInfo[]) => {
      broadcastToRoom(roomId, {
        method: 'activeSpeakerUpdate',
        data: { speakers },
      });
    },
    onPeerJoined: (peerId: string, displayName: string) => {
      broadcastToRoom(
        roomId,
        {
          method: 'participantJoined',
          data: { peerId, displayName },
        },
        peerId
      );
    },
    onPeerLeft: (peerId: string) => {
      broadcastToRoom(roomId, {
        method: 'participantLeft',
        data: { peerId },
      });
    },
    onNewConsumerNeeded: async (
      consumingPeerId: string,
      _producerPeerId: string,
      producer: mediasoupTypes.Producer
    ) => {
      await createConsumerForPeer(
        roomId,
        consumingPeerId,
        producer.id
      );
    },
  });

  rooms.set(roomId, room);
  return room;
}

/**
 * Create a consumer for a specific peer when a new producer appears.
 */
async function createConsumerForPeer(
  roomId: string,
  consumingPeerId: string,
  producerId: string
): Promise<void> {
  const peerConn = peerConnections.get(consumingPeerId);
  if (!peerConn || !peerConn.rtpCapabilities || !peerConn.recvTransportId) {
    return;
  }

  const room = rooms.get(roomId);
  if (!room) return;

  try {
    if (room.hasConsumerForProducer(consumingPeerId, producerId)) {
      return;
    }

    const consumerData = await room.consume(
      consumingPeerId,
      peerConn.recvTransportId,
      producerId,
      peerConn.rtpCapabilities
    );

    if (!consumerData) return;

    // Send new consumer notification to the peer
    sendToPeer(consumingPeerId, {
      method: 'newConsumer',
      data: {
        consumerId: consumerData.consumerId,
        producerId: consumerData.producerId,
        kind: consumerData.kind,
        rtpParameters: consumerData.rtpParameters,
        peerId: consumerData.producerPeerId,
        displayName: consumerData.producerDisplayName,
        paused: true,
      },
    });
  } catch (err) {
    console.error(
      `[Server] Failed to create consumer for ${consumingPeerId}:`,
      err
    );
  }
}

/**
 * Ensure a newly joined peer receives already-existing producers in the room.
 * This complements onNewConsumerNeeded (which only covers future producers).
 */
async function syncExistingConsumersForPeer(peerId: string): Promise<void> {
  const peerConn = peerConnections.get(peerId);
  if (!peerConn || !peerConn.roomId || !peerConn.rtpCapabilities || !peerConn.recvTransportId) {
    return;
  }

  const room = rooms.get(peerConn.roomId);
  if (!room) return;

  const participants = room.getParticipants();
  for (const participant of participants) {
    if (participant.peerId === peerId) continue;
    for (const producer of participant.producers) {
      await createConsumerForPeer(peerConn.roomId, peerId, producer.producerId);
    }
  }
}

// ═══════════════════════════════════════════════════════════
// WebSocket Signaling
// ═══════════════════════════════════════════════════════════

function sendToPeer(peerId: string, msg: any): void {
  const peerConn = peerConnections.get(peerId);
  if (!peerConn || peerConn.ws.readyState !== WebSocket.OPEN) return;
  peerConn.ws.send(JSON.stringify(msg));
}

function broadcastToRoom(
  roomId: string,
  msg: any,
  excludePeerId?: string
): void {
  const peers = roomMembers.get(roomId);
  if (!peers) return;

  for (const peerId of peers) {
    if (peerId === excludePeerId) continue;
    sendToPeer(peerId, msg);
  }
}

function attachPeerToRoom(peerId: string, roomId: string): void {
  const peerConn = peerConnections.get(peerId);
  if (!peerConn) return;

  if (peerConn.roomId && peerConn.roomId !== roomId) {
    detachPeerFromRoom(peerId, peerConn.roomId);
  }

  let peers = roomMembers.get(roomId);
  if (!peers) {
    peers = new Set<string>();
    roomMembers.set(roomId, peers);
  }

  peers.add(peerId);
  peerConn.roomId = roomId;
}

function detachPeerFromRoom(peerId: string, roomId: string | null): void {
  if (!roomId) return;

  const peers = roomMembers.get(roomId);
  if (!peers) return;

  peers.delete(peerId);
  if (peers.size === 0) {
    roomMembers.delete(roomId);
  }
}

function resetPeerMediaState(peerConn: PeerConnection): void {
  peerConn.roomId = null;
  peerConn.rtpCapabilities = null;
  peerConn.sendTransportId = null;
  peerConn.recvTransportId = null;
}

function removePeerFromConference(peerId: string): void {
  const peerConn = peerConnections.get(peerId);
  if (!peerConn) return;

  const roomId = peerConn.roomId;
  if (roomId) {
    const room = rooms.get(roomId);
    if (room) {
      room.removePeer(peerId);
      if (room.peerCount === 0) {
        room.close();
        rooms.delete(roomId);
      }
    }

    detachPeerFromRoom(peerId, roomId);
  }

  resetPeerMediaState(peerConn);
}

function cleanupPeerConnection(peerId: string, reason: string): void {
  const peerConn = peerConnections.get(peerId);
  if (!peerConn || peerConn.cleanedUp) {
    return;
  }

  peerConn.cleanedUp = true;
  removePeerFromConference(peerId);
  peerConnections.delete(peerId);
  console.log(`[Server] Peer cleanup complete: ${peerId} (${reason})`);
}

function getRequestPath(req: IncomingMessage): string {
  try {
    const requestUrl = req.url || '/';
    return new URL(requestUrl, 'http://localhost').pathname;
  } catch {
    return '/';
  }
}

function wildcardToRegExp(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`, 'i');
}

function isOriginAllowed(originHeader: string | undefined): boolean {
  if (config.signaling.disableOriginCheck) {
    return true;
  }

  if (!originHeader) {
    return config.signaling.allowRequestsWithoutOrigin;
  }

  let parsedOrigin: URL;
  try {
    parsedOrigin = new URL(originHeader);
  } catch {
    return false;
  }

  const origin = parsedOrigin.origin.toLowerCase();
  const hostname = parsedOrigin.hostname.toLowerCase();

  return config.signaling.allowedOriginPatterns.some((rawPattern) => {
    const pattern = rawPattern.trim().toLowerCase();
    if (!pattern) return false;
    if (pattern === '*') return true;

    // If the pattern contains scheme, compare full origin.
    if (pattern.includes('://')) {
      return wildcardToRegExp(pattern).test(origin);
    }

    // Host-only wildcard pattern.
    return wildcardToRegExp(pattern).test(hostname);
  });
}

function isAllowedWsPath(pathname: string): boolean {
  return config.signaling.wsPaths.some((allowedPath) => {
    const normalizedAllowedPath = allowedPath.endsWith('/')
      ? allowedPath.slice(0, -1)
      : allowedPath;
    const normalizedPath = pathname.endsWith('/')
      ? pathname.slice(0, -1)
      : pathname;
    return normalizedAllowedPath === normalizedPath;
  });
}

function isSecureRequest(req: IncomingMessage): boolean {
  const isDirectTls = !!(req.socket as any)?.encrypted;
  if (isDirectTls) {
    return true;
  }

  const forwardedProto = req.headers['x-forwarded-proto'];
  if (Array.isArray(forwardedProto)) {
    return forwardedProto.some((value) => value.toLowerCase() === 'https');
  }

  return String(forwardedProto || '').toLowerCase() === 'https';
}

function rejectUpgrade(
  req: IncomingMessage,
  socket: Duplex,
  statusCode: number,
  reason: string
): void {
  const statusText =
    statusCode === 400
      ? 'Bad Request'
      : statusCode === 403
        ? 'Forbidden'
        : statusCode === 404
          ? 'Not Found'
          : 'Upgrade Rejected';

  socket.write(
    `HTTP/1.1 ${statusCode} ${statusText}\r\n` +
      'Connection: close\r\n' +
      'Content-Type: text/plain; charset=utf-8\r\n' +
      `Content-Length: ${Buffer.byteLength(reason)}\r\n` +
      '\r\n' +
      reason
  );
  socket.destroy();

  const origin = req.headers.origin || 'n/a';
  const path = getRequestPath(req);
  console.warn(
    `[Server] WS upgrade rejected (${statusCode}): path=${path} origin=${origin} reason=${reason}`
  );
}

/**
 * Handle signaling messages from client.
 *
 * NOTE: This implementation uses JSON for readability.
 * For production, replace JSON.parse/stringify with Protobuf
 * encode/decode using the generated signaling.js module:
 *
 *   import { signaling } from './protobuf/signaling.js';
 *   const msg = signaling.SignalingMessage.decode(buffer);
 *   const reply = signaling.SignalingMessage.encode({...}).finish();
 *   ws.send(reply);
 */
async function handleMessage(
  peerId: string,
  raw: string | Buffer
): Promise<void> {
  let msg: SignalingMessage;
  try {
    msg =
      typeof raw === 'string'
        ? JSON.parse(raw)
        : JSON.parse(raw.toString('utf-8'));
  } catch {
    console.error(`[Server] Invalid message from ${peerId}`);
    return;
  }

  const peerConn = peerConnections.get(peerId);
  if (!peerConn) return;
  peerConn.isAlive = true;
  const signalMethod = msg.method || msg.type;

  const respond = (data: any) => {
    if (!msg.id) return;
    sendToPeer(peerId, {
      id: msg.id,
      response: true,
      ok: true,
      data,
    });
  };

  const respondError = (error: string) => {
    if (!msg.id) return;
    sendToPeer(peerId, {
      id: msg.id,
      response: true,
      ok: false,
      error,
    });
  };

  try {
    switch (signalMethod) {
      // ── Pre-bind socket to room (first WS message) ──
      case 'join_room': {
        const data = asRecord(msg.data);
        const roomId = String(msg.roomId || data.roomId || '').trim();
        if (!roomId) return respondError('roomId is required');

        attachPeerToRoom(peerId, roomId);
        respond({ roomId });
        break;
      }

      // ── Join Room ──
      case 'joinRoom': {
        const data = asRecord(msg.data);
        const roomId = String(data.roomId || '');
        const displayName = String(data.displayName || 'Guest');
        if (!roomId) return respondError('roomId is required');

        // If peer moves from another room, clean old media and room bindings.
        if (peerConn.roomId && peerConn.roomId !== roomId) {
          removePeerFromConference(peerId);
        }

        const room = await getOrCreateRoom(roomId);

        attachPeerToRoom(peerId, roomId);
        peerConn.displayName = displayName;
        const alreadyInRoom = room
          .getParticipants()
          .some((participant) => participant.peerId === peerId);
        if (!alreadyInRoom) {
          room.addPeer(peerId, displayName);
        }

        respond({
          routerRtpCapabilities: room.rtpCapabilities,
          participants: room.getParticipants(),
          turnConfig:
            config.turn.urls.length > 0
              ? {
                  urls: config.turn.urls,
                  url: config.turn.urls[0],
                  username: config.turn.username,
                  credential: config.turn.credential,
                }
              : undefined,
        });
        break;
      }

      // ── Set RTP Capabilities ──
      case 'setRtpCapabilities': {
        const data = asRecord(msg.data);
        peerConn.rtpCapabilities = data.rtpCapabilities;
        respond({});
        break;
      }

      // ── Create Transport ──
      case 'createTransport': {
        const room = rooms.get(peerConn.roomId!);
        if (!room) return respondError('Not in a room');

        const data = asRecord(msg.data);
        const transportData = await room.createWebRtcTransport(peerId);

        // Track direction
        if (data.direction === 'send') {
          peerConn.sendTransportId = transportData.transportId;
        } else {
          peerConn.recvTransportId = transportData.transportId;
        }

        let iceCandidates = transportData.iceCandidates;
        if (config.mediasoup.announcedPort) {
          iceCandidates = iceCandidates.map(c => ({
            ...c,
            port: config.mediasoup.announcedPort!
          }));
        }

        respond({
          id: transportData.transportId,
          iceParameters: transportData.iceParameters,
          iceCandidates: iceCandidates,
          dtlsParameters: transportData.dtlsParameters,
        });
        break;
      }

      // ── Connect Transport ──
      case 'connectTransport': {
        const room = rooms.get(peerConn.roomId!);
        if (!room) return respondError('Not in a room');

        const data = asRecord(msg.data);
        const transportId = String(data.transportId || '');
        await room.connectTransport(
          peerId,
          transportId,
          data.dtlsParameters
        );
        // Once send transport is connected, client recv PC is typically ready.
        // Sync existing producers so late-joiners immediately receive media.
        if (transportId && transportId === peerConn.sendTransportId) {
          await syncExistingConsumersForPeer(peerId);
        }
        respond({});
        break;
      }

      // ── Produce (send media) ──
      case 'produce': {
        const room = rooms.get(peerConn.roomId!);
        if (!room) return respondError('Not in a room');

        const data = asRecord(msg.data);
        const producerId = await room.produce(
          peerId,
          String(data.transportId || ''),
          data.kind,
          data.rtpParameters
        );
        await syncExistingConsumersForPeer(peerId);
        respond({ producerId });
        break;
      }

      // ── Force consumer catch-up for already existing producers ──
      case 'syncConsumers': {
        if (!peerConn.roomId) return respondError('Not in a room');
        await syncExistingConsumersForPeer(peerId);
        respond({});
        break;
      }

      // ── Resume Consumer ──
      // RACE CONDITION GUARD: транспорт может закрыться из-за DTLS failure
      // до того, как клиент успеет отправить resume через WebSocket.
      // Вызов resume() на уничтоженном Consumer'е (C++ worker) ронял бы Node.js.
      // Вместо краша — отвечаем ошибкой, клиент корректно обработает "not found".
      case 'resumeConsumer': {
        const room = rooms.get(peerConn.roomId!);
        if (!room) return respondError('Not in a room');

        const data = asRecord(msg.data);
        const consumerId = String(data.consumerId || '');
        if (!consumerId) return respondError('consumerId is required');

        try {
          await room.resumeConsumer(peerId, consumerId);
          respond({});
        } catch (resumeErr: any) {
          const errMsg = resumeErr?.message || 'Failed to resume consumer';
          console.warn(`[Server] resumeConsumer failed (peer=${peerId} consumer=${consumerId}): ${errMsg}`);
          respondError(errMsg);
        }
        break;
      }

      // ── Pause Consumer ──
      case 'pauseConsumer': {
        const room = rooms.get(peerConn.roomId!);
        if (!room) return respondError('Not in a room');

        const data = asRecord(msg.data);
        const consumerId = String(data.consumerId || '');
        if (!consumerId) return respondError('consumerId is required');

        try {
          await room.pauseConsumer(peerId, consumerId);
          respond({});
        } catch (pauseErr: any) {
          const errMsg = pauseErr?.message || 'Failed to pause consumer';
          console.warn(`[Server] pauseConsumer failed (peer=${peerId} consumer=${consumerId}): ${errMsg}`);
          respondError(errMsg);
        }
        break;
      }

      // ── Quality Report (RTT/PLR for BWE adaptation) ──
      case 'qualityReport': {
        const room = rooms.get(peerConn.roomId!);
        if (!room) return respondError('Not in a room');

        const qualityReport = parseQualityReport(msg.data);
        if (!qualityReport) {
          return respondError('Invalid qualityReport payload');
        }

        room.handleQualityReport(peerId, qualityReport);
        respond({});
        break;
      }

      // ── Leave Room ──
      case 'leaveRoom': {
        removePeerFromConference(peerId);
        respond({});
        break;
      }

      // ── Raw signaling relay (SDP/ICE) scoped to room members ──
      case 'offer':
      case 'answer':
      case 'iceCandidate':
      case 'candidate':
      case 'sdp_offer':
      case 'sdp_answer':
      case 'ice_candidate': {
        if (!peerConn.roomId) return respondError('Not in a room');
        broadcastToRoom(
          peerConn.roomId,
          {
            method: signalMethod,
            data: msg.data,
            fromPeerId: peerId,
          },
          peerId
        );
        respond({});
        break;
      }

      // ── Keepalive ──
      case 'ping': {
        sendToPeer(peerId, { method: 'pong', data: {} });
        break;
      }

      default:
        respondError(`Unknown method: ${signalMethod}`);
    }
  } catch (err: any) {
    console.error(`[Server] Error handling ${signalMethod}:`, err);
    respondError(err.message || 'Internal error');
  }
}

// ═══════════════════════════════════════════════════════════
// Server Startup
// ═══════════════════════════════════════════════════════════

async function main(): Promise<void> {
  console.log('='.repeat(60));
  console.log('  HTQWeb SFU Server — VP8 + H264 Baseline / 1080p@60');
  console.log('='.repeat(60));

  // 1. Create Mediasoup workers
  await createWorkers();

  // 2. Create HTTP(S) server
  let httpServer;
  const tlsCertPath = config.tls.cert.trim();
  const tlsKeyPath = config.tls.key.trim();
  const hasCertPath = tlsCertPath.length > 0;
  const hasKeyPath = tlsKeyPath.length > 0;
  const certExists = hasCertPath && existsSync(tlsCertPath);
  const keyExists = hasKeyPath && existsSync(tlsKeyPath);
  const tlsReady = certExists && keyExists;
  const useTls = tlsReady;

  if (config.signaling.requireTls && !tlsReady) {
    const missingTlsReasons: string[] = [];
    if (!hasCertPath) {
      missingTlsReasons.push('TLS_CERT is empty');
    } else if (!certExists) {
      missingTlsReasons.push(`TLS_CERT file not found: ${tlsCertPath}`);
    }

    if (!hasKeyPath) {
      missingTlsReasons.push('TLS_KEY is empty');
    } else if (!keyExists) {
      missingTlsReasons.push(`TLS_KEY file not found: ${tlsKeyPath}`);
    }

    throw new Error(
      'SIGNALING_REQUIRE_TLS=true but TLS is not ready: ' +
        missingTlsReasons.join('; ') +
        '. Generate LAN certificate/key and set TLS_CERT/TLS_KEY.'
    );
  }

  if (!tlsReady && (hasCertPath || hasKeyPath)) {
    console.warn(
      '[Server] Partial TLS configuration detected (cert/key mismatch). ' +
        'Starting without TLS because SIGNALING_REQUIRE_TLS=false.'
    );
  }

  if (useTls) {
    // HTTPS + WSS signaling (LAN secure context)
    httpServer = createHttpsServer({
      cert: readFileSync(tlsCertPath),
      key: readFileSync(tlsKeyPath),
      minVersion: 'TLSv1.2',
    }, handleHttpRequest);
    console.log(`[Server] TLS enabled (min: TLSv1.2) cert=${tlsCertPath} key=${tlsKeyPath}`);
  } else {
    // Plain HTTP mode (only allowed when signaling TLS requirement is disabled).
    httpServer = createHttpServer(handleHttpRequest);
    console.warn(
      '[Server] Running without TLS. ' +
        'Use this mode only behind trusted local reverse-proxy/TLS termination.'
    );
  }

  // 3. Attach WebSocket signaling server with explicit Upgrade handling.
  const wss = new WebSocketServer({ noServer: true });

  httpServer.on('upgrade', (req, socket, head) => {
    const connectionHeader = String(req.headers.connection || '').toLowerCase();
    const upgradeHeader = String(req.headers.upgrade || '').toLowerCase();

    // Node.js fires the 'upgrade' event only for requests that include
    // Connection: Upgrade, so we only need to verify the Upgrade header
    // value. Behind a reverse-proxy (nginx) the Connection header can
    // arrive as 'keep-alive' or 'close' after TLS termination strips
    // the upgrade token — this is normal and safe to accept.
    const isWebSocketUpgrade =
      upgradeHeader === 'websocket' ||
      connectionHeader
        .split(',')
        .map((token) => token.trim())
        .includes('upgrade');

    if (!isWebSocketUpgrade) {
      console.warn(
        `[Server] Rejecting upgrade — Upgrade: '${req.headers.upgrade}' ` +
        `Connection: '${req.headers.connection}'`
      );
      return rejectUpgrade(req, socket, 400, 'Invalid WebSocket Upgrade headers');
    }

    const requestPath = getRequestPath(req);
    if (!isAllowedWsPath(requestPath)) {
      return rejectUpgrade(req, socket, 404, `Unsupported WebSocket path: ${requestPath}`);
    }

    const originHeader = Array.isArray(req.headers.origin)
      ? req.headers.origin[0]
      : req.headers.origin;
    if (!isOriginAllowed(originHeader)) {
      return rejectUpgrade(req, socket, 403, 'Origin is not allowed');
    }

    if (config.signaling.requireTls && !isSecureRequest(req)) {
      return rejectUpgrade(req, socket, 403, 'TLS is required for signaling');
    }

    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit('connection', ws, req);
    });
  });

  const wsHeartbeatTimer = setInterval(() => {
    for (const [peerId, peerConn] of peerConnections) {
      const ws = peerConn.ws;
      if (ws.readyState !== WebSocket.OPEN) {
        continue;
      }

      if (!peerConn.isAlive) {
        console.warn(
          `[Server] Heartbeat timeout for ${peerId}. Terminating stale socket.`
        );
        ws.terminate();
        cleanupPeerConnection(peerId, 'heartbeat-timeout');
        continue;
      }

      peerConn.isAlive = false;
      try {
        ws.ping();
      } catch (error) {
        console.warn(`[Server] Failed to send heartbeat ping to ${peerId}:`, error);
        ws.terminate();
        cleanupPeerConnection(peerId, 'heartbeat-ping-failure');
      }
    }
  }, WS_HEARTBEAT_INTERVAL_MS);

  wss.on('connection', (ws: WebSocket, req: IncomingMessage) => {
    const peerId = uuidv4();
    const peerConn: PeerConnection = {
      peerId,
      ws,
      roomId: null,
      displayName: '',
      rtpCapabilities: null,
      sendTransportId: null,
      recvTransportId: null,
      isAlive: true,
      cleanedUp: false,
    };

    peerConnections.set(peerId, peerConn);
    console.log(
      `[Server] Client connected: ${peerId} path=${getRequestPath(req)} origin=${req.headers.origin || 'n/a'}`
    );

    // Send peer their ID
    ws.send(JSON.stringify({ method: 'welcome', data: { peerId } }));

    ws.on('message', (data) => {
      handleMessage(peerId, data as Buffer);
    });

    ws.on('pong', () => {
      peerConn.isAlive = true;
    });

    ws.on('close', (code, reasonBuffer) => {
      const reason = reasonBuffer.toString() || 'n/a';
      console.log(`[Server] Client disconnected: ${peerId}`);
      cleanupPeerConnection(peerId, `ws-close code=${code} reason=${reason}`);
    });

    ws.on('error', (err) => {
      console.error(`[Server] WebSocket error for ${peerId}:`, err);
      ws.terminate();
      cleanupPeerConnection(peerId, 'ws-error');
    });
  });

  // 4. Start listening
  httpServer.listen(config.port, config.host, () => {
    const wsProtocol = useTls ? 'wss' : 'ws';
    console.log(
      `[Server] Listening on ${config.host}:${config.port}`
    );
    console.log(
      `[Server] Signaling: ${wsProtocol}://${config.host}:${config.port}${config.signaling.wsPaths[0]}`
    );
    console.log(
      `[Server] WS paths: ${config.signaling.wsPaths.join(', ')} | ` +
        `Origin check: ${config.signaling.disableOriginCheck ? 'disabled' : 'enabled'}`
    );
    if (!config.signaling.disableOriginCheck) {
      console.log(
        `[Server] Allowed origins: ${config.signaling.allowedOriginPatterns.join(', ')}`
      );
    }
    console.log(
      `[Server] Workers: ${workers.length}, ` +
        `Target video: ${(config.bitrate.videoBps / 1e6).toFixed(0)} Mbps, ` +
        `Target audio: ${(config.bitrate.audioBps / 1000).toFixed(0)} kbps`
    );

    if (config.tcpTunnelMode && config.mediasoup.webRtcServerPort !== 44444) {
      console.log(`[Server] TCP tunnel mode bridging active. Forwarding incoming tunnel traffic (localhost:44444) -> Mediasoup (localhost:${config.mediasoup.webRtcServerPort})`);
      const tcpBouncer = net.createServer((clientSocket) => {
        const targetSocket = net.connect(config.mediasoup.webRtcServerPort, '127.0.0.1', () => {
          clientSocket.pipe(targetSocket);
          targetSocket.pipe(clientSocket);
        });
        clientSocket.on('error', () => { /* ignore */ });
        targetSocket.on('error', () => { /* ignore */ });
      });
      tcpBouncer.on('error', (err) => {
        console.error(`[Server] TCP bouncer error on 44444:`, err);
      });
      tcpBouncer.listen(44444, '127.0.0.1');
    }
  });

  // 5. Graceful shutdown
  const shutdown = () => {
    console.log('\n[Server] Shutting down...');
    clearInterval(wsHeartbeatTimer);
    for (const [, room] of rooms) {
      room.close();
    }
    closeMediasoupResources('shutdown');
    httpServer.close();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

function asRecord(input: unknown): Record<string, any> {
  return input && typeof input === 'object'
    ? (input as Record<string, any>)
    : {};
}

function parseQualityReport(input: unknown): QualityReportPayload | null {
  const raw = asRecord(input);
  const packetLossRate = Number(raw.packetLossRate);
  const rttMs = Number(raw.rttMs);

  if (!Number.isFinite(packetLossRate) || !Number.isFinite(rttMs)) {
    return null;
  }

  return {
    packetLossRate: Math.max(0, Math.min(packetLossRate, 1)),
    rttMs: Math.max(0, rttMs),
  };
}

function handleHttpRequest(
  req: IncomingMessage,
  res: import('http').ServerResponse
): void {
  const requestPath = getRequestPath(req);

  if (requestPath === '/' || requestPath === '/healthz' || requestPath === '/health') {
    const payload = JSON.stringify({
      ok: true,
      service: 'htqweb-sfu',
      wsPaths: config.signaling.wsPaths,
    });
    res.writeHead(200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Content-Length': Buffer.byteLength(payload),
    });
    res.end(payload);
    return;
  }

  const payload = JSON.stringify({
    ok: false,
    error: 'Not Found',
    hint: 'Use WebSocket upgrade on /ws/sfu/',
  });
  res.writeHead(404, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

main().catch((err) => {
  console.error('[Server] Fatal error:', err);
  const errorMessage =
    err &&
    typeof err === 'object' &&
    typeof (err as any).message === 'string'
      ? (err as any).message.toLowerCase()
      : '';
  const isWebRtcPortInUse =
    errorMessage.includes('address already in use') ||
    errorMessage.includes('eaddrinuse') ||
    errorMessage.includes('uv_udp_bind() failed') ||
    errorMessage.includes('uv_tcp_bind() failed');

  if (isWebRtcPortInUse) {
    const webRtcPort = config.mediasoup.webRtcServerPort;
    console.error(
      `[Server] WEBRTC_SERVER_PORT=${webRtcPort} is already in use. ` +
        'Stop the process holding this port or set a different WEBRTC_SERVER_PORT in sfu/.env.'
    );
    console.error(
      `[Server] Quick check (Windows): cmd /c netstat -ano | findstr :${webRtcPort}`
    );
  }

  closeMediasoupResources('fatal startup error');
  const isSpawnPermissionError =
    err &&
    typeof err === 'object' &&
    (err as any).code === 'EPERM' &&
    (err as any).syscall === 'spawn';

  if (isSpawnPermissionError) {
    console.error(
      '[Server] Mediasoup worker could not be spawned (EPERM). ' +
        'On Windows, prefer running SFU in Docker/WSL2 or allow mediasoup-worker.exe in security policy.'
    );
    console.error(
      '[Server] Check executable: sfu/node_modules/mediasoup/worker/out/Release/mediasoup-worker.exe'
    );
  }
  process.exit(1);
});
