/**
 * Корпоративная почта в настройках сотрудника: подключение и подпись.
 *
 * Заменила поле «Дополнительная почта» — на этом месте полезнее то, чем
 * человек действительно пользуется каждый день.
 *
 * Пароль спрашивается ВСЕГДА и проверяется живым входом на почтовый сервер.
 * Это не формальность: знание адреса ничего не доказывает — адреса сотрудников
 * известны всем, кто получал от них письма, — а вот пароль знает только
 * владелец ящика. Без этой проверки «подключить почту» означало бы «забрать
 * себе чужую переписку, зная лишь адрес».
 *
 * Бэкенд:
 *   GET/POST/DELETE  /api/email/v1/accounts/connect-corporate/
 *   PATCH            /api/email/v1/accounts/{id}/signature/
 */
import React, { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AtSign, CheckCircle2, KeyRound, PenLine, Unlink } from 'lucide-react';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

import { useCorporateMailbox, useInvalidateCorporateMailbox } from './useCorporateMailbox';

type ApiError = { response?: { data?: { detail?: string } } };

type Account = {
    id: number;
    type: 'corporate' | 'personal';
    address: string;
    signature: string;
    is_active: boolean;
};

export const CorporateMailSettings: React.FC = () => {
    const { t } = useTranslation();
    const { data: info } = useCorporateMailbox();
    const invalidate = useInvalidateCorporateMailbox();

    const [password, setPassword] = useState('');
    const [address, setAddress] = useState('');

    const mailbox = info?.mailbox;
    const connected = Boolean(mailbox) && !info?.awaiting_password;
    // Адрес подставляем сами: сотруднику незачем его набирать, а опечатка
    // превратила бы понятный отказ сервера в загадочный.
    const suggested = mailbox?.address || info?.own_address || '';
    const effectiveAddress = suggested || address;

    const connectMutation = useMutation({
        mutationFn: () => api.post('email/v1/accounts/connect-corporate/', {
            address: effectiveAddress,
            password,
        }),
        onSuccess: () => {
            setPassword('');
            invalidate();
            toast.success(t('settingsPage.mailConnected', 'Почта подключена — письма скоро появятся в разделе «Почта»'));
        },
        onError: (e: ApiError) => toast.error(
            e?.response?.data?.detail
            || t('settingsPage.mailConnectFailed', 'Не удалось подключить почту'),
            { duration: 15_000 },
        ),
    });

    const disconnectMutation = useMutation({
        mutationFn: () => api.delete('email/v1/accounts/connect-corporate/'),
        onSuccess: () => {
            invalidate();
            toast.success(t('settingsPage.mailDisconnected', 'Почта отключена от платформы'));
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    // Карточка не показывается вовсе, когда подключать нечего: у сотрудника
    // нет корпоративного адреса и админ не открывал самообслуживание.
    if (!info?.allowed && !mailbox) return null;

    return (
        <div className="space-y-4">
            <div className="space-y-1.5">
                <Label className="flex items-center gap-1">
                    <AtSign className="h-4 w-4" />
                    {t('settingsPage.corporateEmail', 'Корпоративная почта')}
                </Label>

                <Input
                    type="email"
                    value={effectiveAddress}
                    onChange={(e) => setAddress(e.target.value)}
                    // Свой адрес правке не подлежит: его закрепил админ, и
                    // подставить чужой было бы попыткой увести переписку.
                    disabled={Boolean(suggested)}
                    placeholder={`i.ivanov@${info?.domain || '…'}`}
                    autoComplete="username"
                />

                {connected ? (
                    <p className="flex items-center gap-1.5 text-sm text-emerald-600">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {t('settingsPage.mailConnectedHint', 'Подключена — письма приходят в раздел «Почта».')}
                    </p>
                ) : (
                    <p className="text-sm text-muted-foreground">
                        {t('settingsPage.corporateEmailHint', 'Введите пароль от рабочего ящика — платформа проверит его на почтовом сервере и начнёт показывать вашу почту здесь.')}
                    </p>
                )}

            </div>

            {!connected && (
                <div className="space-y-1.5">
                    <Label className="flex items-center gap-1">
                        <KeyRound className="h-4 w-4" />
                        {t('settingsPage.mailPassword', 'Пароль от почты')}
                    </Label>
                    <div className="flex gap-2">
                        <Input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            autoComplete="current-password"
                            placeholder="••••••••"
                        />
                        <Button
                            type="button"
                            onClick={() => connectMutation.mutate()}
                            disabled={connectMutation.isPending || !password || !effectiveAddress}
                        >
                            {connectMutation.isPending
                                ? t('mail.connect.checking', 'Проверяем…')
                                : t('mail.connect.connect', 'Подключить ящик')}
                        </Button>
                    </div>
                </div>
            )}

            {connected && (
                <>
                    <SignatureField />
                    <div>
                        <Button
                            type="button" variant="ghost"
                            className="gap-2 text-destructive hover:text-destructive"
                            onClick={() => disconnectMutation.mutate()}
                            disabled={disconnectMutation.isPending}
                        >
                            <Unlink className="h-4 w-4" />
                            {t('mail.connect.disconnect', 'Отключить')}
                        </Button>
                    </div>
                </>
            )}
        </div>
    );
};

/**
 * Подпись, которой подписываются письма с корпоративного адреса.
 *
 * Живёт при аккаунте, а не при пользователе: у человека может быть и рабочий
 * ящик, и личный, и подписывать клиентское письмо тем же, чем личное, он не
 * захочет.
 */
const SignatureField: React.FC = () => {
    const { t } = useTranslation();
    const [value, setValue] = useState('');
    const [touched, setTouched] = useState(false);

    const { data: accounts } = useQuery({
        queryKey: ['email-accounts'],
        queryFn: async () => (await api.get<Account[]>('email/v1/accounts/')).data,
        staleTime: 60_000,
    });
    const account = (accounts ?? []).find((a) => a.type === 'corporate');

    // Подтягиваем сохранённое значение, но не затираем то, что человек уже
    // начал править: запрос может ответить позже первого нажатия клавиши.
    useEffect(() => {
        if (!touched && account) setValue(account.signature || '');
    }, [account, touched]);

    const mutation = useMutation({
        mutationFn: () => api.patch(`email/v1/accounts/${account?.id}/signature/`, {
            signature: value,
        }),
        onSuccess: () => {
            setTouched(false);
            toast.success(t('settingsPage.signatureSaved', 'Подпись сохранена'));
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    if (!account) return null;

    return (
        <div className="space-y-1.5">
            <Label className="flex items-center gap-1">
                <PenLine className="h-4 w-4" />
                {t('settingsPage.signature', 'Подпись в письмах')}
            </Label>
            <Textarea
                rows={4}
                value={value}
                onChange={(e) => { setValue(e.target.value); setTouched(true); }}
                placeholder={t('settingsPage.signaturePlaceholder', 'Иван Иванов\nРуководитель проекта, Hi-Tech Group\n+7 700 000-00-00')}
            />
            <div className="flex items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">
                    {t('settingsPage.signatureHint', 'Подставляется в конец нового письма — перед отправкой её можно отредактировать или убрать.')}
                </p>
                <Button
                    type="button" variant="secondary" size="sm"
                    onClick={() => mutation.mutate()}
                    disabled={mutation.isPending || !touched}
                >
                    {mutation.isPending
                        ? t('common.saving', 'Сохранение...')
                        : t('settingsPage.save', 'Сохранить')}
                </Button>
            </div>
        </div>
    );
};

export default CorporateMailSettings;
