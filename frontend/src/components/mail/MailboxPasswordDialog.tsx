/**
 * Ввод пароля от корпоративного ящика — единственное место в интерфейсе,
 * которое это умеет.
 *
 * Поверхностей три (карточка в профиле, раздел «Почта», баннер после входа),
 * и разойдись они в мелочах — в блокировке адреса, в тексте ошибки, в том,
 * что инвалидируется после успеха, — сотрудник получал бы разный результат в
 * зависимости от того, откуда нажал.
 *
 * ``fixedAddress`` — ящик, который платформа УЖЕ назначила сотруднику. Тогда
 * адрес не редактируется: выбирать нечего, а опечатка в нём превратила бы
 * понятный отказ сервера в загадочный.
 */
import React, { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { useInvalidateCorporateMailbox } from './useCorporateMailbox';

type ApiError = { response?: { data?: { detail?: string } } };

export const MailboxPasswordDialog: React.FC<{
    open: boolean;
    onOpenChange: (open: boolean) => void;
    domain?: string;
    fixedAddress?: string | null;
}> = ({ open, onOpenChange, domain, fixedAddress }) => {
    const { t } = useTranslation();
    const invalidate = useInvalidateCorporateMailbox();
    const [address, setAddress] = useState('');
    const [password, setPassword] = useState('');

    useEffect(() => {
        if (!open) setPassword('');
    }, [open]);

    const effectiveAddress = fixedAddress || address;

    const mutation = useMutation({
        mutationFn: async () => {
            const res = await api.post('email/v1/accounts/connect-corporate/', {
                address: effectiveAddress,
                password,
            });
            return res.data;
        },
        onSuccess: () => {
            invalidate();
            toast.success(t('mail.connect.connected', 'Почта подключена'));
            onOpenChange(false);
        },
        // Отказ сервера показываем дословно: «не тот пароль» и «сервер
        // недоступен» требуют разных действий от сотрудника.
        onError: (e: ApiError) => toast.error(
            e?.response?.data?.detail
            || t('mail.connect.failed', 'Не удалось подключить ящик'),
            { duration: 15_000 },
        ),
    });

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                        {fixedAddress
                            ? t('mail.connect.pendingTitle', 'Введите пароль от вашего ящика')
                            : t('mail.connect.connect', 'Подключить ящик')}
                    </DialogTitle>
                    <DialogDescription>
                        {fixedAddress
                            ? t('mail.connect.pendingHint', 'Ящик уже закреплён за вами на почтовом сервере. Введите пароль, которым вы входите в него, — платформа проверит его и начнёт показывать вашу почту здесь.')
                            : t('mail.connect.hint', 'Введите адрес и пароль вашего рабочего ящика — те же, что вы используете в почтовом клиенте. Платформа проверит их на почтовом сервере и сохранит в зашифрованном виде.')}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    <div className="space-y-1.5">
                        <Label>{t('mail.connect.address', 'Адрес ящика')}</Label>
                        <Input
                            value={effectiveAddress}
                            onChange={(e) => setAddress(e.target.value)}
                            disabled={Boolean(fixedAddress)}
                            placeholder={`i.ivanov@${domain || '…'}`}
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
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {t('profile.cancel', 'Отмена')}
                    </Button>
                    <Button
                        onClick={() => mutation.mutate()}
                        disabled={mutation.isPending || !password || !effectiveAddress}
                    >
                        {mutation.isPending
                            ? t('mail.connect.checking', 'Проверяем…')
                            : t('mail.connect.connect', 'Подключить ящик')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

export default MailboxPasswordDialog;
