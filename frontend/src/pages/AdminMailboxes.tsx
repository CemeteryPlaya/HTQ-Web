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
    ArrowDownToLine,
    ArrowUpFromLine,
    CheckCircle2,
    Info,
    RefreshCw,
    ServerCog,
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
import { MailConnectionSettings } from '@/components/mail/MailConnectionSettings';
import { MailboxLookupNotice } from '@/components/mail/MailboxLookupNotice';
import { MailboxCoverage } from '@/components/mail/MailboxCoverage';
import {
    fetchMailboxLookup,
    lookupIsAnswerable,
    lookupSubmitsAttach,
    lookupVerdict,
    useDebounced,
} from '@/components/mail/mailboxLookup';

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

// GET email/v1/mailboxes/status/ — что умеет подключённый почтовый сервер.
// Форма создания читает это, чтобы не обещать невозможного: сервер без
// админ-API ящик не заведёт, он может только проверить существующий.
type MailboxStatus = {
    provisioner: 'mailcow' | 'imap' | 'none';
    domain: string;
    mailcow_api_configured: boolean;
    imap_configured: boolean;
    imap_host: string;
    imap_port: number;
    can_create_remotely: boolean;
    can_list_remote: boolean;
};

type ReconcileDiff = {
    kind: 'only_local' | 'only_remote' | 'mismatched' | 'unlinked';
    address: string;
    mailbox_id: number | null;
    user_id: number | null;
    local: Record<string, unknown> | null;
    remote: Record<string, unknown> | null;
    fields: string[];
    detail: string | null;
    action: string | null;
    error: string | null;
};

// Ошибка axios в том объёме, который эта страница реально читает. `mailbox`
// приезжает вместе с 502 от POST /mailboxes/: строка создана, но почтовый
// сервер отказал — список нужно обновить, иначе админ создаст дубль.
type ApiError = { response?: { data?: { detail?: string; mailbox?: Mailbox } } };

type ReconcileReport = {
    mode: 'listing' | 'probe' | 'unavailable';
    provisioner: string;
    domain: string;
    applied: boolean;
    direction: string;
    checked_local: number;
    checked_remote: number;
    in_sync: number;
    counts: { only_local: number; only_remote: number; mismatched: number;
              unlinked: number; linked: number };
    differences: ReconcileDiff[];
    errors: string[];
    finished_at: string;
};

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

    const { data: status } = useQuery({
        queryKey: ['admin-mailbox-status'],
        queryFn: async () => (await api.get<MailboxStatus>('email/v1/mailboxes/status/')).data,
        staleTime: 60_000,
    });

    const [resetTarget, setResetTarget] = useState<Mailbox | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<Mailbox | null>(null);
    const [createOpen, setCreateOpen] = useState(false);

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
            <div className="flex items-start justify-between gap-4 mb-6 flex-wrap">
                <div>
                    <h1 className="text-3xl font-bold">{t('admin.mailboxes.title', 'Корпоративные ящики')}</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {t('admin.mailboxes.subtitle', 'Управление ящиками на корпоративном домене. Удаление — двух-этапное: сначала «Архив», затем «Удалить окончательно».')}
                    </p>
                </div>
                <Button onClick={() => setCreateOpen(true)} className="gap-2">
                    <Plus className="h-4 w-4" /> {t('admin.mailboxes.create', 'Создать ящик')}
                </Button>
            </div>

            <ConnectionBanner status={status} />

            <Tabs defaultValue="mailboxes">
                <TabsList>
                    <TabsTrigger value="mailboxes">{t('admin.mailboxes.tabMailboxes', 'Ящики')}</TabsTrigger>
                    <TabsTrigger value="connection">{t('admin.mailboxes.tabConnection', 'Подключение')}</TabsTrigger>
                    <TabsTrigger value="coverage">{t('admin.mailboxes.tabCoverage', 'Покрытие')}</TabsTrigger>
                    <TabsTrigger value="reconcile">{t('admin.mailboxes.tabReconcile', 'Сверка')}</TabsTrigger>
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

                <TabsContent value="connection" className="mt-4">
                    <MailConnectionSettings />
                </TabsContent>

                <TabsContent value="coverage" className="mt-4">
                    <MailboxCoverage />
                </TabsContent>

                <TabsContent value="reconcile" className="mt-4">
                    <ReconcileTab status={status} />
                </TabsContent>

                <TabsContent value="aliases" className="mt-4">
                    <AliasesTab />
                </TabsContent>
            </Tabs>

            {/* Create mailbox dialog */}
            <CreateMailboxDialog
                open={createOpen}
                status={status}
                onClose={() => setCreateOpen(false)}
                onDone={() => qc.invalidateQueries({ queryKey: ['admin-mailboxes'] })}
            />

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

