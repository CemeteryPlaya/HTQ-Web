import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
    Archive,
    KeyRound,
    Plus,
    Trash2,
    Undo2,
    AlertTriangle,
    AtSign } from 'lucide-react';

import api from '@/api/client';
import { BackToProfile } from '@/components/BackToProfile';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

// Backend contract — services/email/app/api/v1/mailboxes.py
type Mailbox = {
    id: number;
    user_id: number | null;
    local_part: string;
    domain: string;
    address: string;
    status: 'active' | 'archived' | 'deleted' | 'error';
    quota_mb: number;
    display_name: string | null;
    last_error: string | null;
    created_at: string;
    archived_at: string | null;
    deleted_at: string | null;
};

type Alias = { id: number; address: string; goto: string; active: number | boolean };

const STATUS_VARIANT: Record<Mailbox['status'], 'default' | 'destructive' | 'outline' | 'secondary'> = {
    active: 'default',
    archived: 'secondary',
    deleted: 'outline',
    error: 'destructive',
};

const generatePassword = (length = 16) => {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_-+=';
    const arr = new Uint32Array(length);
    crypto.getRandomValues(arr);
    return Array.from(arr, (n) => alphabet[n % alphabet.length]).join('');
};

const AdminMailboxes: React.FC = () => {
    const { t } = useTranslation();
    const qc = useQueryClient();

    const { data: mailboxes, isLoading, error } = useQuery({
        queryKey: ['admin-mailboxes'],
        queryFn: async () => (await api.get<Mailbox[]>('email/v1/mailboxes/?include_deleted=true')).data,
    });

    const [resetTarget, setResetTarget] = useState<Mailbox | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<Mailbox | null>(null);

    const archiveMutation = useMutation({
        mutationFn: (id: number) => api.post<Mailbox>(`email/v1/mailboxes/${id}/archive/`),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-mailboxes'] }); toast.success(t('admin.mailboxes.archived', 'Ящик архивирован')); },
        onError: (e: any) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    const restoreMutation = useMutation({
        mutationFn: (id: number) => api.post<Mailbox>(`email/v1/mailboxes/${id}/restore/`),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-mailboxes'] }); toast.success(t('admin.mailboxes.restored', 'Ящик восстановлен')); },
        onError: (e: any) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    const deleteMutation = useMutation({
        mutationFn: (id: number) => api.delete(`email/v1/mailboxes/${id}/`),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-mailboxes'] }); toast.success(t('admin.mailboxes.deleted', 'Ящик удалён окончательно')); setDeleteTarget(null); },
        onError: (e: any) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    if (isLoading) return <Shell><div className="text-center py-16">Loading…</div></Shell>;
    if (error) return <Shell><div className="text-center py-16 text-destructive">{(error as any)?.message || 'Error'}</div></Shell>;

    return (
        <Shell>
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-3xl font-bold">{t('admin.mailboxes.title', 'Корпоративные ящики')}</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {t('admin.mailboxes.subtitle', 'Управление ящиками на корпоративном домене (Mailcow). Удаление — двух-этапное: сначала «Архив», затем «Удалить окончательно».')}
                    </p>
                </div>
            </div>

            <Tabs defaultValue="mailboxes">
                <TabsList>
                    <TabsTrigger value="mailboxes">{t('admin.mailboxes.tabMailboxes', 'Ящики')}</TabsTrigger>
                    <TabsTrigger value="aliases">{t('admin.mailboxes.tabAliases', 'Алиасы')}</TabsTrigger>
                </TabsList>

                <TabsContent value="mailboxes" className="mt-4">
                    <div className="bg-card rounded-lg border overflow-x-auto">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>{t('admin.mailboxes.address', 'Адрес')}</TableHead>
                                    <TableHead>{t('admin.mailboxes.user', 'Пользователь')}</TableHead>
                                    <TableHead>{t('admin.mailboxes.statusLabel', 'Статус')}</TableHead>
                                    <TableHead>{t('admin.mailboxes.quota', 'Квота')}</TableHead>
                                    <TableHead>{t('admin.mailboxes.created', 'Создан')}</TableHead>
                                    <TableHead className="text-right">{t('admin.users.actions', 'Действия')}</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {(mailboxes ?? []).map((mb) => (
                                    <TableRow key={mb.id}>
                                        <TableCell className="font-mono text-sm">
                                            {mb.address}
                                            {mb.display_name && <span className="block text-xs text-muted-foreground">{mb.display_name}</span>}
                                            {mb.last_error && (
                                                <span className="flex items-center gap-1 text-xs text-destructive mt-1">
                                                    <AlertTriangle className="h-3 w-3" /> {mb.last_error}
                                                </span>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-xs text-muted-foreground">{mb.user_id ? `#${mb.user_id}` : '—'}</TableCell>
                                        <TableCell>
                                            <Badge variant={STATUS_VARIANT[mb.status]}>{mb.status}</Badge>
                                        </TableCell>
                                        <TableCell>{mb.quota_mb} MB</TableCell>
                                        <TableCell className="text-xs text-muted-foreground">{new Date(mb.created_at).toLocaleString()}</TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex justify-end gap-1">
                                                {mb.status === 'active' && (
                                                    <>
                                                        <Button size="sm" variant="ghost" onClick={() => setResetTarget(mb)}>
                                                            <KeyRound className="h-3.5 w-3.5" />
                                                        </Button>
                                                        <Button size="sm" variant="ghost" onClick={() => archiveMutation.mutate(mb.id)} disabled={archiveMutation.isPending}>
                                                            <Archive className="h-3.5 w-3.5" />
                                                        </Button>
                                                    </>
                                                )}
                                                {mb.status === 'archived' && (
                                                    <>
                                                        <Button size="sm" variant="ghost" onClick={() => restoreMutation.mutate(mb.id)} disabled={restoreMutation.isPending}>
                                                            <Undo2 className="h-3.5 w-3.5" />
                                                        </Button>
                                                        <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setDeleteTarget(mb)}>
                                                            <Trash2 className="h-3.5 w-3.5" />
                                                        </Button>
                                                    </>
                                                )}
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ))}
                                {(!mailboxes || mailboxes.length === 0) && (
                                    <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">{t('admin.mailboxes.empty', 'Ящиков нет')}</TableCell></TableRow>
                                )}
                            </TableBody>
                        </Table>
                    </div>
                </TabsContent>

                <TabsContent value="aliases" className="mt-4">
                    <AliasesTab />
                </TabsContent>
            </Tabs>

            {/* Reset password dialog */}
            <ResetPasswordDialog
                mailbox={resetTarget}
                onClose={() => setResetTarget(null)}
                onDone={() => qc.invalidateQueries({ queryKey: ['admin-mailboxes'] })}
            />

            {/* Confirm permanent delete */}
            <Dialog open={Boolean(deleteTarget)} onOpenChange={(o) => !o && setDeleteTarget(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t('admin.mailboxes.confirmDeleteTitle', 'Удалить окончательно?')}</DialogTitle>
                        <DialogDescription>
                            {t('admin.mailboxes.confirmDeleteDesc', 'Ящик и все его данные будут удалены из Mailcow безвозвратно. Это второй этап двух-стадийного удаления (после архивирования).')}
                        </DialogDescription>
                    </DialogHeader>
                    <p className="font-mono text-sm bg-muted/50 p-3 rounded">{deleteTarget?.address}</p>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setDeleteTarget(null)}>{t('profile.cancel', 'Отмена')}</Button>
                        <Button
                            variant="destructive"
                            onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
                            disabled={deleteMutation.isPending}
                        >
                            {t('admin.mailboxes.deleteConfirmBtn', 'Удалить навсегда')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </Shell>
    );
};

export default AdminMailboxes;

// ─── Subcomponents ───────────────────────────────────────────────────────────

const Shell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <div className="min-h-screen bg-background flex flex-col">
        <Header />
        <main className="flex-1 container mx-auto px-4 py-8">
            <BackToProfile className="mb-4" />
            {children}
        </main>
        <Footer />
    </div>
);

const ResetPasswordDialog: React.FC<{
    mailbox: Mailbox | null;
    onClose: () => void;
    onDone: () => void;
}> = ({ mailbox, onClose, onDone }) => {
    const { t } = useTranslation();
    const [pwd, setPwd] = useState('');
    const [forceChange, setForceChange] = useState(true);

    React.useEffect(() => {
        if (mailbox) { setPwd(''); setForceChange(true); }
    }, [mailbox]);

    const mutation = useMutation({
        mutationFn: async () => {
            const id = mailbox!.id;
            const res = await api.post<Mailbox & { generated_password?: string | null }>(
                `email/v1/mailboxes/${id}/reset-password/`,
                { new_password: pwd, force_change: forceChange },
            );
            return res.data;
        },
        onSuccess: (data) => {
            const p = data.generated_password;
            if (p) {
                toast.success(`${t('admin.mailboxes.passwordResetOnce', 'Новый пароль (показывается один раз)')}: ${p}`, { duration: 30_000 });
            } else {
                toast.success(t('admin.users.passwordReset', 'Пароль сброшен'));
            }
            onDone();
            onClose();
        },
        onError: (e: any) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    return (
        <Dialog open={Boolean(mailbox)} onOpenChange={(o) => !o && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{t('admin.mailboxes.resetTitle', 'Сброс пароля ящика')}</DialogTitle>
                    <DialogDescription className="font-mono">{mailbox?.address}</DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                    <Label>{t('admin.mailboxes.newPassword', 'Новый пароль')}</Label>
                    <div className="flex gap-2">
                        <Input
                            type="text"
                            value={pwd}
                            onChange={(e) => setPwd(e.target.value)}
                            placeholder={t('admin.users.mailboxPasswordPlaceholder', 'пусто = автогенерация')}
                            minLength={pwd ? 8 : undefined}
                        />
                        <Button type="button" variant="secondary" onClick={() => setPwd(generatePassword())}>
                            {t('admin.users.mailboxGenPassword', 'Сгенерировать')}
                        </Button>
                    </div>
                    <label className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={forceChange} onChange={(e) => setForceChange(e.target.checked)} />
                        {t('admin.mailboxes.forceChange', 'Заставить сменить при следующем входе')}
                    </label>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>{t('profile.cancel', 'Отмена')}</Button>
                    <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                        {mutation.isPending ? t('common.saving', 'Сохранение...') : t('admin.users.resetPasswordBtn', 'Сбросить пароль')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

const AliasesTab: React.FC = () => {
    const { t } = useTranslation();
    const qc = useQueryClient();
    const [createOpen, setCreateOpen] = useState(false);
    const [address, setAddress] = useState('');
    const [goto_, setGoto] = useState('');

    const { data, isLoading, error } = useQuery({
        queryKey: ['admin-mailbox-aliases'],
        queryFn: async () => (await api.get<Alias[]>('email/v1/mailboxes/aliases/')).data,
    });

    const createMutation = useMutation({
        mutationFn: () => api.post('email/v1/mailboxes/aliases/', { address, goto: goto_, active: true }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['admin-mailbox-aliases'] });
            toast.success(t('admin.mailboxes.aliasCreated', 'Алиас создан'));
            setAddress(''); setGoto(''); setCreateOpen(false);
        },
        onError: (e: any) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    const deleteMutation = useMutation({
        mutationFn: (id: number) => api.delete(`email/v1/mailboxes/aliases/${id}/`),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-mailbox-aliases'] }); toast.success(t('admin.mailboxes.aliasDeleted', 'Алиас удалён')); },
        onError: (e: any) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    return (
        <>
            <div className="flex justify-end mb-3">
                <Button onClick={() => setCreateOpen(true)} className="gap-2">
                    <Plus className="h-4 w-4" /> {t('admin.mailboxes.createAlias', 'Создать алиас')}
                </Button>
            </div>
            <div className="bg-card rounded-lg border overflow-x-auto">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('admin.mailboxes.aliasAddress', 'Алиас')}</TableHead>
                            <TableHead>{t('admin.mailboxes.aliasGoto', 'Куда пересылается')}</TableHead>
                            <TableHead>{t('admin.mailboxes.aliasActive', 'Активен')}</TableHead>
                            <TableHead className="text-right">{t('admin.users.actions', 'Действия')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {isLoading && <TableRow><TableCell colSpan={4} className="text-center py-8">Loading…</TableCell></TableRow>}
                        {error && <TableRow><TableCell colSpan={4} className="text-center py-8 text-destructive">{(error as any)?.message || 'Mailcow unreachable'}</TableCell></TableRow>}
                        {(data ?? []).map((a) => (
                            <TableRow key={a.id}>
                                <TableCell className="font-mono">{a.address}</TableCell>
                                <TableCell className="font-mono text-sm">{a.goto}</TableCell>
                                <TableCell>{a.active ? '✓' : '✗'}</TableCell>
                                <TableCell className="text-right">
                                    <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => deleteMutation.mutate(a.id)}>
                                        <Trash2 className="h-3.5 w-3.5" />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                        {(!isLoading && !error && (!data || data.length === 0)) && (
                            <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">{t('admin.mailboxes.aliasesEmpty', 'Алиасов нет')}</TableCell></TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t('admin.mailboxes.createAlias', 'Создать алиас')}</DialogTitle>
                        <DialogDescription>
                            {t('admin.mailboxes.aliasHint', 'Адрес-алиас принимает почту и пересылает её на один или несколько ящиков (через запятую).')}
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label className="flex items-center gap-1"><AtSign className="h-3.5 w-3.5" />{t('admin.mailboxes.aliasAddress', 'Алиас')}</Label>
                            <Input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="info@yourdomain.com" />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('admin.mailboxes.aliasGoto', 'Куда пересылается')}</Label>
                            <Input value={goto_} onChange={(e) => setGoto(e.target.value)} placeholder="i.ivanov@yourdomain.com,p.petrov@yourdomain.com" />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setCreateOpen(false)}>{t('profile.cancel', 'Отмена')}</Button>
                        <Button onClick={() => createMutation.mutate()} disabled={!address || !goto_ || createMutation.isPending}>
                            {createMutation.isPending ? t('common.saving', 'Сохранение...') : t('admin.users.createBtn', 'Создать')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
};
