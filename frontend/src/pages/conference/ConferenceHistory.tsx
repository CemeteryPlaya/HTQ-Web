/**
 * История видеоконференций — /conference/history.
 *
 * Отвечает на вопрос «кто собирал встречу, когда и что от неё осталось».
 * Строки заводит не человек, а SFU по факту звонка (apps.conference), поэтому
 * здесь нет ни создания, ни редактирования — только чтение и переход в
 * карточку.
 *
 * Пагинация серверная, как на странице истории уведомлений: список растёт
 * бесконечно, и вытягивать его целиком нельзя.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { format } from 'date-fns';
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  History as HistoryIcon,
  Radio,
  Search,
  Users,
  Video,
} from 'lucide-react';

import {
  fetchOverview,
  listSessions,
  type ConferenceSessionListItem,
  type ConferenceTodayItem,
} from '@/api/conference';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { BackToProfile } from '@/components/BackToProfile';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  LivePanel, SessionRow, TodayPanel,
} from '@/components/conference/OverviewPanels';
import {
  formatDateTime,
  formatDuration,
  recordingBadge,
} from '@/lib/conference/history';

const PAGE_LIMIT = 25;

/**
 * Текст ошибки из ответа axios, если он там есть.
 *
 * Разбираем `unknown` вручную, а не приводим к `any`: тело ошибки приходит
 * с сервера, и предполагать его форму без проверки — ровно тот случай,
 * когда падает уже сам обработчик ошибки.
 */
const errorDetail = (error: unknown): string => {
  if (typeof error !== 'object' || error === null) return '';
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    .response?.data?.detail;
  if (typeof detail === 'string') return detail;
  const message = (error as { message?: unknown }).message;
  return typeof message === 'string' ? message : '';
};

type ScopeFilter = 'all' | 'mine';
type MainTab = 'today' | 'live' | 'history';

const ConferenceHistory: React.FC = () => {
  const { t } = useTranslation();
  const [tab, setTab] = useState<MainTab>('today');
  const [scope, setScope] = useState<ScopeFilter>('all');
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');

  // Поиск отправляем с задержкой: список ходит на сервер, и запрос на
  // каждое нажатие клавиши — это десяток лишних обращений на одно слово.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(searchInput.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // 30 секунд: «идёт сейчас» устаревает быстро, но чаще — это лишний трафик
  // на каждой открытой вкладке у всех сотрудников сразу.
  const {
    data: overview,
    isLoading: overviewLoading,
    error: overviewError,
  } = useQuery({
    queryKey: ['conference-overview'],
    queryFn: fetchOverview,
    refetchInterval: 30_000,
  });

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['conference-history', scope, query, page],
    queryFn: () => listSessions({
      page, limit: PAGE_LIMIT, q: query || undefined, mine: scope === 'mine',
    }),
  });

  // Пустой список и упавший запрос выглядят одинаково, если про ошибку
  // молчать, — а «встреч нет» и «история не грузится» требуют разных
  // действий от пользователя.
  useEffect(() => {
    if (!error) return;
    const detail = errorDetail(error);
    toast.error(t('conference.history.loadError', 'Не удалось загрузить историю встреч')
      + (detail ? `: ${detail}` : ''));
  }, [error, t]);

  // Тот же приём для /overview: без тоста упавшая ручка выглядит как
  // «сегодня встреч нет» и «никто не разговаривает» — то есть как спокойный
  // рабочий день, а не как сломанная страница.
  useEffect(() => {
    if (!overviewError) return;
    const detail = errorDetail(overviewError);
    toast.error(t('conference.overview.loadError', 'Не удалось загрузить обзор конференций')
      + (detail ? `: ${detail}` : ''));
  }, [overviewError, t]);

  const items = data?.items ?? [];
  const totalPages = data?.pages ?? 1;
  const total = data?.total ?? 0;
  const recordedTotal = data?.recorded_total ?? 0;
  const todayItems = overview?.today ?? [];
  const activeItems = overview?.active ?? [];

  const summary = useMemo(() => (
    t('conference.history.summary', { total, recorded: recordedTotal })
  ), [t, total, recordedTotal]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto py-8 px-4 max-w-5xl animate-in fade-in duration-500">
        <BackToProfile className="mb-4" />

        <div className="mb-6 min-w-0">
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <Video className="h-7 w-7 shrink-0 text-primary" />
            <span className="truncate">
              {t('conference.overview.pageTitle', 'Мои видеоконференции')}
            </span>
          </h1>
        </div>

        <Tabs value={tab} onValueChange={(value) => setTab(value as MainTab)}>
          <TabsList className="mb-6">
            <TabsTrigger value="today" className="gap-1.5">
              <CalendarDays className="h-4 w-4" />
              {t('conference.overview.tabToday', 'Сегодня')}
            </TabsTrigger>
            <TabsTrigger value="live" className="gap-1.5">
              <Radio className="h-4 w-4" />
              {t('conference.overview.tabLive', 'Идут сейчас')}
            </TabsTrigger>
            <TabsTrigger value="history" className="gap-1.5">
              <HistoryIcon className="h-4 w-4" />
              {t('conference.overview.tabHistory', 'История')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="today">
            <TodayPanel
              items={todayItems}
              loading={overviewLoading}
              failed={Boolean(overviewError)}
            />
          </TabsContent>

          <TabsContent value="live">
            <LivePanel
              items={activeItems}
              loading={overviewLoading}
              failed={Boolean(overviewError)}
            />
          </TabsContent>

          <TabsContent value="history">
            <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <p className="text-sm text-muted-foreground">{summary}</p>

              <Tabs value={scope} onValueChange={(value) => {
                setScope(value as ScopeFilter);
                setPage(1);
              }}>
                <TabsList>
                  <TabsTrigger value="all">
                    {t('conference.history.scopeAll', 'Все')}
                  </TabsTrigger>
                  <TabsTrigger value="mine">
                    {t('conference.history.scopeMine', 'Мои')}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            <div className="relative mb-6">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t('conference.history.searchPlaceholder',
                  'Поиск по названию или организатору')}
                className="pl-9"
              />
            </div>

            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-24 w-full rounded-lg" />
                ))}
              </div>
            ) : items.length === 0 ? (
              <div className="rounded-lg border border-dashed p-12 text-center">
                <Video className="mx-auto h-10 w-10 text-muted-foreground/50" />
                <p className="mt-4 text-muted-foreground">
                  {query
                    ? t('conference.history.emptySearch', 'Ничего не найдено')
                    : t('conference.history.empty', 'Встреч пока не было')}
                </p>
              </div>
            ) : (
              <ul className="space-y-3">
                {items.map((session) => (
                  <SessionRow key={session.id} session={session} />
                ))}
              </ul>
            )}

            {totalPages > 1 && (
              <div className="mt-8 flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1 || isFetching}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  <ChevronLeft className="mr-1 h-4 w-4" />
                  {t('conference.history.prev', 'Назад')}
                </Button>
                <span className="text-sm text-muted-foreground">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages || isFetching}
                  onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                >
                  {t('conference.history.next', 'Вперёд')}
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </main>
      <Footer />
    </div>
  );
};

export default ConferenceHistory;
