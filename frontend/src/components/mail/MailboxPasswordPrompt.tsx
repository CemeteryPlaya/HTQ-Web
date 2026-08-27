/**
 * «Ваш ящик найден — введите пароль»: подсказка сотруднику там, где он
 * столкнётся с последствиями её отсутствия.
 *
 * Поводов ровно два, и они разной силы:
 *
 * 1. ``awaiting_password`` — ящик НАЙДЕН и закреплён за сотрудником, но
 *    платформа не смогла получить к нему доступ сама (сервер без админ-API,
 *    Mailcow отказал в app-password). Факт, а не догадка.
 * 2. ``suggest_connect`` — ящика у сотрудника нет, но его рабочий адрес в
 *    корпоративном домене. Догадка: на голом IMAP существование ящика без
 *    пароля не проверяется в принципе, поэтому подтверждением служит сам
 *    успешный вход при подключении.
 *
 * В обычном случае ящик подключается молча, и сотрудника ничто не беспокоит —
 * иначе подсказка стала бы фоновым шумом и её перестали бы читать. По той же
 * причине закрытый баннер ДОГАДКИ не возвращается (запоминаем в
 * localStorage), а баннер найденного ящика возвращается после перезагрузки:
 * там почта действительно не работает, и «навсегда» означало бы тихо бросить
 * сотрудника без неё.
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

/** Ключ «эту догадку уже отклонили». Только для suggest — см. докстринг. */
const SUGGEST_DISMISSED_KEY = 'htq.mail.suggestConnectDismissed';

const readSuggestDismissed = (address: string): boolean => {
    // Приватное окно и заблокированные site data кидают на самом обращении,
    // поэтому в try весь доступ целиком, а не только разбор значения.
    try {
        return localStorage.getItem(SUGGEST_DISMISSED_KEY) === address;
    } catch {
        return false;
    }
};

export const MailboxPasswordPrompt: React.FC<{
    variant?: 'inline' | 'banner';
    className?: string;
}> = ({ variant = 'inline', className }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [dismissed, setDismissed] = useState(false);
    const { data: info } = useCorporateMailbox();

    // Найденный ящик важнее догадки: если он есть, адрес берём у него.
    const awaiting = Boolean(info?.awaiting_password && info?.mailbox?.address);
    const suggested = Boolean(!awaiting && info?.suggest_connect && info?.own_address);
    const address = awaiting ? info?.mailbox?.address : info?.own_address;

    const suggestSilenced = suggested && readSuggestDismissed(address || '');
    const show = awaiting || (suggested && !suggestSilenced);

    // Диалог остаётся смонтированным, пока открыт: Radix ставит на <body>
    // pointer-events:none и снимает его при СВОЁМ закрытии. Сними мы диалог
    // с монтирования раньше — страница осталась бы «мёртвой» к кликам.
    if (!show && !open) return null;

    const hide = () => {
        setDismissed(true);
        if (!suggested) return;
        try {
            localStorage.setItem(SUGGEST_DISMISSED_KEY, address || '');
        } catch {
            // Хранилище недоступно — переживём: баннер вернётся после
            // перезагрузки, но подключению это не мешает.
        }
    };

    const text = awaiting
        ? t(
            'mail.connect.promptBody',
            'Ваш рабочий ящик {{address}} найден на почтовом сервере, но платформа не может открыть его без пароля. Введите пароль — и почта появится здесь.',
            { address },
        )
        : t(
            'mail.connect.suggestBody',
            'Ваш рабочий адрес {{address}} — корпоративный, но почта здесь ещё не подключена. Введите пароль от ящика: платформа проверит его на почтовом сервере и начнёт показывать вашу переписку.',
            { address },
        );

    return (
        <>
            {show && variant === 'inline' && (
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

            {show && variant === 'banner' && !dismissed && (
                <div className="fixed inset-x-0 bottom-0 z-40 mb-16 px-3 md:mb-3">
                    <div className="mx-auto flex max-w-3xl items-start gap-3 rounded-lg border border-amber-500/40 bg-background/95 p-3 text-sm shadow-lg backdrop-blur">
                        <KeyRound className="h-4 w-4 mt-0.5 shrink-0 text-amber-600" />
                        <p className="flex-1">{text}</p>
                        <div className="flex shrink-0 items-center gap-1">
                            <Button size="sm" onClick={() => setOpen(true)}>
                                {t('mail.connect.promptAction', 'Ввести пароль')}
                            </Button>
                            {/* Найденный ящик скрывается только до
                                перезагрузки: он всё ещё не работает, и
                                «навсегда» означало бы тихо бросить сотрудника
                                без почты. Догадку же закрывают насовсем — она
                                может оказаться и ложной. */}
                            <Button
                                size="sm" variant="ghost"
                                aria-label={t('mail.connect.promptDismiss', 'Скрыть')}
                                onClick={hide}
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
                kind={awaiting ? 'pending' : 'suggest'}
            />
        </>
    );
};

export default MailboxPasswordPrompt;
