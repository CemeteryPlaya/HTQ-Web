import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Server, ShieldCheck, Wand2, ChevronDown, ChevronRight } from 'lucide-react';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';

// GET  email/v1/accounts/connect-imap/?address=… — подсказка настроек
// POST email/v1/accounts/connect-imap/           — подключить
type Hint = {
    imap_host: string; imap_port: number; imap_ssl: boolean; imap_starttls: boolean;
    smtp_host: string; smtp_port: number; smtp_ssl: boolean; smtp_starttls: boolean;
    known: boolean; guessed: boolean;
    // true — адрес из корпоративного домена, и хост взят из настроек
    // платформы, а не угадан.
    corporate?: boolean;
};

type ApiError = { response?: { data?: { detail?: string } } };

const BLANK = {
    address: '', password: '', username: '', display_name: '',
    imap_host: '', imap_port: 993, imap_ssl: true, imap_starttls: false,
    smtp_host: '', smtp_port: 587, smtp_ssl: false, smtp_starttls: true,
};

/**
 * Подключение почтового аккаунта по IMAP — третий способ добавить почту,
 * рядом с OAuth (Gmail/Outlook) и корпоративным ящиком платформы. Нужен для
 * всего, что не покрывают первые два: личный ящик на своём хостинге, почта
 * подрядчика, второй домен компании.
 *
 * Настройки сервера подставляются по домену адреса, но помечаются как
 * догадка, когда провайдер неизвестен: выдавать предположение за факт —
 * верный способ получить непонятную ошибку входа.
 */
