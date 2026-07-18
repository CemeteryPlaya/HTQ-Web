import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
    Activity,
    AlertCircle,
    ArrowLeft,
    CheckCircle2,
    Copy,
    Database,
    ExternalLink,
    Eye,
    EyeOff,
    HardDrive,
    History,
    KeyRound,
    Loader2,
    Lock,
    ServerCog,
    ShieldCheck,
} from 'lucide-react';
import { toast } from 'sonner';

import api from '@/api/client';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import MonitoringWidget from '@/components/profile/MonitoringWidget';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

type CredentialField = {
    key: string;
    label: string;
    value: string;
    secret: boolean;
    masked: boolean;
    copyable: boolean;
};

type ResourceLink = {
    label: string;
    url: string;
    external: boolean;
};

type ManagedResource = {
    id: string;
    name: string;
    kind: string;
    status: string;
    summary: string;
    endpoint: string;
    database?: string | null;
    credentials: CredentialField[];
    links: ResourceLink[];
};

type InfrastructureResponse = {
    credentials_visible: boolean;
    issued_at: string;
    environment: string;
    reveal_expires_at: string | null;
    reveal_ttl_seconds: number | null;
    resources: ManagedResource[];
};

type HealthResult = {
    id: string;
    status: 'ok' | 'error';
    latency_ms: number | null;
    message: string;
    checked_at: string;
};

type HealthCheckResponse = {
    checked_at: string;
    results: HealthResult[];
};

type HealthState = {
    status: 'unknown' | 'checking' | 'ok' | 'error';
    latency_ms?: number | null;
    message?: string;
    checked_at?: string;
};

type HistoryPoint = { at: string; status: string; latency_ms: number | null };
type HealthHistoryResponse = { history: Record<string, HistoryPoint[]> };

type AuditEvent = {
    at: string;
    user_id: number | string | null;
    email: string | null;
    ip: string | null;
    user_agent: string | null;
    ttl_seconds: number | null;
};
type AuditResponse = { events: AuditEvent[] };

