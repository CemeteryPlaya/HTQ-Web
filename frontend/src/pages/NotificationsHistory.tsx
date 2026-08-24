/**
 * NotificationsHistory — full history page (/notifications).
 *
 * Shows every notification the user ever received with filter tabs
 * (Все / Непрочитанные / Прочитанные), pagination, the date the row was
 * marked as read, and a hyperlink to the source entity (task / calendar
 * event / employee card / …).
 *
 * The "live" notification badge in the header keeps using
 * ``NotificationsViewer`` over the legacy ``/notifications/`` endpoint;
 * this page hits ``/notifications/history/`` for proper pagination.
 */
import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowUpRight,
  Bell,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  RefreshCw,
  Trash2,
} from 'lucide-react';

import {
  deleteNotification,
  fetchNotificationHistory,
  formatNotificationText,
  markAllNotificationsRead,
  markNotificationRead,
  markNotificationUnread,
  notificationSourceLabel,
  notificationTargetUrl,
} from '@/api/tasks';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { BackToProfile } from '@/components/BackToProfile';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import type { Notification } from '@/types/tasks';
import { useTranslation } from 'react-i18next';

type StatusFilter = 'all' | 'unread' | 'read';

const PAGE_LIMIT = 25;

// Mirrors notificationSourceLabel but adds the optional task key suffix
// (e.g. "Задача · ABC-123"). Kept as a one-liner so the rendering loop reads
// cleanly.
const composeSourceBadge = (n: Notification): string | null => {
  const base = notificationSourceLabel(n);
  if (!base) return null;
  if (n.task_key && base === 'Задача') return `${base} · ${n.task_key}`;
  return base;
};

