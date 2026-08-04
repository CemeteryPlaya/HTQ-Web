import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AtSign, Link2, Unlink, ShieldCheck } from 'lucide-react';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';

// GET/POST/DELETE email/v1/accounts/connect-corporate/
// Обычному пользователю отдаётся только необходимое — без адресов серверов.
type ConnectInfo = {
    allowed: boolean;
    domain: string;
    mailbox: {
        id: number;
        address: string;
        status: 'active' | 'archived' | 'deleted' | 'error';
        last_error: string | null;
    } | null;
};

type ApiError = { response?: { data?: { detail?: string } } };

/**
 * Самоподключение корпоративного ящика сотрудником.
 *
 * Ящик заводит почтовый администратор, сотрудник знает от него пароль — здесь
 * он привязывает ящик к своей учётной записи, не дожидаясь админа платформы.
 * Платформа проверяет пару живым IMAP-входом ДО сохранения, поэтому нерабочая
 * привязка не создаётся.
 *
 * Блок сам скрывается, если админ не включил режим, — чтобы не показывать
 * действие, которое заведомо вернёт отказ.
 */
export const ConnectCorporateMailbox: React.FC<{ className?: string }> = ({ className }) => {
    const { t } = useTranslation();
    const qc = useQueryClient();
    const [open, setOpen] = useState(false);
    const [address, setAddress] = useState('');
    const [password, setPassword] = useState('');

    const { data: info } = useQuery({
        queryKey: ['corporate-mailbox-connect'],
        queryFn: async () => (await api.get<ConnectInfo>('email/v1/accounts/connect-corporate/')).data,
        staleTime: 60_000,
        retry: false,
    });

    const invalidate = () => {
        qc.invalidateQueries({ queryKey: ['corporate-mailbox-connect'] });
        qc.invalidateQueries({ queryKey: ['email-accounts'] });
    };

    const connectMutation = useMutation({
        mutationFn: () => api.post('email/v1/accounts/connect-corporate/', { address, password }),
        onSuccess: () => {
            toast.success(t('mail.connect.connected', 'Ящик подключён'));
            setPassword('');
            setOpen(false);
            invalidate();
        },
        onError: (e: ApiError) => toast.error(
            e?.response?.data?.detail || t('mail.connect.error', 'Не удалось подключить ящик'),
            { duration: 12_000 },
        ),
    });

    const disconnectMutation = useMutation({
        mutationFn: () => api.delete('email/v1/accounts/connect-corporate/'),
        onSuccess: () => {
            toast.success(t('mail.connect.disconnected', 'Ящик отключён от платформы'));
            invalidate();
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    // Режим выключен админом — показывать нечего.
    if (!info?.allowed) return null;

    const mailbox = info.mailbox;

    return (
        <div className={className}>
            <div className="rounded-lg border bg-card p-4">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="space-y-1">
                        <h3 className="font-medium flex items-center gap-2">
                            <AtSign className="h-4 w-4" />
                            {t('mail.connect.title', 'Корпоративная почта')}
                        </h3>
                        {mailbox ? (
                            <p className="text-sm text-muted-foreground">
                                <span className="font-mono">{mailbox.address}</span>{' '}
                                <Badge variant={mailbox.status === 'active' ? 'default' : 'secondary'}>
                                    {mailbox.status}
                                </Badge>
                                {mailbox.last_error && (
                                    <span className="block text-destructive text-xs mt-1">{mailbox.last_error}</span>
                                )}
                            </p>
                        ) : (
                            <p className="text-sm text-muted-foreground">
                                {t('mail.connect.subtitle', 'Подключите свой рабочий ящик @{{domain}}, чтобы читать и отправлять почту здесь.', { domain: info.domain })}
                            </p>
                        )}
                    </div>

                    <div className="flex gap-2">
                        <Button variant={mailbox ? 'outline' : 'default'} className="gap-2" onClick={() => setOpen(true)}>
                            <Link2 className="h-4 w-4" />
                            {mailbox
                                ? t('mail.connect.update', 'Обновить пароль')
                                : t('mail.connect.connect', 'Подключить ящик')}
                        </Button>
                        {mailbox && (
                            <Button
                                variant="ghost" className="gap-2 text-destructive hover:text-destructive"
                                onClick={() => disconnectMutation.mutate()}
                                disabled={disconnectMutation.isPending}
                            >
                                <Unlink className="h-4 w-4" />
                                {t('mail.connect.disconnect', 'Отключить')}
                            </Button>
                        )}
                    </div>
                </div>
            </div>

            <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setPassword(''); }}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t('mail.connect.connect', 'Подключить ящик')}</DialogTitle>
                        <DialogDescription>
                            {t('mail.connect.hint', 'Введите адрес и пароль вашего рабочего ящика — те же, что вы используете в почтовом клиенте. Платформа проверит их на почтовом сервере и сохранит в зашифрованном виде.')}
                        </DialogDescription>
                    </DialogHeader>

                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label>{t('mail.connect.address', 'Адрес ящика')}</Label>
                            <Input
                                value={address || (mailbox?.address ?? '')}
                                onChange={(e) => setAddress(e.target.value)}
                                placeholder={`i.ivanov@${info.domain}`}
                                autoComplete="username"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label>{t('mail.connect.password', 'Пароль ящика')}</Label>
                            <Input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                autoComplete="current-password"
                            />
                        </div>
                        <p className="flex items-start gap-2 text-xs text-muted-foreground">
                            <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                            {t('mail.connect.security', 'Пароль хранится зашифрованным и используется только для получения и отправки вашей почты.')}
                        </p>
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setOpen(false)}>
                            {t('profile.cancel', 'Отмена')}
                        </Button>
                        <Button
                            onClick={() => connectMutation.mutate()}
                            disabled={connectMutation.isPending || !password || !(address || mailbox?.address)}
                        >
                            {connectMutation.isPending
                                ? t('mail.connect.checking', 'Проверяем…')
                                : t('mail.connect.connect', 'Подключить ящик')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
};

export default ConnectCorporateMailbox;
