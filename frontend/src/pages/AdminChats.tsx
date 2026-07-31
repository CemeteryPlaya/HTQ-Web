import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { MessageCircle, ShieldAlert, ArrowLeft, Lock, FileText, Download, Music } from 'lucide-react';
import { BackToProfile } from '@/components/BackToProfile';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { messengerApi } from '../features/messenger/api/messengerApi';
import { decodeMessageText } from '../features/messenger/messageContent';
import { ChatMessage, ChatRoom } from '../features/messenger/types';

/** Author of a message, as the moderation view should label it.
 *
 *  `GET /admin/rooms/{id}/messages` returns `sender` (the platform brief) next
 *  to `sender_id`. A missing `sender` is a genuinely system-authored message —
 *  it used to be *every* message, because the endpoint only ever returned the
 *  numeric id and this view reads the profile. */
function senderLabel(msg: ChatMessage, fallback: string): string {
    const sender = msg.sender as
        | { full_name?: string; first_name?: string; last_name?: string; username?: string; id?: number }
        | null
        | undefined;
    if (!sender) return fallback;
    const name =
        sender.full_name ||
        [sender.first_name, sender.last_name].filter(Boolean).join(' ') ||
        sender.username ||
        '';
    const id = msg.sender_id ?? sender.id;
    return name ? `${name}${id != null ? ` (ID: ${id})` : ''}` : fallback;
}

/** Human-readable names of everyone in a room, for the moderation views.
 *
 *  `GET /admin/rooms` returns `participants: [{user_id, role, user}]` where
 *  `user` is the platform brief (or `null` if that account is gone) — so an
 *  unresolvable participant still shows up, as `#<id>`, instead of silently
 *  shrinking the list. This used to read `room.memberships`, a field name
 *  left over from the pre-microservice Django monolith that no endpoint has
 *  produced since; that is why the "Участники" column was always empty. */
function participantNames(room: ChatRoom): string[] {
    const rows = (room as unknown as {
        participants?: Array<{
            user_id?: number;
            role?: string;
            user?: { full_name?: string; username?: string } | null;
        }>;
    }).participants ?? [];
    return rows.map((p) =>
        p.user?.full_name || p.user?.username || (p.user_id != null ? `#${p.user_id}` : ''),
    ).filter(Boolean);
}

/** A room deleted by its group owner. It stays in this admin listing on
 *  purpose — with every message and attachment — so moderation still has the
 *  full record; the badge is what tells it apart from a live chat. Replaces a
 *  check on `is_archived`, a field no endpoint has ever returned. */
function isDeleted(room: ChatRoom | null): boolean {
    return Boolean((room as unknown as { is_deleted?: boolean } | null)?.is_deleted);
}

