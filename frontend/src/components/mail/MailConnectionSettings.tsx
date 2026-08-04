import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CheckCircle2, XCircle, MinusCircle, PlugZap, Save, Info } from 'lucide-react';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';

type Provisioner = '' | 'auto' | 'mailcow' | 'imap' | 'none';

// GET/PUT email/v1/mailboxes/settings/
// `value` — что записано в БД (пусто = наследуем из окружения),
// `effective` — что реально действует. Разделение важно: иначе админ не
// отличит «я задал 993» от «993 пришло из переменных окружения».
type MailSettings = {
    value: Record<string, string | number | boolean | null>;
    effective: {
        provisioner: string;
        resolved_provisioner: string;
        domain: string;
        imap_host: string;
        imap_port: number;
        imap_ssl: boolean;
        imap_starttls: boolean;
        imap_tls_server_hostname: string;
        smtp_host: string;
        smtp_port: number;
        smtp_ssl: boolean;
        smtp_starttls: boolean;
        mailcow_api_url: string;
        sync_folders: string[];
        sync_push_flags: boolean;
        allow_self_service: boolean;
        local_part_pattern: string;
    };
    overridden: string[];
    mailcow_api_key_set: boolean;
    updated_at: string | null;
};

type CheckStep = {
    key: string;
    title: string;
    status: 'ok' | 'fail' | 'skip';
    detail: string;
    hint: string;
    data: Record<string, unknown>;
};

type CheckReport = { ok: boolean; steps: CheckStep[] };

type ApiError = { response?: { data?: { detail?: string } } };

type FormState = Record<string, string | boolean>;

const TEXT_FIELDS = [
    'domain', 'imap_host', 'imap_tls_server_hostname', 'smtp_host', 'mailcow_api_url',
] as const;
const NUMBER_FIELDS = ['imap_port', 'smtp_port'] as const;
const BOOL_FIELDS = [
    'imap_ssl', 'imap_starttls', 'smtp_ssl', 'smtp_starttls', 'sync_push_flags', 'allow_self_service',
] as const;

/** Список папок сервера из произвольного `data` шага — если он там есть. */
const folderList = (step: CheckStep): string[] | null => {
    const value = step.data?.available;
    return Array.isArray(value) ? value.map(String) : null;
};

const STEP_ICON: Record<CheckStep['status'], React.ReactNode> = {
    ok: <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />,
    fail: <XCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />,
    skip: <MinusCircle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />,
};

/**
 * Вкладка «Подключение»: реквизиты почтового сервера прямо из интерфейса.
 *
 * Раньше их можно было задать только в `.env` + перезапуск контейнеров, а
 * проверить — лишь попыткой завести ящик. Здесь и правка, и проверка связи
 * (та же цепочка, что у `manage.py mail_check`) в одном месте.
 */
