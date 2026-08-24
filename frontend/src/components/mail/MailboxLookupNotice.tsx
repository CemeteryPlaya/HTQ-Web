/**
 * Вердикт сверки в форме заведения ящика: «такой ящик уже есть — он будет
 * подключён» вместо молчаливого ``i.ivanov2`` или неожиданной ошибки сервера.
 *
 * Свободный адрес не комментируется вовсе: это обычный ход дел, и подпись
 * «всё в порядке» под каждым полем только приучает её не читать.
 */
import React from 'react';
import { AlertTriangle, CheckCircle2, KeyRound, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { MailboxLookup, lookupVerdict } from './mailboxLookup';

export const MailboxLookupNotice: React.FC<{
    lookup?: MailboxLookup | null;
    loading?: boolean;
}> = ({ lookup, loading }) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t('admin.mailboxes.lookupChecking', 'Сверяем адрес…')}
            </p>
        );
    }
    if (!lookup) return null;

    const verdict = lookupVerdict(lookup);
    if (verdict === 'free') return null;

    const attaching = verdict === 'attach';
    const Icon = attaching ? CheckCircle2 : verdict === 'needs-password' ? KeyRound : AlertTriangle;
    const tone = attaching
        ? 'border-emerald-500/40 bg-emerald-500/10'
        : 'border-amber-500/40 bg-amber-500/10';
    const iconTone = attaching ? 'text-emerald-600' : 'text-amber-600';

    return (
        <div className={`flex items-start gap-2 rounded-md border p-2.5 text-xs ${tone}`}>
            <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${iconTone}`} />
            <span>{lookup.detail}</span>
        </div>
    );
};
