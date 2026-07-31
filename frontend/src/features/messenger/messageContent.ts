/**
 * Decoding a stored chat message into something renderable.
 *
 * Extracted from `MessengerPage.tsx` so the admin moderation view
 * (`pages/AdminChats.tsx`) shares it instead of keeping a second copy. That
 * second copy was decoding a field the API stopped returning: it read
 * `msg.encrypted_data` (base64) and `msg.msg_type`, both from the
 * pre-microservice Django monolith, and bailed out with `''` on the very
 * first line — which is why every message rendered blank in the admin view.
 *
 * What the backend actually stores today (`apps.messenger.models.Message`):
 *   - `content` — a JSON string, `{"text": "…"}` for anything the SPA sent;
 *   - `is_encrypted` — E2EE rooms, whose payload the server cannot read;
 *   - `attachments[]` — files, carried separately from the text.
 */
import type { ChatMessage } from './types';

export type DecodedMessage = {
    text: string;
    file_url?: string;
    file_name?: string;
    mime_type?: string;
    /** Set for image attachments after migration 006 — falls back to
     *  ``file_url`` in the renderer when missing. */
    thumb_url?: string | null;
    width?: number | null;
    height?: number | null;
    data_type?: string | null;
};

export function decodeMessageText(msg: ChatMessage): DecodedMessage | string {
    const attachment = msg.attachments?.[0];
    if (!msg.content && !attachment) return '';
    if (!msg.is_encrypted) {
        let parsed: any = null;
        let text = msg.content || '';
        try {
            parsed = msg.content ? JSON.parse(msg.content) : null;
            text = parsed?.text || parsed?.body || '';
        } catch {
            text = msg.content || '';
        }

        if (attachment) {
            return {
                text,
                file_url: attachment.url,
                file_name: attachment.filename,
                mime_type: attachment.content_type,
                thumb_url: attachment.thumbnail_url ?? null,
                width: attachment.width ?? null,
                height: attachment.height ?? null,
                data_type: attachment.data_type ?? null,
            };
        }
        if (parsed?.file_url || msg.msg_type === 'file') {
            return parsed;
        }
        return text || msg.content || '';
    }
    return '🔒 Зашифрованное сообщение';
}
