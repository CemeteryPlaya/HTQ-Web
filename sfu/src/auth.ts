/**
 * Проверка платформенного JWT (HS256) на стороне SFU.
 *
 * Токены выпускает Django (`apps.users` → `htqweb/authn/jwt.py`, issuer
 * `htqweb-auth`) и локально валидирует каждый сервис тем же общим
 * `JWT_SECRET` — сетевого вызова нет. SFU повторяет ровно ту же схему,
 * поэтому здесь нет зависимости от npm-библиотеки: HS256 — это HMAC-SHA256
 * над `header.payload`, всё остальное — разбор claim'ов.
 *
 * Проверяем то же, что и `decode_token` на бэкенде: подпись, алгоритм,
 * `exp`, `iss` и дополнительно `token_type == "access"` (refresh-токен
 * в сигналинг пускать незачем).
 */

import { createHmac, timingSafeEqual } from 'crypto';

export interface AccessTokenClaims {
  sub?: string;
  user_id?: number;
  username?: string;
  email?: string;
  is_staff?: boolean;
  is_superuser?: boolean;
  is_admin?: boolean;
  token_type?: string;
  iat?: number;
  exp?: number;
  iss?: string;
}

export type VerifyTokenResult =
  | { ok: true; claims: AccessTokenClaims }
  | { ok: false; reason: string };

export interface VerifyTokenOptions {
  secret: string;
  issuer: string;
  /** Запас на расхождение часов между контейнерами, секунды. */
  clockToleranceSec?: number;
}

function decodeSegment(segment: string): unknown {
  const json = Buffer.from(segment, 'base64url').toString('utf-8');
  return JSON.parse(json);
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function signaturesMatch(expected: Buffer, actual: Buffer): boolean {
  // timingSafeEqual бросает на разной длине — сравниваем длину заранее.
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function verifyAccessToken(
  rawToken: string,
  options: VerifyTokenOptions
): VerifyTokenResult {
  const token = String(rawToken || '').trim();
  if (!token) {
    return { ok: false, reason: 'token is empty' };
  }
  if (!options.secret) {
    return { ok: false, reason: 'JWT_SECRET is not configured on the SFU' };
  }

  const parts = token.split('.');
  if (parts.length !== 3) {
    return { ok: false, reason: 'malformed token (expected 3 segments)' };
  }

  const [headerSegment, payloadSegment, signatureSegment] = parts;

  let header: Record<string, unknown> | null;
  let payload: Record<string, unknown> | null;
  try {
    header = asObject(decodeSegment(headerSegment));
    payload = asObject(decodeSegment(payloadSegment));
  } catch {
    return { ok: false, reason: 'malformed token (base64/JSON decode failed)' };
  }

  if (!header || !payload) {
    return { ok: false, reason: 'malformed token (header/payload is not an object)' };
  }

  if (String(header.alg || '').toUpperCase() !== 'HS256') {
    // Явно отвергаем "alg": "none" и подмену алгоритма на асимметричный.
    return { ok: false, reason: `unsupported alg: ${String(header.alg)}` };
  }

  let providedSignature: Buffer;
  try {
    providedSignature = Buffer.from(signatureSegment, 'base64url');
  } catch {
    return { ok: false, reason: 'malformed signature' };
  }

  const expectedSignature = createHmac('sha256', options.secret)
    .update(`${headerSegment}.${payloadSegment}`)
    .digest();

  if (!signaturesMatch(expectedSignature, providedSignature)) {
    return { ok: false, reason: 'signature mismatch' };
  }

  const claims = payload as AccessTokenClaims;
  const tolerance = options.clockToleranceSec ?? 30;
  const nowSec = Math.floor(Date.now() / 1000);

  if (typeof claims.exp !== 'number') {
    return { ok: false, reason: 'exp claim is missing' };
  }
  if (nowSec > claims.exp + tolerance) {
    return { ok: false, reason: 'token expired' };
  }

  if (typeof claims.iat === 'number' && claims.iat - tolerance > nowSec) {
    return { ok: false, reason: 'token issued in the future' };
  }

  if (options.issuer && claims.iss !== options.issuer) {
    return { ok: false, reason: `unexpected issuer: ${String(claims.iss)}` };
  }

  if (claims.token_type && claims.token_type !== 'access') {
    return { ok: false, reason: `token_type must be "access", got "${claims.token_type}"` };
  }

  return { ok: true, claims };
}

/**
 * Человекочитаемая метка пира для логов: `username#user_id`, без e-mail.
 */
export function describeClaims(claims: AccessTokenClaims): string {
  const name = String(claims.username || claims.sub || 'unknown');
  return claims.user_id !== undefined ? `${name}#${claims.user_id}` : name;
}