const AdminChats = () => {
    const { t } = useTranslation();
    const [selectedRoomId, setSelectedRoomId] = useState<number | null>(null);

    // --- All rooms query ---
    const { data: rooms, isLoading: roomsLoading, error: roomsError } = useQuery({
        queryKey: ['admin-chats'],
        queryFn: messengerApi.admin.getAllRooms,
    });

    // --- Specific room messages query ---
    // Backend returns a flat ChatMessage[]; the room metadata is taken from
    // the already-loaded `rooms` list to avoid a second round-trip.
    const { data: messages, isLoading: messagesLoading } = useQuery({
        queryKey: ['admin-chat-messages', selectedRoomId],
        queryFn: () => selectedRoomId ? messengerApi.admin.getRoomMessages(selectedRoomId) : Promise.resolve([]),
        enabled: !!selectedRoomId,
    });

    const selectedRoom = rooms?.find((r) => r.id === selectedRoomId) ?? null;

    if (roomsLoading) return <div className="min-h-screen flex items-center justify-center">Loading...</div>;

    // Auth bypass check is usually handled by interceptor logic routing to /login
    // but we can show access denied if query fails
    if (roomsError) return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8 flex items-center justify-center">
                <div className="text-center">
                    <ShieldAlert className="h-16 w-16 text-destructive mx-auto mb-4" />
                    <h1 className="text-2xl font-bold text-destructive mb-2">{t('admin.chats.accessDeniedTitle', 'Access Denied')}</h1>
                    <p>{t('admin.chats.accessDenied', 'У вас нет прав администратора для просмотра этой страницы.')}</p>
                </div>
            </main>
            <Footer />
        </div>
    );

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8">
                {selectedRoomId ? (
                    // --- Room Messages View ---
                    <div className="bg-card rounded-lg border h-[600px] flex flex-col max-w-4xl mx-auto">
                        <div className="p-4 border-b flex items-center gap-4">
                            <button
                                onClick={() => setSelectedRoomId(null)}
                                className="p-2 -ml-2 rounded-lg hover:bg-accent transition-colors"
                            >
                                <ArrowLeft className="h-5 w-5" />
                            </button>
                            <div>
                                <h2 className="font-bold text-lg flex items-center">
                                    {selectedRoom?.room_type === 'secret' && <Lock className="h-4 w-4 mr-2 text-primary" />}
                                    {((selectedRoom as any)?.title || (selectedRoom as any)?.name) || `Чат #${selectedRoom?.id ?? selectedRoomId} (${selectedRoom?.room_type ?? '—'})`}
                                    {isDeleted(selectedRoom) && <Badge variant="outline" className="ml-3 text-xs border-destructive/40 text-destructive">{t('admin.chats.deleted', 'Удалён')}</Badge>}
                                </h2>
                                <p className="text-xs text-muted-foreground">
                                    {t('admin.chats.created', 'Создан')}: {selectedRoom?.created_at ? new Date(selectedRoom.created_at).toLocaleString() : ''}
                                </p>
                                {/* Who was in this chat. Shown here too, not just
                                    in the list, because moderating a history is
                                    meaningless without knowing the room's members
                                    — and they survive the room being deleted (see
                                    the backend's room_lifecycle: RoomParticipant
                                    rows are never touched). */}
                                {selectedRoom && participantNames(selectedRoom).length > 0 && (
                                    <p className="text-xs text-muted-foreground mt-0.5">
                                        {t('admin.chats.participants', 'Участники')}:{' '}
                                        <span className="text-foreground">
                                            {participantNames(selectedRoom).join(', ')}
                                        </span>
                                    </p>
                                )}
                            </div>
                        </div>

                        <div className="flex-1 overflow-y-auto p-4 space-y-4">
                            {messagesLoading ? (
                                <div className="text-center text-muted-foreground mt-10">{t('admin.chats.loadingMessages', 'Загрузка сообщений...')}</div>
                            ) : (messages?.length ?? 0) === 0 ? (
                                <div className="text-center text-muted-foreground mt-10">{t('admin.chats.noMessages', 'Нет сообщений в этом чате.')}</div>
                            ) : (
                                (messages ?? []).map((msg) => (
                                    <div key={msg.id} className="bg-muted p-3 rounded-lg text-sm max-w-[80%]">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="font-bold text-xs text-primary">
                                                {senderLabel(msg, t('admin.chats.system', 'Система'))}
                                            </span>
                                            <span className="text-[10px] text-muted-foreground">
                                                {new Date(msg.created_at).toLocaleString()}
                                            </span>
                                        </div>
                                        <div className="whitespace-pre-wrap">
                                            {/* E2EE is a room flag (`is_e2ee`), not a room_type — this
                                                used to test for `room_type === 'secret'`, a value the
                                                backend never returns (direct | group | department). */}
                                            {selectedRoom?.is_e2ee ? (
                                                t('admin.chats.encryptedPayload', '🔒 [Зашифрованный E2EE Payload]')
                                            ) : (
                                                (() => {
                                                    const decoded = decodeMessageText(msg);
                                                    if (typeof decoded === 'object') {
                                                        const isAudio = decoded.mime_type?.startsWith('audio/');
                                                        return (
                                                            <div className="flex flex-col gap-2 mt-1">
                                                                {decoded.text && <p className="text-sm mb-1">{decoded.text}</p>}
                                                                <div className="flex items-center gap-2 bg-background/50 border p-2 rounded-lg max-w-sm">
                                                                    {isAudio ? <Music className="h-5 w-5 opacity-70" /> : <FileText className="h-5 w-5 opacity-70" />}
                                                                    <span className="text-sm font-medium truncate flex-1" title={decoded.file_name}>{decoded.file_name || 'Файл'}</span>
                                                                    <a
                                                                        href={decoded.file_url}
                                                                        target="_blank"
                                                                        rel="noreferrer"
                                                                        download={decoded.file_name}
                                                                        className="ml-2 p-1.5 bg-background rounded-full hover:bg-accent transition-colors border"
                                                                        title="Скачать"
                                                                    >
                                                                        <Download className="h-4 w-4" />
                                                                    </a>
                                                                </div>
                                                                {isAudio && (
                                                                    <audio controls src={decoded.file_url} className="h-8 w-full max-w-[250px]" />
                                                                )}
                                                            </div>
                                                        );
                                                    }
                                                    return decoded;
                                                })()
                                            )}
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                ) : (
                    // --- All Rooms List ---
                    <>
                        <div className="mb-6 flex flex-col gap-4">
                            <BackToProfile />

                            <div className="flex items-center gap-2">
                                <MessageCircle className="h-8 w-8 text-primary" />
                                <h1 className="text-3xl font-bold">{t('admin.chats.title', 'Управление чатами')}</h1>
                            </div>
                        </div>
                        <div className="bg-card rounded-lg border">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>ID</TableHead>
                                        <TableHead>{t('admin.chats.type', 'Тип')}</TableHead>
                                        <TableHead>{t('admin.chats.name', 'Название')}</TableHead>
                                        <TableHead>{t('admin.chats.participants', 'Участники')}</TableHead>
                                        <TableHead>{t('admin.chats.created', 'Создан')}</TableHead>
                                        <TableHead>{t('admin.chats.actions', 'Действия')}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {rooms?.map((room) => (
                                        <TableRow key={room.id}>
                                            <TableCell className="font-medium">#{room.id}</TableCell>
                                            <TableCell className="space-x-2">
                                                <Badge variant={room.room_type === 'secret' ? "destructive" : room.room_type === 'group' ? "default" : "secondary"}>
                                                    {room.room_type}
                                                </Badge>
                                                {isDeleted(room) && (
                                                    <Badge variant="outline" className="text-destructive border-destructive/40 text-xs">{t('admin.chats.deleted', 'Удалён')}</Badge>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {((room as any).title || (room as any).name) || <span className="text-muted-foreground italic">{t('admin.chats.untitled', 'Без названия')}</span>}
                                            </TableCell>
                                            <TableCell>
                                                {(() => {
                                                    const names = participantNames(room);
                                                    if (!names.length) {
                                                        return <span className="text-muted-foreground">—</span>;
                                                    }
                                                    return (
                                                        <div className="text-xs" title={names.join(', ')}>
                                                            <span className="line-clamp-2 max-w-[260px]">
                                                                {names.join(', ')}
                                                            </span>
                                                            {/* Plain interpolation, not i18next's `count`
                                                                option — that one switches on plural rules
                                                                and would need _one/_few/_many keys, which
                                                                this page (all inline defaults, no locale
                                                                file) doesn't have. */}
                                                            <span className="text-muted-foreground">
                                                                {t('admin.chats.participantCount', '{{total}} чел.', { total: names.length })}
                                                            </span>
                                                        </div>
                                                    );
                                                })()}
                                            </TableCell>
                                            <TableCell className="text-sm">
                                                {new Date(room.created_at).toLocaleDateString()}
                                            </TableCell>
                                            <TableCell>
                                                <button
                                                    onClick={() => setSelectedRoomId(room.id)}
                                                    className="text-xs font-medium text-primary hover:underline"
                                                >
                                                    {t('admin.chats.viewHistory', 'Просмотр истории')}
                                                </button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                    {(!rooms || rooms.length === 0) && (
                                        <TableRow>
                                            <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                                                {t('admin.chats.noChats', 'Нет доступных чатов')}
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </TableBody>
                            </Table>
                        </div>
                    </>
                )}
            </main>
            <Footer />
        </div>
    );
};

export default AdminChats;
