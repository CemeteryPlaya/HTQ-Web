/**
 * Transport Module — Barrel Export
 *
 * Provides the transport-agnostic media conference abstractions.
 * Import from here, not from individual files.
 *
 * Usage (Step 1 — WebRTC only):
 *   import { WebRTCAdapter } from '@/lib/transport';
 *   const transport: IMediaTransport = new WebRTCAdapter(events);
 *
 * Usage (Step 3 — auto-detection):
 *   import { createMediaTransport } from '@/lib/transport';
 *   const transport = createMediaTransport(events); // returns best available
 */

export type {
  IMediaTransport,
  IMediaTransportEvents,
  TransportError,
  TransportErrorCode,
  TransportJoinOptions,
  TransportMetrics,
  RemoteParticipantStream,
} from './IMediaTransport';

export { WebRTCAdapter } from './WebRTCAdapter';
