export type WebRTCErrorCode =
  | 'SIGNALING_CONNECTION_FAILED'
  | 'SIGNALING_PROTOCOL_ERROR'
  | 'SIGNALING_TIMEOUT'
  | 'SIGNALING_REQUEST_FAILED'
  | 'SIGNALING_UNSUPPORTED_CODEC'
  | 'NATIVE_SDP_REJECTION'
  | 'ICE_GATHERING_FAILURE'
  | 'MEDIA_CAPTURE_FAILURE'
  | 'TRANSPORT_SETUP_FAILURE'
  | 'UNKNOWN';

export interface WebRTCError {
  code: WebRTCErrorCode;
  message: string;
  retriable: boolean;
  details?: Record<string, unknown>;
  cause?: unknown;
}

export function createWebRTCError(
  code: WebRTCErrorCode,
  message: string,
  options: {
    retriable?: boolean;
    details?: Record<string, unknown>;
    cause?: unknown;
  } = {}
): WebRTCError {
  return {
    code,
    message,
    retriable: options.retriable ?? false,
    details: options.details,
    cause: options.cause,
  };
}

export function webRTCErrorFromUnknown(
  input: unknown,
  fallbackCode: WebRTCErrorCode = 'UNKNOWN'
): WebRTCError {
  if (isWebRTCError(input)) {
    return input;
  }

  const message =
    input instanceof Error
      ? input.message
      : typeof input === 'string'
        ? input
        : 'Unknown WebRTC error';

  if (/unsupported codec/i.test(message)) {
    return createWebRTCError('SIGNALING_UNSUPPORTED_CODEC', message, {
      retriable: true,
      cause: input,
    });
  }

  if (/set(local|remote)description|sdp/i.test(message)) {
    return createWebRTCError('NATIVE_SDP_REJECTION', message, {
      retriable: true,
      cause: input,
    });
  }

  if (/ice/i.test(message) && /fail|error|timeout/i.test(message)) {
    return createWebRTCError('ICE_GATHERING_FAILURE', message, {
      retriable: true,
      cause: input,
    });
  }

  return createWebRTCError(fallbackCode, message, {
    retriable: false,
    cause: input,
  });
}

export function signalingErrorFromMessage(
  message: string,
  details?: Record<string, unknown>
): WebRTCError {
  if (/unsupported codec/i.test(message)) {
    return createWebRTCError('SIGNALING_UNSUPPORTED_CODEC', message, {
      retriable: true,
      details,
    });
  }

  if (/sdp|offer|answer|set(local|remote)description/i.test(message)) {
    return createWebRTCError('NATIVE_SDP_REJECTION', message, {
      retriable: true,
      details,
    });
  }

  if (/ice/i.test(message) && /fail|error|timeout/i.test(message)) {
    return createWebRTCError('ICE_GATHERING_FAILURE', message, {
      retriable: true,
      details,
    });
  }

  return createWebRTCError('SIGNALING_REQUEST_FAILED', message, {
    retriable: false,
    details,
  });
}

function isWebRTCError(input: unknown): input is WebRTCError {
  if (!input || typeof input !== 'object') return false;
  const maybe = input as Partial<WebRTCError>;
  return (
    typeof maybe.code === 'string' &&
    typeof maybe.message === 'string' &&
    typeof maybe.retriable === 'boolean'
  );
}
