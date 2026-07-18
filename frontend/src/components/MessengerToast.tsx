/**
 * MessengerToast — rich toast layout for new chat-message notifications.
 *
 * Layout (per the design spec):
 *
 *   ┌─────────────────────────────────────────────┐
 *   │  Иванов Иван                  [avatar]      │
 *   │  Текст сообщения, до 2 строк…               │
 *   │                                       14:32 │
 *   └─────────────────────────────────────────────┘
 *
 * - Имя сотрудника (полужирный) + аватарка справа.
 * - Тело — `webkit-line-clamp: 2` (две строки максимум).
 * - Время прибытия — в правом нижнем углу.
 *
 * Used by ``NotificationsViewer`` only for ``target_type='messenger_room'``
 * notifications. Other types keep the default sonner text-only layout.
 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { toast } from 'sonner';

import type { Notification } from '@/types/tasks';

interface Props {
    toastId: string | number;
    notification: Notification;
    onClick?: () => void;
}

const fmtTime = (iso: string): string => {
    try {
        return new Date(iso).toLocaleTimeString('ru', {
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch {
        return '';
    }
};

const initialsOf = (name: string | null | undefined): string => {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    const first = parts[0][0] ?? '';
    const second = parts[1]?.[0] ?? '';
    return (first + second).toUpperCase() || '?';
};

/** Extract the chat body from a notification verb.
 *  New form (post-cleanup):
 *    "в чате «<room>»: <preview>"   — group chats
 *    "<preview>"                     — direct chats
 *  Legacy forms still on disk:
 *    "прислал в чате «<room>»: <preview>"
 *    "прислал сообщение: <preview>"
 *  All four collapse to just the message body for the rich toast. */
const extractMessageBody = (verb: string): string => {
    const cleaned = verb.trim();
    // New format: "в чате «X»: BODY"
    const groupNew = cleaned.match(/^в чате «[^»]*»:\s*(.+)$/);
    if (groupNew) return groupNew[1].trim();
    // Legacy: "прислал [в чате «X» | сообщение]: BODY"
    const legacy = cleaned.match(
        /^прислал(?:\s+(?:в чате «[^»]*»|сообщение))?:\s*(.+)$/,
    );
    if (legacy) return legacy[1].trim();
    return cleaned;
};

export const MessengerToast: React.FC<Props> = ({
    toastId,
    notification,
    onClick,
}) => {
    const navigate = useNavigate();
    const name = notification.actor_name || 'Сотрудник';
    const avatar = notification.actor_avatar_url || null;
    const body = extractMessageBody(notification.verb || '');
    const arrived = fmtTime(notification.created_at);

    const handleOpen = () => {
        if (onClick) {
            onClick();
            return;
        }
        toast.dismiss(toastId);
    };

    return (
        <div
            // ``items-center`` vertically centers the avatar with the text
            // column so the picture sits on the toast's middle axis (soosno).
            // ``pb-5`` reserves space for the absolutely-positioned time stamp.
            className="relative flex w-[380px] max-w-[90vw] items-center gap-3 rounded-xl border bg-card p-3 pb-5 pr-12 shadow-xl"
            role="button"
            tabIndex={0}
            onClick={handleOpen}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleOpen();
                }
            }}
        >
            {/* Text column */}
            <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-foreground truncate">
                    {name}
                </p>
                <p
                    className="mt-0.5 text-sm text-muted-foreground"
                    style={{
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                        wordBreak: 'break-word',
                    }}
                >
                    {body}
                </p>
            </div>

            {/* Avatar — 48px, vertically centered. Renders the real photo
                whenever the notification carries one; falls back to the
                primary-coloured initials disk only if both the snapshot
                column and the task_users replica are empty. */}
            <AvatarBlock src={avatar} fallback={initialsOf(name)} />

            {/* Time — bottom-right corner */}
            {arrived && (
                <span className="absolute bottom-1.5 right-3 text-[10px] tabular-nums text-muted-foreground">
                    {arrived}
                </span>
            )}

            {/* Close button — top-right tucked over the avatar's edge */}
            <button
                type="button"
                onClick={(e) => {
                    e.stopPropagation();
                    toast.dismiss(toastId);
                }}
                className="absolute top-1.5 right-1.5 p-1 rounded-full text-muted-foreground/60 hover:bg-muted hover:text-foreground"
                aria-label="Закрыть"
            >
                <X className="h-3 w-3" />
            </button>
        </div>
    );
};


/** Avatar slot with graceful fallback.
 *
 *  Renders ``src`` until the browser reports a load error (expired
 *  signed URL, deleted file) — at which point the disk silently swaps
 *  to the initials fallback. Sized at 48px to match the design spec.
 */
const AvatarBlock: React.FC<{ src: string | null; fallback: string }> = ({
    src,
    fallback,
}) => {
    const [errored, setErrored] = React.useState(false);
    if (src && !errored) {
        return (
            <img
                src={src}
                alt=""
                onError={() => setErrored(true)}
                className="h-12 w-12 flex-shrink-0 rounded-full object-cover ring-1 ring-border"
            />
        );
    }
    return (
        <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-base font-semibold text-primary">
            {fallback}
        </div>
    );
};