const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('ru', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

const NotificationsHistory: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [status, setStatus] = useState<StatusFilter>('all');
  const [page, setPage] = useState(1);

  const queryKey = ['notification-history', status, page];
  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey,
    queryFn: () =>
      fetchNotificationHistory({ status, page, limit: PAGE_LIMIT }),
  });

  // Surface backend failures explicitly — otherwise an erroring endpoint
  // is indistinguishable from an empty list, which is the trap that hid
  // a missing-migration bug for too long during development.
  useEffect(() => {
    if (error) {
      const msg = (error as any)?.response?.data?.detail
        || (error as any)?.message
        || t('notifications.history.loadError');
      toast.error(t('notifications.history.errorToast', { message: msg }));
      // eslint-disable-next-line no-console
      console.error('notification-history fetch failed', error);
    }
  }, [error, t]);

  // Invalidate both the history query and the live bell dropdown so
  // toggling read state stays in sync everywhere.
  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['notifications'] });
    qc.invalidateQueries({ queryKey: ['notification-history'] });
  };

  const markReadM = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: invalidateAll,
  });
  const markUnreadM = useMutation({
    mutationFn: markNotificationUnread,
    onSuccess: invalidateAll,
  });
  const markAllM = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: invalidateAll,
  });
  const deleteM = useMutation({
    mutationFn: deleteNotification,
    onSuccess: invalidateAll,
  });

  const items: Notification[] = data?.items ?? [];
  const totalPages = data?.pages ?? 1;
  const totalRows = data?.total ?? 0;
  const unreadCount = data?.unread_total ?? 0;

  const handleRowClick = (n: Notification) => {
    const url = notificationTargetUrl(n);
    if (!n.is_read) markReadM.mutate(n.id);
    if (url) navigate(url);
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto py-8 px-4 max-w-5xl animate-in fade-in duration-500">
        <BackToProfile className="mb-4" />
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
              <Bell className="h-7 w-7 text-primary" />
              История уведомлений
              {unreadCount > 0 && (
                <Badge variant="destructive" className="rounded-full">
                  {unreadCount}
                </Badge>
              )}
            </h1>
            <p className="text-muted-foreground mt-1 italic">
              {t('notifications.history.subtitle')}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              className="gap-1.5"
            >
              <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} />
              {t('email.actions.refresh')}
            </Button>
            <Button
              size="sm"
              onClick={() => markAllM.mutate()}
              disabled={markAllM.isPending || unreadCount === 0}
              className="gap-1.5"
            >
              <CheckCircle2 className="h-4 w-4" />
              {t('notifications.markAllRead')}
            </Button>
          </div>
        </div>

        <Tabs value={status} onValueChange={(v) => { setStatus(v as StatusFilter); setPage(1); }} className="mb-4">
          <TabsList>
            <TabsTrigger value="all">{t('common.all')}</TabsTrigger>
            <TabsTrigger value="unread">
              Непрочитанные
              {unreadCount > 0 && (
                <span className="ml-1.5 rounded-full bg-primary/15 px-1.5 text-[10px] font-bold text-primary">
                  {unreadCount}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="read">{t('notifications.history.readTab')}</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="rounded-2xl border bg-card overflow-hidden">
          {isLoading ? (
            <div className="p-12 text-center text-sm text-muted-foreground">
              {t('profile.loading')}
            </div>
          ) : items.length === 0 ? (
            <div className="p-12 text-center text-sm text-muted-foreground flex flex-col items-center gap-3">
              <Circle className="h-10 w-10 opacity-20" />
              <p>
                {status === 'unread'
                  ? t('notifications.history.emptyUnread')
                  : status === 'read'
                  ? t('notifications.history.emptyRead')
                  : t('notifications.history.empty')}
              </p>
            </div>
          ) : (
            <ul className="divide-y">
              {items.map((n) => {
                const url = notificationTargetUrl(n);
                const targetLabel = composeSourceBadge(n);
                const readableText = formatNotificationText(n);
                return (
                  <li
                    key={n.id}
                    className={cn(
                      'group flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:px-5 sm:py-4 transition-colors',
                      !n.is_read && 'bg-primary/5',
                      url && 'cursor-pointer hover:bg-muted/40',
                    )}
                    onClick={(e) => {
                      // Don't navigate when the click came from an action button.
                      if ((e.target as HTMLElement).closest('button')) return;
                      handleRowClick(n);
                    }}
                  >
                    <div className="flex items-start gap-3 sm:flex-1 min-w-0">
                      <span
                        className={cn(
                          'mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full',
                          n.is_read ? 'bg-muted' : 'bg-primary animate-pulse',
                        )}
                        aria-label={n.is_read ? t('notifications.history.readMark') : t('notifications.history.unreadMark')}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm text-foreground">
                          {n.actor_name && (
                            <span className="font-semibold text-primary">
                              {n.actor_name}{' '}
                            </span>
                          )}
                          <span className={cn(!n.is_read && 'font-medium')}>
                            {readableText}
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                          <span>{t('notifications.history.received', { stamp: fmtDate(n.created_at) })}</span>
                          <span>
                            {t('notifications.history.readAt')}
                            <span className={cn(n.read_at ? '' : 'italic opacity-70')}>
                              {n.read_at ? fmtDate(n.read_at) : '—'}
                            </span>
                          </span>
                          {targetLabel && (
                            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                              {targetLabel}
                            </Badge>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 sm:ml-3 flex-shrink-0">
                      {url ? (
                        <Button asChild variant="ghost" size="sm" className="gap-1 text-primary">
                          <Link to={url} onClick={(e) => e.stopPropagation()}>
                            {t('notifications.history.goTo')}
                            <ArrowUpRight className="h-3.5 w-3.5" />
                          </Link>
                        </Button>
                      ) : (
                        <span className="text-xs italic text-muted-foreground px-2">
                          {t('notifications.history.noLink')}
                        </span>
                      )}
                      {n.is_read ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => { e.stopPropagation(); markUnreadM.mutate(n.id); }}
                          className="gap-1 text-muted-foreground hover:text-primary"
                          title={t('notifications.history.markUnread')}
                        >
                          <Circle className="h-3.5 w-3.5" />
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => { e.stopPropagation(); markReadM.mutate(n.id); }}
                          className="gap-1 text-muted-foreground hover:text-primary"
                          title={t('notifications.history.markRead')}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); deleteM.mutate(n.id); }}
                        disabled={deleteM.isPending}
                        className="gap-1 text-muted-foreground hover:text-destructive"
                        title={t('notifications.history.remove')}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between text-sm">
            <p className="text-muted-foreground">
              {t('notifications.history.pageOf', { page, total: totalPages, rows: totalRows })}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="gap-1"
              >
                <ChevronLeft className="h-4 w-4" />
                {t('common.prev')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="gap-1"
              >
                {t('common.next')}
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
};

export default NotificationsHistory;
