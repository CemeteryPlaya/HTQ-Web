import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import i18next from 'i18next';
import { Link } from 'react-router-dom';
import { MessageCircle, ShieldAlert, ArrowLeft, Lock, FileText, Download, Music } from 'lucide-react';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { messengerApi } from '../features/messenger/api/messengerApi';
import { ChatMessage } from '../features/messenger/types';

function decodeMessageText(msg: ChatMessage | { encrypted_data: string;[key: string]: unknown }): { text: string; file_url?: string; file_name?: string; mime_type?: string; } | string {
    if (!msg.encrypted_data) return '';
    try {
        const binString = atob(msg.encrypted_data);
        const bytes = Uint8Array.from(binString, (m) => m.codePointAt(0)!);
        const jsonStr = new TextDecoder().decode(bytes);
        const json = JSON.parse(jsonStr);
        if (msg.msg_type === 'file') {
            return json;
        }
        return json.text || json.body || '';
    } catch {
        try {
            const binString = atob(msg.encrypted_data);
            const bytes = Uint8Array.from(binString, (m) => m.codePointAt(0)!);
            return new TextDecoder().decode(bytes);
        } catch {
            return i18next.t('admin.chats.encryptedMessage', '🔒 Зашифрованное сообщение');
        }
    }
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
                                    {(selectedRoom as any)?.is_archived && <Badge variant="outline" className="ml-3 text-xs border-muted text-muted-foreground">{t('admin.chats.archive', 'Архив')}</Badge>}
                                </h2>
                                <p className="text-xs text-muted-foreground">
                                    {t('admin.chats.created', 'Создан')}: {selectedRoom?.created_at ? new Date(selectedRoom.created_at).toLocaleString() : ''}
                                </p>
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
                                                {msg.sender ? `${(msg.sender as any).full_name || [(msg.sender as any).first_name, (msg.sender as any).last_name].filter(Boolean).join(' ') || msg.sender.username} (ID: ${(msg.sender as any).user_id ?? msg.sender.id})` : t('admin.chats.system', 'Система')}
                                            </span>
                                            <span className="text-[10px] text-muted-foreground">
                                                {new Date(msg.created_at).toLocaleString()}
                                            </span>
                                        </div>
                                        <div className="whitespace-pre-wrap">
                                            {selectedRoom?.room_type === 'secret' ? (
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
                            <Link
                                to="/myprofile"
                                className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
                            >
                                <ArrowLeft className="h-4 w-4" />
                                {t('hr.backToMain', 'Назад в профиль')}
                            </Link>

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
                                                {(room as any).is_archived && (
                                                    <Badge variant="outline" className="text-muted-foreground border-muted text-xs">{t('admin.chats.archive', 'Архив')}</Badge>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {((room as any).title || (room as any).name) || <span className="text-muted-foreground italic">{t('admin.chats.untitled', 'Без названия')}</span>}
                                            </TableCell>
                                            <TableCell>
                                                <div className="max-w-[200px] truncate text-xs">
                                                    {(room.memberships ?? [])
                                                        .map(m => m?.user?.full_name || m?.user?.username || '')
                                                        .filter(Boolean)
                                                        .join(', ') || '—'}
                                                </div>
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
