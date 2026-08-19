import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AtSign, KeyRound, Link2, Unlink } from 'lucide-react';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

import { MailboxPasswordDialog } from './MailboxPasswordDialog';
import { useCorporateMailbox, useInvalidateCorporateMailbox } from './useCorporateMailbox';

type ApiError = { response?: { data?: { detail?: string } } };

/**
 * Корпоративный ящик сотрудника в его профиле.
 *
 * Два разных сценария на одной карточке:
 *
 * 1. **Самоподключение.** Ящик завёл почтовый администратор, сотрудник знает
 *    от него пароль и привязывает ящик сам, не дожидаясь админа платформы.
 *    Доступно, только если админ включил режим (``self_service``).
 * 2. **Доввод пароля.** Ящик уже НАЙДЕН и закреплён за сотрудником самой
 *    платформой, но открыть его она не смогла (сервер без админ-API, Mailcow
 *    отказал в app-password). Тогда карточка показывается ВСЕГДА, даже при
 *    выключенном самообслуживании: иначе получилось бы «ящик ваш, но
 *    пользоваться им нельзя».
 *
 * Проверка пары адрес/пароль идёт живым входом ДО сохранения, поэтому
 * нерабочая привязка не создаётся.
 */
export const ConnectCorporateMailbox: React.FC<{ className?: string }> = ({ className }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    const { data: info } = useCorporateMailbox();
    const invalidate = useInvalidateCorporateMailbox();

    const disconnectMutation = useMutation({
        mutationFn: () => api.delete('email/v1/accounts/connect-corporate/'),
        onSuccess: () => {
            toast.success(t('mail.connect.disconnected', 'Ящик отключён от платформы'));
            invalidate();
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    // Раньше здесь стоял ранний `return null`, уносивший ВЕСЬ поддеревом,
    // включая диалог. Стоило запросу `connect-corporate` отдать ошибку или
    // `allowed: false` (а он перезапрашивается сразу после подключения, и
    // `retry: false` — то есть один сетевой сбой обнуляет `info`), как
    // открытый диалог исчезал не закрывшись. Radix снимает свою блокировку
    // `body { pointer-events: none }` в обработчике ЗАКРЫТИЯ; при резком
    // размонтировании снимать её некому — и вся страница переставала
    // принимать клики. Ровно то, на что жалуются: «после этого окна кнопки
    // не нажимаются».
    //
    // Поэтому карточка скрывается, а диалог остаётся смонтированным, пока он
    // открыт: закрыть его должен Radix, а не React-условие.
    const canConnect = Boolean(info?.allowed);
    const mailbox = info?.mailbox;
    const awaiting = Boolean(info?.awaiting_password && mailbox);

    if (!canConnect && !open) return null;

    return (
        <div className={className}>
            {canConnect && (
            <div className={`rounded-lg border p-4 ${awaiting ? 'border-amber-500/40 bg-amber-500/10' : 'bg-card'}`}>
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="space-y-1">
                        <h3 className="font-medium flex items-center gap-2">
                            {awaiting
                                ? <KeyRound className="h-4 w-4 text-amber-600" />
                                : <AtSign className="h-4 w-4" />}
                            {awaiting
                                ? t('mail.connect.pendingTitle', 'Введите пароль от вашего ящика')
                                : t('mail.connect.title', 'Корпоративная почта')}
                        </h3>
                        {awaiting ? (
                            <p className="text-sm">
                                {t('mail.connect.promptBody', 'Ваш рабочий ящик {{address}} найден на почтовом сервере, но платформа не может открыть его без пароля. Введите пароль — и почта появится здесь.', { address: mailbox?.address })}
                            </p>
                        ) : mailbox ? (
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
                                {t('mail.connect.subtitle', 'Подключите свой рабочий ящик @{{domain}}, чтобы читать и отправлять почту здесь.', { domain: info?.domain })}
                            </p>
                        )}
                    </div>

                    <div className="flex gap-2">
                        <Button
                            variant={mailbox && !awaiting ? 'outline' : 'default'}
                            className="gap-2"
                            onClick={() => setOpen(true)}
                        >
                            {awaiting ? <KeyRound className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
                            {awaiting
                                ? t('mail.connect.promptAction', 'Ввести пароль')
                                : mailbox
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
            )}

            {/* Вне условия выше намеренно: см. комментарий про
                pointer-events — открытый диалог нельзя снимать с
                монтирования, его должен закрыть Radix.

                Адрес блокируется только у «ждущего» ящика: он уже назначен,
                выбирать нечего. В режиме самообслуживания сотрудник вводит
                адрес сам. */}
            <MailboxPasswordDialog
                open={open}
                onOpenChange={setOpen}
                domain={info?.domain}
                fixedAddress={awaiting ? mailbox?.address : null}
            />
        </div>
    );
};

export default ConnectCorporateMailbox;