export const ConnectImapAccount: React.FC<{
    open: boolean;
    onClose: () => void;
}> = ({ open, onClose }) => {
    const { t } = useTranslation();
    const qc = useQueryClient();
    const [form, setForm] = useState({ ...BLANK });
    const [hint, setHint] = useState<Hint | null>(null);
    const [showAdvanced, setShowAdvanced] = useState(false);

    React.useEffect(() => {
        if (open) { setForm({ ...BLANK }); setHint(null); setShowAdvanced(false); }
    }, [open]);

    const set = <K extends keyof typeof BLANK>(key: K, value: typeof BLANK[K]) =>
        setForm((prev) => ({ ...prev, [key]: value }));

    // Подставляем настройки, когда адрес выглядит завершённым. Уже введённые
    // вручную значения не затираем — иначе правка адреса сбрасывала бы
    // подобранный руками хост.
    const applyHint = async (address: string) => {
        if (!address.includes('@') || !address.split('@')[1]) return;
        try {
            const { data } = await api.get<Hint>('email/v1/accounts/connect-imap/', {
                params: { address },
            });
            setHint(data);
            setForm((prev) => ({
                ...prev,
                imap_host: prev.imap_host || data.imap_host,
                imap_port: data.imap_port,
                imap_ssl: data.imap_ssl,
                imap_starttls: data.imap_starttls,
                smtp_host: prev.smtp_host || data.smtp_host,
                smtp_port: data.smtp_port,
                smtp_ssl: data.smtp_ssl,
                smtp_starttls: data.smtp_starttls,
            }));
        } catch {
            // Подсказка — удобство, а не необходимость: поля остаются
            // редактируемыми, и подключение возможно без неё.
        }
    };

    const mutation = useMutation({
        mutationFn: () => api.post('email/v1/accounts/connect-imap/', form),
        onSuccess: () => {
            toast.success(t('mail.imap.connected', 'Аккаунт подключён'));
            qc.invalidateQueries({ queryKey: ['email-accounts'] });
            onClose();
        },
        onError: (e: ApiError) => toast.error(
            e?.response?.data?.detail || t('mail.imap.error', 'Не удалось подключить аккаунт'),
            { duration: 12_000 },
        ),
    });

    const canSubmit = Boolean(form.address && form.password && form.imap_host && !mutation.isPending);

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Server className="h-4 w-4" />
                        {t('mail.imap.title', 'Подключить почту по IMAP')}
                    </DialogTitle>
                    <DialogDescription>
                        {t('mail.imap.description', 'Для почты, которой нет среди Google и Outlook: свой хостинг, почта подрядчика, другой домен. Реквизиты — те же, что вы вводите в почтовом клиенте.')}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    <div className="space-y-1.5">
                        <Label>{t('mail.imap.address', 'Адрес')}</Label>
                        <Input
                            value={form.address}
                            onChange={(e) => set('address', e.target.value)}
                            onBlur={(e) => applyHint(e.target.value.trim())}
                            placeholder="me@example.com"
                            autoComplete="username"
                        />
                        {hint?.guessed && (
                            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                                <Wand2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                                {t('mail.imap.guessed', 'Сервер подставлен по домену — проверьте адреса и порты, если вход не пройдёт.')}
                            </p>
                        )}
                        {hint?.known && !hint.corporate && (
                            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                                <Wand2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                                {t('mail.imap.known', 'Настройки этого провайдера подставлены автоматически.')}
                            </p>
                        )}
                        {hint?.corporate && (
                            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                                <Wand2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                                {t('mail.imap.corporate', 'Это корпоративный домен — подставлен рабочий адрес почтового сервера из настроек платформы.')}
                            </p>
                        )}
                    </div>

                    <div className="space-y-1.5">
                        <Label>{t('mail.imap.password', 'Пароль')}</Label>
                        <Input
                            type="password" value={form.password}
                            onChange={(e) => set('password', e.target.value)}
                            autoComplete="current-password"
                        />
                        <p className="text-xs text-muted-foreground">
                            {t('mail.imap.appPasswordHint', 'Многие провайдеры (Gmail, Яндекс, Mail.ru) требуют отдельный «пароль приложения», а не пароль от аккаунта.')}
                        </p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label>{t('mail.imap.imapHost', 'IMAP-сервер')}</Label>
                            <Input value={form.imap_host} onChange={(e) => set('imap_host', e.target.value)}
                                   placeholder="imap.example.com" />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('mail.imap.imapPort', 'IMAP-порт')}</Label>
                            <Input type="number" min={1} max={65535} value={form.imap_port}
                                   onChange={(e) => set('imap_port', Number(e.target.value))} />
                        </div>
                    </div>

                    <button
                        type="button"
                        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
                        onClick={() => setShowAdvanced((v) => !v)}
                    >
                        {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        {t('mail.imap.advanced', 'Дополнительно: SMTP, шифрование, логин')}
                    </button>

                    {showAdvanced && (
                        <div className="space-y-3 rounded-md border p-3">
                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1.5">
                                    <Label>{t('mail.imap.smtpHost', 'SMTP-сервер')}</Label>
                                    <Input value={form.smtp_host} onChange={(e) => set('smtp_host', e.target.value)}
                                           placeholder={t('mail.imap.smtpHostPlaceholder', 'пусто = как у IMAP')} />
                                </div>
                                <div className="space-y-1.5">
                                    <Label>{t('mail.imap.smtpPort', 'SMTP-порт')}</Label>
                                    <Input type="number" min={1} max={65535} value={form.smtp_port}
                                           onChange={(e) => set('smtp_port', Number(e.target.value))} />
                                </div>
                            </div>

                            <div className="grid gap-2 sm:grid-cols-2 text-sm">
                                <label className="flex items-center gap-2">
                                    <input type="checkbox" checked={form.imap_ssl}
                                           onChange={(e) => set('imap_ssl', e.target.checked)} />
                                    {t('mail.imap.imapSsl', 'IMAP: SSL/TLS')}
                                </label>
                                <label className="flex items-center gap-2">
                                    <input type="checkbox" checked={form.imap_starttls}
                                           onChange={(e) => set('imap_starttls', e.target.checked)} />
                                    {t('mail.imap.imapStarttls', 'IMAP: STARTTLS')}
                                </label>
                                <label className="flex items-center gap-2">
                                    <input type="checkbox" checked={form.smtp_ssl}
                                           onChange={(e) => set('smtp_ssl', e.target.checked)} />
                                    {t('mail.imap.smtpSsl', 'SMTP: SSL/TLS')}
                                </label>
                                <label className="flex items-center gap-2">
                                    <input type="checkbox" checked={form.smtp_starttls}
                                           onChange={(e) => set('smtp_starttls', e.target.checked)} />
                                    {t('mail.imap.smtpStarttls', 'SMTP: STARTTLS')}
                                </label>
                            </div>

                            <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1.5">
                                    <Label>{t('mail.imap.username', 'Логин')}</Label>
                                    <Input value={form.username} onChange={(e) => set('username', e.target.value)}
                                           placeholder={t('mail.imap.usernamePlaceholder', 'пусто = адрес целиком')} />
                                </div>
                                <div className="space-y-1.5">
                                    <Label>{t('mail.imap.displayName', 'Имя отправителя')}</Label>
                                    <Input value={form.display_name}
                                           onChange={(e) => set('display_name', e.target.value)} />
                                </div>
                            </div>
                        </div>
                    )}

                    <p className="flex items-start gap-2 text-xs text-muted-foreground">
                        <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                        {t('mail.imap.security', 'Платформа проверит вход на сервере перед сохранением. Пароль хранится зашифрованным и используется только для вашей почты.')}
                    </p>
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>{t('profile.cancel', 'Отмена')}</Button>
                    <Button onClick={() => mutation.mutate()} disabled={!canSubmit}>
                        {mutation.isPending
                            ? t('mail.imap.checking', 'Проверяем вход…')
                            : t('mail.imap.connect', 'Подключить')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

export default ConnectImapAccount;