// Состояние подключения к почтовому серверу. Без него админ не может понять,
// почему «Создать ящик» ведёт себя по-разному: с Mailcow-API ящик реально
// заводится, на голом IMAP — только проверяется существующий, без настроек —
// остаётся лишь строкой в базе.
const ConnectionBanner: React.FC<{ status?: MailboxStatus }> = ({ status }) => {
    const { t } = useTranslation();
    if (!status) return null;

    if (status.provisioner === 'none') {
        return (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <AlertTriangle className="h-4 w-4 mt-0.5 text-amber-600 shrink-0" />
                <span>
                    {t('admin.mailboxes.bannerNone', 'Почтовый сервер не подключён: ящики заводятся только в базе платформы и на сервере не появятся. Задайте MAILCOW_API_URL + MAILCOW_API_KEY либо IMAP_HOST.')}
                </span>
            </div>
        );
    }

    const isImap = status.provisioner === 'imap';
    return (
        <div className="mb-4 flex items-start gap-2 rounded-lg border bg-muted/40 p-3 text-sm">
            <ServerCog className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground">
                {isImap
                    ? t('admin.mailboxes.bannerImap', 'Режим IMAP/SMTP ({{host}}:{{port}}, домен {{domain}}). Создать ящик по IMAP нельзя — заведите его на почтовом сервере, укажите здесь адрес и пароль, платформа проверит учётку и привяжет ящик.', { host: status.imap_host, port: status.imap_port, domain: status.domain || '—' })
                    : t('admin.mailboxes.bannerMailcow', 'Режим Mailcow API (домен {{domain}}). Ящики создаются, архивируются и удаляются на почтовом сервере по-настоящему.', { domain: status.domain || '—' })}
            </span>
        </div>
    );
};