const Sparkline: React.FC<{ points: HistoryPoint[]; width?: number; height?: number }> = ({
    points,
    width = 120,
    height = 28,
}) => {
    if (!points.length) {
        return <span className="text-[10px] text-muted-foreground">нет данных</span>;
    }
    const values = points.map((p) => p.latency_ms ?? 0);
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = Math.max(1, max - min);
    const step = points.length > 1 ? width / (points.length - 1) : 0;
    const path = points
        .map((p, i) => {
            const v = p.latency_ms ?? 0;
            const y = height - ((v - min) / range) * (height - 4) - 2;
            return `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
    const last = points[points.length - 1];
    const stroke = last.status === 'ok' ? 'hsl(142 70% 40%)' : 'hsl(0 70% 50%)';
    return (
        <svg width={width} height={height} className="shrink-0">
            <path d={path} fill="none" stroke={stroke} strokeWidth={1.5} />
        </svg>
    );
};

const iconByResource: Record<string, React.ComponentType<{ className?: string }>> = {
    postgres: Database,
    mongo: Database,
    redis: ServerCog,
    minio: HardDrive,
};

const resolveExternalUrl = (url: string) => {
    if (typeof window === 'undefined') return url;
    if (url === 'http://localhost:9001') {
        return `http://${window.location.hostname}:9001`;
    }
    return url;
};

const extractError = (err: any, fallback: string) =>
    err?.response?.data?.detail ?? err?.message ?? fallback;

const AdminInfrastructure = () => {
    const [dialogOpen, setDialogOpen] = useState(false);
    const [password, setPassword] = useState('');
    const [revealed, setRevealed] = useState<InfrastructureResponse | null>(null);
    const [health, setHealth] = useState<Record<string, HealthState>>({});
    const [history, setHistory] = useState<Record<string, HistoryPoint[]>>({});
    const [shownFields, setShownFields] = useState<Set<string>>(new Set());
    const [auditOpen, setAuditOpen] = useState(false);
    const [auditEvents, setAuditEvents] = useState<AuditEvent[] | null>(null);
    const [auditLoading, setAuditLoading] = useState(false);

    const { data, isLoading, error } = useQuery({
        queryKey: ['admin-infrastructure'],
        queryFn: async () => {
            const res = await api.get<InfrastructureResponse>('admin/v1/infrastructure/');
            return res.data;
        },
        retry: false,
    });

    const revealMutation = useMutation({
        mutationFn: async () => {
            const res = await api.post<InfrastructureResponse>(
                'admin/v1/infrastructure/credentials/reveal',
                { password },
            );
            return res.data;
        },
        onSuccess: (body) => {
            setRevealed(body);
            setShownFields(new Set());
            setPassword('');
            setDialogOpen(false);
            toast.success('Доступ к секретам подтвержден. Кликните по полю, чтобы показать.');
        },
        onError: (err) => {
            toast.error(extractError(err, 'Не удалось подтвердить пароль'));
        },
    });

    useEffect(() => {
        if (!data) return;
        checkAllHealth();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data?.issued_at]);

    const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
    useEffect(() => {
        if (!revealed?.reveal_expires_at) {
            setSecondsLeft(null);
            return undefined;
        }
        const expiresAt = new Date(revealed.reveal_expires_at).getTime();
        const tick = () => {
            const left = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
            setSecondsLeft(left);
            if (left <= 0) {
                setRevealed(null);
                toast.info('Секреты скрыты (истёк TTL)');
            }
        };
        tick();
        const id = window.setInterval(tick, 1000);
        return () => window.clearInterval(id);
    }, [revealed]);

    const visibleData = revealed ?? data;
    const secretCount = useMemo(
        () => visibleData?.resources.reduce(
            (sum, resource) => sum + resource.credentials.filter((field) => field.secret).length,
            0,
        ) ?? 0,
        [visibleData],
    );

    const fetchHistory = async () => {
        try {
            const res = await api.get<HealthHistoryResponse>('admin/v1/infrastructure/health-history');
            setHistory(res.data.history);
        } catch {
            // silent — history is auxiliary
        }
    };

    const openAudit = async () => {
        setAuditOpen(true);
        setAuditLoading(true);
        try {
            const res = await api.get<AuditResponse>('admin/v1/infrastructure/audit/reveals');
            setAuditEvents(res.data.events);
        } catch (err) {
            toast.error(extractError(err, 'Не удалось загрузить журнал'));
        } finally {
            setAuditLoading(false);
        }
    };

    const checkAllHealth = async () => {
        const ids = data?.resources.map((r) => r.id) ?? [];
        setHealth((prev) => {
            const next = { ...prev };
            ids.forEach((id) => { next[id] = { status: 'checking' }; });
            return next;
        });
        try {
            const res = await api.get<HealthCheckResponse>('admin/v1/infrastructure/health-check');
            const map: Record<string, HealthState> = {};
            res.data.results.forEach((r) => {
                map[r.id] = {
                    status: r.status,
                    latency_ms: r.latency_ms,
                    message: r.message,
                    checked_at: r.checked_at,
                };
            });
            setHealth((prev) => ({ ...prev, ...map }));
            fetchHistory();
        } catch (err) {
            toast.error(extractError(err, 'Не удалось проверить статус'));
            setHealth((prev) => {
                const next = { ...prev };
                ids.forEach((id) => {
                    if (next[id]?.status === 'checking') next[id] = { status: 'unknown' };
                });
                return next;
            });
        }
    };

    const checkOneHealth = async (resourceId: string) => {
        setHealth((prev) => ({ ...prev, [resourceId]: { status: 'checking' } }));
        try {
            const res = await api.post<HealthResult>(
                `admin/v1/infrastructure/${resourceId}/health-check`,
            );
            setHealth((prev) => ({
                ...prev,
                [resourceId]: {
                    status: res.data.status,
                    latency_ms: res.data.latency_ms,
                    message: res.data.message,
                    checked_at: res.data.checked_at,
                },
            }));
            if (res.data.status === 'ok') {
                toast.success(`${resourceId}: ${res.data.latency_ms ?? '?'} ms`);
            } else {
                toast.error(`${resourceId}: ${res.data.message || 'error'}`);
            }
            fetchHistory();
        } catch (err) {
            setHealth((prev) => ({ ...prev, [resourceId]: { status: 'unknown' } }));
            toast.error(extractError(err, 'Проверка не удалась'));
        }
    };

    const copyValue = async (field: CredentialField) => {
        if (!field.copyable || !field.value) return;
        await navigator.clipboard.writeText(field.value);
        toast.success(`${field.label}: скопировано`);
    };

    if (isLoading) {
        return (
            <div className="min-h-screen bg-background flex flex-col">
                <Header />
                <main className="flex-1 flex items-center justify-center">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                </main>
                <Footer />
            </div>
        );
    }

    if (error || !visibleData) {
        return (
            <div className="min-h-screen bg-background flex flex-col">
                <Header />
                <main className="flex-1 container mx-auto px-4 py-8 flex items-center justify-center">
                    <Alert variant="destructive" className="max-w-xl">
                        <Lock className="h-4 w-4" />
                        <AlertTitle>Доступ закрыт</AlertTitle>
                        <AlertDescription>
                            Нужны права администратора для просмотра инфраструктуры.
                        </AlertDescription>
                    </Alert>
                </main>
                <Footer />
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8">
                <div className="mb-6 flex flex-col gap-4">
                    <Link
                        to="/myprofile"
                        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
                    >
                        <ArrowLeft className="h-4 w-4" />
                        Назад в профиль
                    </Link>

                    <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                        <div>
                            <div className="flex flex-wrap items-center gap-2">
                                <h1 className="text-3xl font-bold">Инфраструктура</h1>
                                {visibleData.environment && (
                                    <Badge variant={visibleData.environment === 'production' ? 'destructive' : 'outline'}>
                                        env: {visibleData.environment}
                                    </Badge>
                                )}
                                <Badge variant={visibleData.credentials_visible ? 'destructive' : 'secondary'}>
                                    {visibleData.credentials_visible ? 'секреты открыты' : 'секреты скрыты'}
                                </Badge>
                            </div>
                            <p className="mt-1 text-sm text-muted-foreground">
                                MongoDB, MinIO, SQL и служебные подключения.
                            </p>
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                            <Button variant="outline" onClick={checkAllHealth}>
                                <Activity className="h-4 w-4" />
                                Проверить все
                            </Button>
                            <Button variant="outline" onClick={openAudit}>
                                <History className="h-4 w-4" />
                                Журнал ревелов
                            </Button>
                            {visibleData.credentials_visible ? (
                                <Button variant="outline" onClick={() => setRevealed(null)}>
                                    <EyeOff className="h-4 w-4" />
                                    Скрыть пароли
                                </Button>
                            ) : (
                                <Button onClick={() => setDialogOpen(true)}>
                                    <Eye className="h-4 w-4" />
                                    Показать пароли
                                </Button>
                            )}
                        </div>
                    </div>
                </div>

                {visibleData.credentials_visible && (
                    <Alert className="mb-6 border-amber-200 bg-amber-50 text-amber-950">
                        <ShieldCheck className="h-4 w-4" />
                        <AlertTitle>Повторная проверка пройдена</AlertTitle>
                        <AlertDescription>
                            Открыто секретных полей: {secretCount}.
                            {secondsLeft != null && (
                                <> Авто-скрытие через <span className="font-mono font-semibold">
                                    {String(Math.floor(secondsLeft / 60)).padStart(2, '0')}:
                                    {String(secondsLeft % 60).padStart(2, '0')}
                                </span>.</>
                            )}
                        </AlertDescription>
                    </Alert>
                )}

                <div className="grid gap-4 lg:grid-cols-2">
                    {visibleData.resources.map((resource) => {
                        const Icon = iconByResource[resource.id] ?? ServerCog;
                        const hs = health[resource.id] ?? { status: 'unknown' as const };
                        const badgeVariant =
                            hs.status === 'ok' ? 'default'
                            : hs.status === 'error' ? 'destructive'
                            : 'secondary';
                        const badgeLabel =
                            hs.status === 'ok' ? `OK${hs.latency_ms != null ? ` · ${hs.latency_ms} ms` : ''}`
                            : hs.status === 'error' ? 'ошибка'
                            : hs.status === 'checking' ? 'проверка...'
                            : resource.status;
                        const StatusIcon =
                            hs.status === 'ok' ? CheckCircle2
                            : hs.status === 'error' ? AlertCircle
                            : hs.status === 'checking' ? Loader2
                            : Activity;
                        return (
                            <section key={resource.id} className="rounded-lg border bg-card p-4 shadow-sm">
                                <div className="mb-4 flex items-start justify-between gap-3">
                                    <div className="flex min-w-0 items-start gap-3">
                                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border bg-background">
                                            <Icon className="h-5 w-5 text-primary" />
                                        </div>
                                        <div className="min-w-0">
                                            <h2 className="truncate text-lg font-semibold leading-tight">{resource.name}</h2>
                                            <p className="mt-1 text-sm text-muted-foreground">{resource.summary}</p>
                                        </div>
                                    </div>
                                    <div className="flex shrink-0 flex-col items-end gap-1">
                                        <Badge variant={badgeVariant} className="flex items-center gap-1">
                                            <StatusIcon className={cn('h-3 w-3', hs.status === 'checking' && 'animate-spin')} />
                                            {badgeLabel}
                                        </Badge>
                                        <Sparkline points={history[resource.id] ?? []} />
                                        {hs.checked_at && (
                                            <span className="text-[10px] text-muted-foreground">
                                                {new Date(hs.checked_at).toLocaleTimeString()}
                                            </span>
                                        )}
                                    </div>
                                </div>

                                <div className="mb-4 grid gap-2 text-sm sm:grid-cols-2">
                                    <div className="rounded-md border bg-background px-3 py-2">
                                        <span className="block text-xs text-muted-foreground">Endpoint</span>
                                        <span className="block break-all font-mono">{resource.endpoint || '-'}</span>
                                    </div>
                                    <div className="rounded-md border bg-background px-3 py-2">
                                        <span className="block text-xs text-muted-foreground">Database / bucket</span>
                                        <span className="block break-all font-mono">{resource.database || '-'}</span>
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    {resource.credentials.map((field) => {
                                        const fieldId = `${resource.id}.${field.key}`;
                                        const canShow = field.secret && !field.masked;
                                        const isShown = shownFields.has(fieldId);
                                        const displayValue =
                                            field.secret && !field.masked && !isShown
                                                ? '••••••••'
                                                : field.value || '-';
                                        return (
                                            <div
                                                key={field.key}
                                                className="grid grid-cols-[104px_minmax(0,1fr)_72px] items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm"
                                            >
                                                <span className="text-xs font-medium text-muted-foreground">{field.label}</span>
                                                <span
                                                    className={cn(
                                                        'min-w-0 break-all font-mono text-xs sm:text-sm',
                                                        ((field.masked) || (field.secret && !isShown)) && 'tracking-widest text-muted-foreground',
                                                    )}
                                                >
                                                    {displayValue}
                                                </span>
                                                <div className="flex items-center justify-end gap-0">
                                                    {canShow && (
                                                        <Button
                                                            type="button"
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-8 w-8"
                                                            onClick={() => setShownFields((prev) => {
                                                                const next = new Set(prev);
                                                                if (next.has(fieldId)) next.delete(fieldId);
                                                                else next.add(fieldId);
                                                                return next;
                                                            })}
                                                            title={isShown ? 'Скрыть' : 'Показать'}
                                                        >
                                                            {isShown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                        </Button>
                                                    )}
                                                    <Button
                                                        type="button"
                                                        variant="ghost"
                                                        size="icon"
                                                        className="h-8 w-8"
                                                        onClick={() => copyValue(field)}
                                                        disabled={!field.copyable}
                                                        title={`Скопировать ${field.label}`}
                                                    >
                                                        <Copy className="h-4 w-4" />
                                                    </Button>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>

                                <div className="mt-4 flex flex-wrap gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => checkOneHealth(resource.id)}
                                        disabled={hs.status === 'checking'}
                                    >
                                        {hs.status === 'checking'
                                            ? <Loader2 className="h-4 w-4 animate-spin" />
                                            : <Activity className="h-4 w-4" />}
                                        Проверить
                                    </Button>
                                    {resource.links.map((link) => (
                                        <Button key={`${resource.id}-${link.url}`} variant="outline" size="sm" asChild>
                                            <a href={resolveExternalUrl(link.url)}>
                                                <ExternalLink className="h-4 w-4" />
                                                {link.label}
                                            </a>
                                        </Button>
                                    ))}
                                </div>
                                {hs.status === 'error' && hs.message && (
                                    <p className="mt-2 break-all text-xs text-destructive">{hs.message}</p>
                                )}
                            </section>
                        );
                    })}
                </div>

                {/* Мониторинг Prometheus-таргетов (перенесён из профиля) */}
                <div className="mt-6">
                    <MonitoringWidget />
                </div>
            </main>
            <Footer />

            <Dialog open={auditOpen} onOpenChange={setAuditOpen}>
                <DialogContent className="max-w-3xl">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <History className="h-5 w-5" />
                            Журнал раскрытий секретов
                        </DialogTitle>
                        <DialogDescription>
                            Последние {auditEvents?.length ?? 0} событий (in-memory ring, очищается при рестарте admin-service).
                        </DialogDescription>
                    </DialogHeader>
                    {auditLoading ? (
                        <div className="flex justify-center py-6">
                            <Loader2 className="h-6 w-6 animate-spin text-primary" />
                        </div>
                    ) : (
                        <div className="max-h-96 overflow-auto rounded border">
                            <table className="w-full text-xs">
                                <thead className="sticky top-0 bg-muted">
                                    <tr className="text-left">
                                        <th className="px-2 py-1.5">Время</th>
                                        <th className="px-2 py-1.5">Email</th>
                                        <th className="px-2 py-1.5">IP</th>
                                        <th className="px-2 py-1.5">User-Agent</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(auditEvents ?? []).length === 0 ? (
                                        <tr><td colSpan={4} className="px-2 py-3 text-center text-muted-foreground">Пусто</td></tr>
                                    ) : (
                                        (auditEvents ?? []).map((ev, i) => (
                                            <tr key={i} className="border-t">
                                                <td className="px-2 py-1 font-mono">{new Date(ev.at).toLocaleString()}</td>
                                                <td className="px-2 py-1">{ev.email ?? '-'}</td>
                                                <td className="px-2 py-1 font-mono">{ev.ip ?? '-'}</td>
                                                <td className="px-2 py-1 max-w-xs truncate" title={ev.user_agent ?? ''}>{ev.user_agent ?? '-'}</td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                    )}
                </DialogContent>
            </Dialog>

            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <KeyRound className="h-5 w-5" />
                            Подтверждение администратора
                        </DialogTitle>
                        <DialogDescription>
                            Введите пароль текущей учетной записи администратора.
                        </DialogDescription>
                    </DialogHeader>

                    <form
                        className="space-y-4"
                        onSubmit={(event) => {
                            event.preventDefault();
                            revealMutation.mutate();
                        }}
                    >
                        <div className="space-y-2">
                            <Label htmlFor="admin-password">Пароль</Label>
                            <Input
                                id="admin-password"
                                type="password"
                                autoComplete="current-password"
                                value={password}
                                onChange={(event) => setPassword(event.target.value)}
                                disabled={revealMutation.isPending}
                            />
                        </div>

                        <DialogFooter>
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => setDialogOpen(false)}
                                disabled={revealMutation.isPending}
                            >
                                Отмена
                            </Button>
                            <Button type="submit" disabled={!password || revealMutation.isPending}>
                                {revealMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                                Показать
                            </Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </div>
    );
};

export default AdminInfrastructure;
