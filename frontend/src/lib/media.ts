/**
 * media.ts — helpers for resolving and rendering media-service URLs.
 *
 * Backend returns relative paths like "/api/media/v1/files/{id}". The browser
 * resolves these against the page origin and nginx proxies /api/media/* to
 * the media-service. We deliberately keep them relative so the same code
 * works in dev (Vite proxy), prod (nginx), and over a tunnel — no string
 * surgery on VITE_API_BASE_URL is needed.
 */

export type MediaVariant =
    | 'thumb_32'
    | 'thumb_96'
    | 'thumb_256'
    | 'thumb_512'
    | 'preview_1024'
    | 'poster';

export type AvatarSize = 24 | 32 | 48 | 64 | 96 | 128 | 256;

const FILE_ID_RE = /\/files\/([0-9a-f-]{36})/i;

/**
 * Build a relative URL to a media file (or one of its variants).
 *
 * Returns ``/api/media/v1/files/{id}`` for the original, or
 * ``/api/media/v1/files/{id}/{variant}`` when a variant name is given.
 */
export function mediaUrl(fileId: string, variant?: MediaVariant): string {
    return variant
        ? `/api/media/v1/files/${fileId}/${variant}`
        : `/api/media/v1/files/${fileId}`;
}

/**
 * Coerce whatever the backend hands us (file id, relative URL, full URL, or
 * a transient ``blob:``/``data:`` preview) into a usable ``<img src>``.
 *
 * - Empty/undefined → undefined (caller renders a fallback).
 * - ``blob:`` / ``data:`` / absolute URL → returned unchanged.
 * - Bare UUID → ``/api/media/v1/files/{uuid}``.
 * - Anything else (already a path) → returned unchanged.
 */
export function resolveMediaSrc(input?: string | null): string | undefined {
    if (!input) return undefined;
    if (
        input.startsWith('blob:') ||
        input.startsWith('data:') ||
        input.startsWith('http://') ||
        input.startsWith('https://') ||
        input.startsWith('/')
    ) {
        return input;
    }
    if (/^[0-9a-f-]{36}$/i.test(input)) return mediaUrl(input);
    return input;
}

/**
 * Extract the file UUID from a stored avatar_url like
 * ``/api/media/v1/files/{uuid}`` or ``https://host/api/media/v1/files/{uuid}``.
 * Returns ``null`` for legacy/external URLs (``i.pravatar.cc`` etc.).
 */
export function extractFileId(url?: string | null): string | null {
    if (!url) return null;
    const m = FILE_ID_RE.exec(url);
    return m ? m[1] : null;
}

/**
 * Pick the smallest avatar variant that still looks crisp at the requested
 * CSS size on the current device. We round up to the next available step,
 * never serving a variant smaller than the displayed pixel count.
 */
export function pickAvatarVariant(displaySize: AvatarSize): MediaVariant {
    const dpr = typeof window !== 'undefined' ? Math.min(window.devicePixelRatio || 1, 3) : 1;
    const physical = displaySize * dpr;
    if (physical <= 32) return 'thumb_32';
    if (physical <= 96) return 'thumb_96';
    return 'thumb_256';
}

/**
 * Build a ``srcset`` for an avatar so retina displays pick a sharper variant
 * automatically. Variants that don't exist yet (e.g., right after upload,
 * before the worker finishes) gracefully 404 and the browser falls back to
 * the next entry.
 */
export function avatarSrcSet(fileId: string): string {
    return [
        `${mediaUrl(fileId, 'thumb_32')} 32w`,
        `${mediaUrl(fileId, 'thumb_96')} 96w`,
        `${mediaUrl(fileId, 'thumb_256')} 256w`,
    ].join(', ');
}