const CreateMailboxDialog: React.FC<{
    open: boolean;
    status?: MailboxStatus;
    onClose: () => void;
    onDone: () => void;
}> = ({ open, status, onClose, onDone }) => {
    const { t } = useTranslation();
    const [localPart, setLocalPart] = useState('');
    const [firstName, setFirstName] = useState('');
    const [lastName, setLastName] = useState('');
    const [password, setPassword] = useState('');
    const [quota, setQuota] = useState('');
    const [userId, setUserId] = useState('');

    React.useEffect(() => {
        if (open) {
            setLocalPart(''); setFirstName(''); setLastName('');
            setPassword(''); setQuota(''); setUserId('');
        }
    }, [open]);

    // Сверка: тот же вопрос, который бэкенд задаст себе при создании, только
    // задаётся заранее — чтобы админ увидел «ящик уже есть» до нажатия кнопки,
    // а не после. Debounce, иначе запрос уходит на каждую букву.
    const dLocalPart = useDebounced(localPart, 400);
    const dFirstName = useDebounced(firstName, 400);
    const dLastName = useDebounced(lastName, 400);
    const dUserId = useDebounced(userId, 400);
    const lookupArgs = {
        localPart: dLocalPart,
        firstName: dFirstName,
        lastName: dLastName,
        userId: dUserId ? Number(dUserId) : null,
    };
    const { data: lookup, isFetching: lookupLoading } = useQuery({
        queryKey: ['mailbox-lookup', dLocalPart, dFirstName, dLastName, dUserId],
        queryFn: () => fetchMailboxLookup(lookupArgs),
        enabled: open && lookupIsAnswerable(lookupArgs),
        staleTime: 15_000,
        retry: false,
    });

    // На сервере без админ-API ящик уже существует — платформа обязана
    // проверить его логином, поэтому пароль там не опционален. Сверка может
    // потребовать пароль и отдельно: найденный ящик подключается только
    // проверенной учёткой.
    const passwordRequired = (status ? !status.can_create_remotely && status.provisioner !== 'none' : false)
        || lookupVerdict(lookup) === 'needs-password';
    const willAttach = lookupSubmitsAttach(lookup);

    const mutation = useMutation({
        mutationFn: async () => {
            const res = await api.post<Mailbox & {
                generated_password?: string | null;
                attached?: boolean;
                detail?: string | null;
            }>(
                'email/v1/mailboxes/',
                {
                    local_part: localPart.trim(),
                    first_name: firstName.trim(),
                    last_name: lastName.trim(),
                    password,
                    quota_mb: quota ? Number(quota) : 0,
                    user_id: userId ? Number(userId) : null,
                },
            );
            return res.data;
        },
        onSuccess: (data) => {
            const pwd = data.generated_password;
            if (data.attached) {
                // Пароля здесь нет и быть не должно: ящик существовал до нас,
                // сотрудник входит в него тем паролем, что у него уже есть.
                toast.success(
                    `${t('admin.mailboxes.attached', 'Подключён существующий ящик')}: ${data.address}`,
                    { duration: 15_000 },
                );
            } else if (pwd) {
                toast.success(
                    `${t('admin.mailboxes.created', 'Ящик создан')}: ${data.address}\n${t('admin.mailboxes.passwordOnce', 'Пароль (показывается один раз)')}: ${pwd}`,
                    { duration: 30_000 },
                );
            } else {
                toast.success(`${t('admin.mailboxes.created', 'Ящик создан')}: ${data.address}`);
            }
            onDone();
            onClose();
        },
        onError: (e: ApiError) => {
            const detail = e?.response?.data?.detail;
            const mailbox = e?.response?.data?.mailbox;
            // 502 = строка создана, но почтовый сервер отказал. Список нужно
            // обновить, иначе админ создаст дубль, не увидев строку в ошибке.
            if (mailbox) onDone();
            toast.error(detail || t('admin.mailboxes.createError', 'Не удалось создать ящик'), { duration: 15_000 });
        },
    });

    const canSubmit = Boolean(
        (localPart.trim() || (firstName.trim() && lastName.trim()))
        && (!passwordRequired || password)
        && !mutation.isPending,
    );

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{t('admin.mailboxes.create', 'Создать ящик')}</DialogTitle>
                    <DialogDescription>
                        {passwordRequired
                            ? t('admin.mailboxes.createDescImap', 'Ящик должен быть уже заведён на почтовом сервере. Укажите его адрес и пароль — платформа проверит учётку по IMAP и привяжет ящик.')
                            : t('admin.mailboxes.createDesc', 'Адрес можно не указывать — он соберётся из имени и фамилии (Иван Иванов → i.ivanov). Пустой пароль означает автогенерацию.')}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    <div className="space-y-1.5">
                        <Label className="flex items-center gap-1">
                            <AtSign className="h-3.5 w-3.5" />{t('admin.mailboxes.localPart', 'Адрес (до @)')}
                        </Label>
                        <div className="flex items-center gap-2">
                            <Input
                                value={localPart}
                                onChange={(e) => setLocalPart(e.target.value)}
                                placeholder={t('admin.mailboxes.localPartPlaceholder', 'i.ivanov — пусто = из имени')}
                            />
                            <span className="text-sm text-muted-foreground whitespace-nowrap">
                                @{status?.domain || '…'}
                            </span>
                        </div>
                        <MailboxLookupNotice lookup={lookup} loading={lookupLoading} />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                            <Label>{t('admin.users.firstName', 'Имя')}</Label>
                            <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder={t('admin.mailboxes.firstNamePlaceholder')} />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('admin.users.lastName', 'Фамилия')}</Label>
                            <Input value={lastName} onChange={(e) => setLastName(e.target.value)} placeholder={t('admin.mailboxes.lastNamePlaceholder')} />
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <Label>
                            {t('admin.mailboxes.password', 'Пароль')}
                            {passwordRequired && <span className="text-destructive"> *</span>}
                        </Label>
                        <div className="flex gap-2">
                            <Input
                                type="text"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder={passwordRequired
                                    ? t('admin.mailboxes.passwordRequiredPlaceholder', 'пароль ящика на почтовом сервере')
                                    : t('admin.users.mailboxPasswordPlaceholder', 'пусто = автогенерация')}
                            />
                            {!passwordRequired && (
                                <Button type="button" variant="secondary" onClick={() => setPassword(generatePassword())}>
                                    {t('admin.users.mailboxGenPassword', 'Сгенерировать')}
                                </Button>
                            )}
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                            <Label>{t('admin.mailboxes.quota', 'Квота')} (MB)</Label>
                            <Input
                                type="number" min={0} value={quota}
                                onChange={(e) => setQuota(e.target.value)}
                                placeholder={t('admin.mailboxes.quotaPlaceholder', 'пусто = по умолчанию')}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('admin.mailboxes.userId', 'ID пользователя')}</Label>
                            <Input
                                type="number" min={1} value={userId}
                                onChange={(e) => setUserId(e.target.value)}
                                placeholder={t('admin.mailboxes.userIdPlaceholder', 'необязательно')}
                            />
                        </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                        {t('admin.mailboxes.userIdHint', 'С указанным пользователем ящик появится у него в разделе «Почта»: платформа заведёт для него почтовый аккаунт.')}
                    </p>
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>{t('profile.cancel', 'Отмена')}</Button>
                    <Button onClick={() => mutation.mutate()} disabled={!canSubmit}>
                        {mutation.isPending
                            ? t('common.saving', 'Сохранение...')
                            : willAttach
                                ? t('admin.mailboxes.attachBtn', 'Подключить')
                                : t('admin.users.createBtn', 'Создать')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

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

const DIFF_VARIANT: Record<ReconcileDiff['kind'], 'default' | 'destructive' | 'outline' | 'secondary'> = {
    only_local: 'destructive',
    only_remote: 'secondary',
    mismatched: 'outline',
    unlinked: 'default',
};

const ReconcileTab: React.FC<{ status?: MailboxStatus }> = ({ status }) => {
    const { t } = useTranslation();
    const qc = useQueryClient();
    const [report, setReport] = useState<ReconcileReport | null>(null);

    const DIFF_LABEL: Record<ReconcileDiff['kind'], string> = {
        only_local: t('admin.mailboxes.diffOnlyLocal', 'Только в платформе'),
        only_remote: t('admin.mailboxes.diffOnlyRemote', 'Только на сервере'),
        mismatched: t('admin.mailboxes.diffMismatched', 'Расходятся'),
        unlinked: t('admin.mailboxes.diffUnlinked', 'Нашёлся владелец'),
    };

    const runMutation = useMutation({
        mutationFn: async (direction: 'report' | 'pull' | 'push' | 'both') => {
            if (direction === 'report') {
                return (await api.get<ReconcileReport>('email/v1/mailboxes/reconcile/')).data;
            }
            return (await api.post<ReconcileReport>('email/v1/mailboxes/reconcile/', {
                apply: true, direction,
            })).data;
        },
        onSuccess: (data, direction) => {
            setReport(data);
            if (direction !== 'report') {
                qc.invalidateQueries({ queryKey: ['admin-mailboxes'] });
                toast.success(t('admin.mailboxes.reconcileApplied', 'Сверка применена'));
            }
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    const busy = runMutation.isPending;
    const hasDiffs = Boolean(report && report.differences.length > 0);
    const serverUnavailable = report?.mode === 'unavailable';

    return (
        <div className="space-y-4">
            <div className="rounded-lg border bg-card p-4">
                <div className="flex items-start gap-2 text-sm text-muted-foreground">
                    <Info className="h-4 w-4 mt-0.5 shrink-0" />
                    <p>
                        {t('admin.mailboxes.reconcileHelp', 'Сверка сравнивает ящики платформы с ящиками почтового сервера в обе стороны. Сначала посмотрите отчёт — он ничего не меняет, — и только потом применяйте выбранное направление. Заодно сверка ищет владельцев: если адрес ящика совпадает с email сотрудника, при применении ящик привяжется к нему сам и появится у него в почте.')}
                    </p>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                    <Button onClick={() => runMutation.mutate('report')} disabled={busy} className="gap-2">
                        <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
                        {t('admin.mailboxes.reconcileRun', 'Проверить расхождения')}
                    </Button>
                    <Button
                        variant="secondary" className="gap-2"
                        disabled={busy || !hasDiffs}
                        onClick={() => runMutation.mutate('pull')}
                        title={t('admin.mailboxes.reconcilePullHint', 'Источник правды — почтовый сервер: недостающие ящики импортируются в платформу, отличия подтягиваются с сервера.')}
                    >
                        <ArrowDownToLine className="h-4 w-4" />
                        {t('admin.mailboxes.reconcilePull', 'Принять данные сервера')}
                    </Button>
                    <Button
                        variant="secondary" className="gap-2"
                        disabled={busy || !hasDiffs || !status?.can_create_remotely}
                        onClick={() => runMutation.mutate('push')}
                        title={status?.can_create_remotely
                            ? t('admin.mailboxes.reconcilePushHint', 'Источник правды — платформа: недостающие ящики создаются на сервере, отличия отправляются туда же.')
                            : t('admin.mailboxes.reconcilePushDisabled', 'Текущий почтовый сервер не умеет создавать ящики через API.')}
                    >
                        <ArrowUpFromLine className="h-4 w-4" />
                        {t('admin.mailboxes.reconcilePush', 'Записать данные платформы')}
                    </Button>
                </div>
            </div>

            {report && (
                <div className="rounded-lg border bg-card p-4 space-y-3">
                    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
                        <span className="text-muted-foreground">
                            {t('admin.mailboxes.reconcileMode', 'Режим')}:{' '}
                            <span className="font-medium text-foreground">{report.mode}</span>
                        </span>
                        <span className="text-muted-foreground">
                            {t('admin.mailboxes.reconcileLocal', 'В платформе')}:{' '}
                            <span className="font-medium text-foreground">{report.checked_local}</span>
                        </span>
                        <span className="text-muted-foreground">
                            {t('admin.mailboxes.reconcileRemote', 'На сервере')}:{' '}
                            <span className="font-medium text-foreground">{report.checked_remote}</span>
                        </span>
                        <span className="text-muted-foreground">
                            {t('admin.mailboxes.reconcileInSync', 'Совпадают')}:{' '}
                            <span className="font-medium text-foreground">{report.in_sync}</span>
                        </span>
                        {report.counts.unlinked > 0 && (
                            <span className="text-muted-foreground">
                                {report.applied
                                    ? t('admin.mailboxes.reconcileLinked', 'Привязано к сотрудникам')
                                    : t('admin.mailboxes.reconcileToLink', 'Найдены владельцы')}:{' '}
                                <span className="font-medium text-foreground">
                                    {report.applied ? report.counts.linked : report.counts.unlinked}
                                </span>
                            </span>
                        )}
                    </div>

                    {report.mode === 'probe' && (
                        <p className="text-xs text-muted-foreground">
                            {t('admin.mailboxes.reconcileProbeNote', 'Сервер не отдаёт список ящиков, поэтому проверены только известные платформе ящики — живым IMAP-логином. Ящики, заведённые на сервере мимо платформы, в этом режиме увидеть невозможно.')}
                        </p>
                    )}

                    {report.errors.length > 0 && (
                        <div className={`flex items-start gap-2 rounded-md p-2 text-xs ${serverUnavailable ? 'bg-destructive/10 text-destructive' : 'bg-muted/50 text-muted-foreground'}`}>
                            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                            <div className="space-y-0.5">
                                {report.errors.map((err, i) => <div key={i}>{err}</div>)}
                            </div>
                        </div>
                    )}

                    {!hasDiffs && !serverUnavailable && (
                        <div className="flex items-center gap-2 py-6 justify-center text-sm text-muted-foreground">
                            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                            {t('admin.mailboxes.reconcileClean', 'Расхождений нет — платформа и почтовый сервер совпадают.')}
                        </div>
                    )}

                    {hasDiffs && (
                        <div className="overflow-x-auto">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>{t('admin.mailboxes.address', 'Адрес')}</TableHead>
                                        <TableHead>{t('admin.mailboxes.diffKind', 'Расхождение')}</TableHead>
                                        <TableHead>{t('admin.mailboxes.diffDetail', 'Подробности')}</TableHead>
                                        <TableHead>{t('admin.mailboxes.diffAction', 'Действие')}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {report.differences.map((d) => (
                                        <TableRow key={`${d.kind}-${d.address}`}>
                                            <TableCell className="font-mono text-sm">{d.address}</TableCell>
                                            <TableCell>
                                                <Badge variant={DIFF_VARIANT[d.kind]}>{DIFF_LABEL[d.kind]}</Badge>
                                            </TableCell>
                                            <TableCell className="text-xs text-muted-foreground">
                                                {d.detail}
                                                {d.error && <span className="block text-destructive mt-1">{d.error}</span>}
                                            </TableCell>
                                            <TableCell className="text-xs">
                                                {d.action
                                                    ? <span className="text-emerald-600">{d.action}</span>
                                                    : <span className="text-muted-foreground">—</span>}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    )}
                </div>
            )}
        </div>
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
