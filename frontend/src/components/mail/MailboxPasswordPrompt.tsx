/**
 * «Ваш ящик найден — введите пароль»: подсказка сотруднику там, где он
 * столкнётся с последствиями её отсутствия.
 *
 * Появляется, только когда платформа НЕ смогла получить доступ к найденному
 * ящику сама (сервер без админ-API, Mailcow отказал в app-password). В
 * обычном случае ящик подключается молча, и сотрудника ничто не беспокоит —
 * иначе подсказка стала бы фоновым шумом и её перестали бы читать.
 *
 * ``variant``:
 * * ``inline`` — в разделе «Почта», ровно там, где видна пустота;
 * * ``banner`` — плавающая полоса после входа, на любой странице.
 */
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyRound, X } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { MailboxPasswordDialog } from './MailboxPasswordDialog';
import { useCorporateMailbox } from './useCorporateMailbox';

export const MailboxPasswordPrompt: React.FC<{
    variant?: 'inline' | 'banner';
    className?: string;
}> = ({ variant = 'inline', className }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [dismissed, setDismissed] = useState(false);
    const { data: info } = useCorporateMailbox();

    const address = info?.mailbox?.address;
    const awaiting = Boolean(info?.awaiting_password && address);

    // Диалог остаётся смонтированным, пока открыт: Radix ставит на <body>
    // pointer-events:none и снимает его при СВОЁМ закрытии. Сними мы диалог
    // с монтирования раньше — страница осталась бы «мёртвой» к кликам.
    if (!awaiting && !open) return null;

    const text = t(
        'mail.connect.promptBody',
        'Ваш рабочий ящик {{address}} найден на почтовом сервере, но платформа не может открыть его без пароля. Введите пароль — и почта появится здесь.',
        { address },
    );

    return (
        <>
            {awaiting && variant === 'inline' && (
                <div className={`flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm ${className ?? ''}`}>
                    <KeyRound className="h-4 w-4 mt-0.5 shrink-0 text-amber-600" />
                    <div className="flex-1 space-y-2">
                        <p>{text}</p>
                        <Button size="sm" onClick={() => setOpen(true)}>
                            {t('mail.connect.promptAction', 'Ввести пароль')}
                        </Button>
                    </div>
                </div>
            )}

            {awaiting && variant === 'banner' && !dismissed && (
                <div className="fixed inset-x-0 bottom-0 z-40 mb-16 px-3 md:mb-3">
                    <div className="mx-auto flex max-w-3xl items-start gap-3 rounded-lg border border-amber-500/40 bg-background/95 p-3 text-sm shadow-lg backdrop-blur">
                        <KeyRound className="h-4 w-4 mt-0.5 shrink-0 text-amber-600" />
                        <p className="flex-1">{text}</p>
                        <div className="flex shrink-0 items-center gap-1">
                            <Button size="sm" onClick={() => setOpen(true)}>
                                {t('mail.connect.promptAction', 'Ввести пароль')}
                            </Button>
                            {/* Скрыть можно только до перезагрузки: ящик всё
                                ещё не работает, и «навсегда» здесь означало бы
                                тихо бросить сотрудника без почты. */}
                            <Button
                                size="sm" variant="ghost"
                                aria-label={t('mail.connect.promptDismiss', 'Скрыть')}
                                onClick={() => setDismissed(true)}
                            >
                                <X className="h-4 w-4" />
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            <MailboxPasswordDialog
                open={open}
                onOpenChange={setOpen}
                domain={info?.domain}
                fixedAddress={address}
            />
        </>
    );
};

export default MailboxPasswordPrompt;