export const MailConnectionSettings: React.FC = () => {
    const { t } = useTranslation();
    const qc = useQueryClient();
    const [form, setForm] = useState<FormState>({});
    // Снимок значений на момент загрузки: сохраняем ТОЛЬКО изменённые поля.
    // Иначе одно сохранение формы (например, ради галочки самоподключения)
    // молча перекрыло бы собой все остальные поля, и правки в .env
    // перестали бы на них влиять — а заметить это было бы нечем.
    const [initial, setInitial] = useState<FormState>({});
    const [apiKey, setApiKey] = useState('');
    const [probeMailbox, setProbeMailbox] = useState('');
    const [probePassword, setProbePassword] = useState('');
    const [report, setReport] = useState<CheckReport | null>(null);
    const [pattern, setPattern] = useState('');

    const { data, isLoading } = useQuery({
        queryKey: ['mail-settings'],
        queryFn: async () => (await api.get<MailSettings>('email/v1/mailboxes/settings/')).data,
    });

    // Показываем ДЕЙСТВУЮЩИЕ значения — так поле сразу видно заполненным, даже
    // если оно пришло из окружения. Пометка «из окружения» рядом объясняет,
    // почему очистка поля не делает его пустым.
    useEffect(() => {
        if (!data) return;
        const next: FormState = {};
        const eff = data.effective as unknown as Record<string, unknown>;
        TEXT_FIELDS.forEach((f) => { next[f] = String(eff[f] ?? ''); });
        NUMBER_FIELDS.forEach((f) => { next[f] = String(eff[f] ?? ''); });
        BOOL_FIELDS.forEach((f) => { next[f] = Boolean(eff[f]); });
        next.provisioner = String(data.value.provisioner ?? '');
        next.sync_folders = (data.effective.sync_folders || []).join(', ');
        setPattern(String(data.value.local_part_pattern ?? ''));
        setForm(next);
        setInitial(next);
        setApiKey('');
    }, [data]);

    const set = (key: string, value: string | boolean) =>
        setForm((prev) => ({ ...prev, [key]: value }));

    const saveMutation = useMutation({
        mutationFn: async () => {
            const payload: Record<string, unknown> = {};
            const changed = (f: string) => form[f] !== initial[f];

            if (changed('provisioner')) payload.provisioner = form.provisioner as string;
            if (pattern !== String(data?.value.local_part_pattern ?? '')) {
                payload.local_part_pattern = pattern;
            }
            if (changed('sync_folders')) {
                payload.sync_folders = String(form.sync_folders || '')
                    .split(',').map((s) => s.trim()).filter(Boolean);
            }
            TEXT_FIELDS.forEach((f) => {
                if (changed(f)) payload[f] = form[f] ?? '';
            });
            NUMBER_FIELDS.forEach((f) => {
                if (!changed(f)) return;
                const raw = String(form[f] ?? '').trim();
                payload[f] = raw ? Number(raw) : null;
            });
            BOOL_FIELDS.forEach((f) => {
                if (changed(f)) payload[f] = Boolean(form[f]);
            });
            // Пустая строка = «не менять»: форма не знает текущего секрета.
            if (apiKey) payload.mailcow_api_key = apiKey;
            return (await api.put<MailSettings>('email/v1/mailboxes/settings/', payload)).data;
        },
        onSuccess: (saved) => {
            qc.setQueryData(['mail-settings'], saved);
            qc.invalidateQueries({ queryKey: ['admin-mailbox-status'] });
            toast.success(t('admin.mailboxes.settingsSaved', 'Настройки сохранены'));
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    const testMutation = useMutation({
        mutationFn: async () => (await api.post<CheckReport>('email/v1/mailboxes/settings/test/', {
            mailbox: probeMailbox, password: probePassword, timeout: 10,
        })).data,
        onSuccess: (data) => {
            setReport(data);
            if (data.ok) toast.success(t('admin.mailboxes.testOk', 'Связь с почтовым сервером есть'));
        },
        onError: (e: ApiError) => toast.error(e?.response?.data?.detail || 'Error'),
    });

    if (isLoading || !data) return <div className="py-10 text-center text-muted-foreground">Loading…</div>;

    const inherited = (field: string) => !data.overridden.includes(field);

    const textField = (field: typeof TEXT_FIELDS[number] | 'sync_folders', label: string, placeholder = '') => (
        <div className="space-y-1.5">
            <Label className="flex items-center gap-2">
                {label}
                {inherited(field) && (
                    <Badge variant="outline" className="text-[10px] font-normal">
                        {t('admin.mailboxes.fromEnv', 'из окружения')}
                    </Badge>
                )}
            </Label>
            <Input
                value={String(form[field] ?? '')}
                onChange={(e) => set(field, e.target.value)}
                placeholder={placeholder}
            />
        </div>
    );

    const numberField = (field: typeof NUMBER_FIELDS[number], label: string) => (
        <div className="space-y-1.5">
            <Label className="flex items-center gap-2">
                {label}
                {inherited(field) && (
                    <Badge variant="outline" className="text-[10px] font-normal">
                        {t('admin.mailboxes.fromEnv', 'из окружения')}
                    </Badge>
                )}
            </Label>
            <Input
                type="number" min={1} max={65535}
                value={String(form[field] ?? '')}
                onChange={(e) => set(field, e.target.value)}
            />
        </div>
    );

    const checkbox = (field: typeof BOOL_FIELDS[number], label: string, hint?: string) => (
        <label className="flex items-start gap-2 text-sm">
            <input
                type="checkbox" className="mt-1"
                checked={Boolean(form[field])}
                onChange={(e) => set(field, e.target.checked)}
            />
            <span>
                {label}
                {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
            </span>
        </label>
    );

    return (
        <div className="space-y-4">
            <div className="flex items-start gap-2 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
                <Info className="h-4 w-4 mt-0.5 shrink-0" />
                <p>
                    {t('admin.mailboxes.settingsHelp', 'Значения из окружения (.env) используются, пока поле не изменено здесь. Очистите поле, чтобы вернуться к значению из окружения. Действующий режим: {{mode}}.', { mode: data.effective.resolved_provisioner })}
                </p>
            </div>

            <div className="rounded-lg border bg-card p-4 space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                        <Label>{t('admin.mailboxes.provisioner', 'Режим подключения')}</Label>
                        <select
                            className="w-full h-9 rounded-md border bg-background px-3 text-sm"
                            value={String(form.provisioner ?? '')}
                            onChange={(e) => set('provisioner', e.target.value as Provisioner)}
                        >
                            <option value="">{t('admin.mailboxes.modeEnv', 'Из окружения')}</option>
                            <option value="auto">{t('admin.mailboxes.modeAuto', 'Автоматически')}</option>
                            <option value="imap">{t('admin.mailboxes.modeImap', 'IMAP/SMTP')}</option>
                            <option value="mailcow">{t('admin.mailboxes.modeMailcow', 'Mailcow API')}</option>
                            <option value="none">{t('admin.mailboxes.modeNone', 'Не подключён')}</option>
                        </select>
                    </div>
                    {textField('domain', t('admin.mailboxes.domainField', 'Домен ящиков'), 'htq.group')}
                </div>

                {/* Соглашение об именовании: промах здесь особенно дорог в
                    режиме IMAP — адрес обязан совпасть с реальным ящиком. */}
                <div className="space-y-1.5">
                    <Label>{t('admin.mailboxes.localPartPattern', 'Шаблон адреса из имени')}</Label>
                    <select
                        className="w-full h-9 rounded-md border bg-background px-3 text-sm"
                        value={pattern}
                        onChange={(e) => setPattern(e.target.value)}
                    >
                        <option value="">{t('admin.mailboxes.modeEnv', 'Из окружения')} — {data.effective.local_part_pattern}</option>
                        <option value="first.last">sanzhar.inamzhanov</option>
                        <option value="f.last">s.inamzhanov</option>
                        <option value="firstlast">sanzharinamzhanov</option>
                        <option value="first_last">sanzhar_inamzhanov</option>
                        <option value="flast">sinamzhanov</option>
                        <option value="last.first">inamzhanov.sanzhar</option>
                        <option value="first">sanzhar</option>
                    </select>
                    <p className="text-xs text-muted-foreground">
                        {t('admin.mailboxes.localPartPatternHint', 'Как собрать адрес из имени и фамилии сотрудника. Должно совпадать с принятым в компании — иначе платформа сгенерирует адрес, которого на сервере нет.')}
                    </p>
                </div>

                <h4 className="font-medium pt-2">IMAP</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                    {textField('imap_host', t('admin.mailboxes.imapHost', 'Хост'), 'mail-tunnel')}
                    {numberField('imap_port', t('admin.mailboxes.port', 'Порт'))}
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                    {checkbox('imap_ssl', t('admin.mailboxes.useSsl', 'Использовать SSL/TLS'),
                        t('admin.mailboxes.tunnelTlsHint', 'Через SSH-туннель обычно не нужно — шифрует сам SSH'))}
                    {checkbox('imap_starttls', 'STARTTLS')}
                </div>
                {textField('imap_tls_server_hostname',
                    t('admin.mailboxes.tlsHostname', 'Имя для проверки сертификата'),
                    t('admin.mailboxes.tlsHostnamePlaceholder', 'только для TLS внутри туннеля'))}

                <h4 className="font-medium pt-2">SMTP</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                    {textField('smtp_host', t('admin.mailboxes.smtpHost', 'Хост'),
                        t('admin.mailboxes.smtpHostPlaceholder', 'пусто = тот же, что IMAP'))}
                    {numberField('smtp_port', t('admin.mailboxes.port', 'Порт'))}
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                    {checkbox('smtp_ssl', t('admin.mailboxes.useSsl', 'Использовать SSL/TLS'))}
                    {checkbox('smtp_starttls', 'STARTTLS')}
                </div>

                <h4 className="font-medium pt-2">Mailcow API</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                    {textField('mailcow_api_url', 'API URL', 'https://mail.example.com/api/v1')}
                    <div className="space-y-1.5">
                        <Label className="flex items-center gap-2">
                            {t('admin.mailboxes.apiKey', 'API-ключ')}
                            {data.mailcow_api_key_set && (
                                <Badge variant="secondary" className="text-[10px] font-normal">
                                    {t('admin.mailboxes.apiKeySet', 'задан')}
                                </Badge>
                            )}
                        </Label>
                        <Input
                            type="password" value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                            placeholder={t('admin.mailboxes.apiKeyPlaceholder', 'оставьте пустым, чтобы не менять')}
                        />
                    </div>
                </div>

                <h4 className="font-medium pt-2">{t('admin.mailboxes.syncSection', 'Синхронизация')}</h4>
                {textField('sync_folders', t('admin.mailboxes.syncFolders', 'Папки синхронизации'), 'INBOX, Sent')}
                <div className="space-y-2">
                    {checkbox('sync_push_flags', t('admin.mailboxes.pushFlags', 'Отмечать прочитанное на сервере'))}
                    {checkbox('allow_self_service', t('admin.mailboxes.selfService', 'Разрешить сотрудникам подключать свой ящик самостоятельно'),
                        t('admin.mailboxes.selfServiceHint', 'Сотрудник вводит адрес и пароль ящика; платформа проверяет их на сервере'))}
                </div>

                <div className="flex justify-end pt-2">
                    <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="gap-2">
                        <Save className="h-4 w-4" />
                        {saveMutation.isPending ? t('common.saving', 'Сохранение...') : t('profile.save', 'Сохранить')}
                    </Button>
                </div>
            </div>

            {/* Проверка связи */}
            <div className="rounded-lg border bg-card p-4 space-y-3">
                <h4 className="font-medium">{t('admin.mailboxes.testTitle', 'Проверка связи')}</h4>
                <p className="text-sm text-muted-foreground">
                    {t('admin.mailboxes.testHelp', 'Проверяет цепочку по порядку: настройки → порт → IMAP → вход → папки → SMTP, и останавливается на первом провале. Адрес и пароль ящика необязательны — без них проверяются настройки и доступность портов.')}
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                        <Label>{t('admin.mailboxes.testMailbox', 'Ящик (необязательно)')}</Label>
                        <Input value={probeMailbox} onChange={(e) => setProbeMailbox(e.target.value)}
                               placeholder={`i.ivanov@${data.effective.domain || 'example.com'}`} />
                    </div>
                    <div className="space-y-1.5">
                        <Label>{t('admin.mailboxes.testPassword', 'Пароль (необязательно)')}</Label>
                        <Input type="password" value={probePassword}
                               onChange={(e) => setProbePassword(e.target.value)}
                               placeholder={t('admin.mailboxes.testPasswordPlaceholder', 'пусто = сохранённый пароль ящика')} />
                    </div>
                </div>
                <Button onClick={() => testMutation.mutate()} disabled={testMutation.isPending} className="gap-2">
                    <PlugZap className="h-4 w-4" />
                    {testMutation.isPending
                        ? t('admin.mailboxes.testing', 'Проверяем…')
                        : t('admin.mailboxes.test', 'Проверить')}
                </Button>

                {report && (
                    <div className="space-y-2 pt-2">
                        {report.steps.map((step) => (
                            <div key={step.key} className="flex items-start gap-2 text-sm">
                                {STEP_ICON[step.status]}
                                <div className="min-w-0">
                                    <span className="font-medium">{step.title}</span>
                                    {step.detail && <span className="text-muted-foreground">: {step.detail}</span>}
                                    {step.hint && (
                                        <div className="text-xs text-muted-foreground mt-0.5 whitespace-pre-line">
                                            {step.hint}
                                        </div>
                                    )}
                                    {folderList(step) && (
                                        <div className="text-xs text-muted-foreground mt-0.5">
                                            {t('admin.mailboxes.serverFolders', 'Папки на сервере')}:{' '}
                                            <span className="font-mono">{folderList(step)!.join(', ')}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default MailConnectionSettings;
