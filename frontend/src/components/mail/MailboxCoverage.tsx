/**
 * «У кого из сотрудников не работает почта» — обратная сторона подсказки
 * «введите пароль».
 *
 * Та адресует проблему сотруднику по одному и по одному же её и оставляет:
 * админ не видит ни масштаба, ни того, что часть случаев закрывается им самим
 * за минуту, без хождения людей за паролями.
 *
 * Причина у каждой строки своя, потому что и действия разные — завести ящик,
 * свести бесхозный с владельцем, сходить к сотруднику за паролем. Список без
 * причины был бы просто перечнем фамилий, с которым непонятно что делать.
 *
 * Бэкенд: GET /api/email/v1/mailboxes/coverage/ (apps/mail/views.py).
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, KeyRound, Link2Off, Loader2, MailPlus } from 'lucide-react';

import api from '@/api/client';
import { Badge } from '@/components/ui/badge';
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';

type Reason = 'no_mailbox' | 'not_linked' | 'awaiting_password';

type CoverageRow = {
    user_id: number;
    email: string;
    full_name: string;
    reason: Reason;
    mailbox_id: number | null;
};

type Coverage = {
    domain: string;
    provisioner: string;
    can_create_remotely: boolean;
    users: CoverageRow[];
};

/** Порядок — по тому, чья очередь действовать: сначала админ, потом сотрудник. */
const REASON_ORDER: Reason[] = ['no_mailbox', 'not_linked', 'awaiting_password'];

const REASON_ICON: Record<Reason, typeof MailPlus> = {
    no_mailbox: MailPlus,
    not_linked: Link2Off,
    awaiting_password: KeyRound,
};

export const MailboxCoverage: React.FC = () => {
    const { t } = useTranslation();

    const { data, isLoading, error } = useQuery({
        queryKey: ['mailbox-coverage'],
        queryFn: async () => (await api.get<Coverage>('email/v1/mailboxes/coverage/')).data,
        retry: false,
    });

    const label: Record<Reason, string> = {
        no_mailbox: t('admin.mailboxes.coverage.reason.no_mailbox', 'Ящика нет'),
        not_linked: t('admin.mailboxes.coverage.reason.not_linked', 'Ящик ничей'),
        awaiting_password: t('admin.mailboxes.coverage.reason.awaiting_password', 'Ждёт пароль'),
    };

    // Что делать — половина смысла списка. Текст зависит ещё и от режима:
    // на голом IMAP платформа ящики не создаёт, и советовать «нажмите
    // создать» было бы обманом.
    const advice: Record<Reason, string> = {
        no_mailbox: data?.can_create_remotely
            ? t('admin.mailboxes.coverage.advice.createHere', 'Заведите ящик на вкладке «Ящики» — платформа создаст его на сервере.')
            : t('admin.mailboxes.coverage.advice.createOnServer', 'Ящик заводит почтовый администратор на сервере. После этого платформа подключит его сама.'),
        not_linked: t('admin.mailboxes.coverage.advice.reconcile', 'Ящик уже существует, но владелец не проставлен. Это делает сверка — вкладка «Сверка».'),
        awaiting_password: t('admin.mailboxes.coverage.advice.password', 'Ящик привязан, но платформа не смогла получить к нему доступ сама. Пароль вводит сотрудник у себя в настройках почты.'),
    };

    if (isLoading) {
        return (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('admin.mailboxes.coverage.loading', 'Считаем…')}
            </p>
        );
    }
    if (error || !data) {
        return (
            <p className="text-sm text-destructive">
                {t('admin.mailboxes.coverage.error', 'Не удалось получить список')}
            </p>
        );
    }

    if (!data.domain) {
        return (
            <p className="text-sm text-muted-foreground">
                {t('admin.mailboxes.coverage.noDomain', 'Корпоративный домен не настроен — определить, у кого должна быть рабочая почта, платформа не может. Задайте домен на вкладке «Подключение».')}
            </p>
        );
    }

    if (data.users.length === 0) {
        return (
            <p className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                {t('admin.mailboxes.coverage.empty', 'У всех сотрудников с адресом в корпоративном домене почта работает.')}
            </p>
        );
    }

    const groups = REASON_ORDER
        .map((reason) => ({ reason, rows: data.users.filter((u) => u.reason === reason) }))
        .filter((group) => group.rows.length > 0);

    return (
        <div className="space-y-6">
            <p className="text-sm text-muted-foreground">
                {t('admin.mailboxes.coverage.summary', 'Сотрудников с адресом @{{domain}}, у которых почта не работает: {{count}}', {
                    domain: data.domain,
                    count: data.users.length,
                })}
            </p>

            {groups.map(({ reason, rows }) => {
                const Icon = REASON_ICON[reason];
                return (
                    <section key={reason} className="space-y-2">
                        <div className="flex items-center gap-2">
                            <Icon className="h-4 w-4 text-muted-foreground" />
                            <h3 className="text-sm font-semibold">{label[reason]}</h3>
                            <Badge variant="secondary">{rows.length}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">{advice[reason]}</p>

                        <div className="rounded-lg border overflow-x-auto">
                            <Table className="text-sm">
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>{t('admin.mailboxes.coverage.columnName', 'Сотрудник')}</TableHead>
                                        <TableHead>{t('admin.mailboxes.coverage.columnEmail', 'Рабочий адрес')}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {rows.map((row) => (
                                        <TableRow key={row.user_id}>
                                            <TableCell>{row.full_name}</TableCell>
                                            <TableCell className="font-mono text-xs">{row.email}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </section>
                );
            })}
        </div>
    );
};

export default MailboxCoverage;
