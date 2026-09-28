/**
 * Экран фоновой выгрузки реестра (ТЗ §19, D-32; A2.2 задача 6, A2.1 задача 8):
 * `/bpp/exports/:id` — адрес из уведомления «Экспорт «…» готов»/«не собран»
 * (`apps/bpp/services/core/export.py::_notify`, `url=f"/bpp/exports/{job.pk}"`).
 *
 * Опрашивает `GET /api/bpp/v1/exports/<id>` (`export.download`), пока
 * выгрузка «готовится» — сервер пересобирает файл в Celery-задаче. Готовая
 * выгрузка несёт `url` (временная подписанная ссылка на файл в
 * `apps.media_files`) и `expires_at`; ссылка выдаётся только заказчику —
 * чужая и несуществующая выгрузка неотличимы (обе отвечают 404).
 *
 * ⚠️ Каждый GET готовой выгрузки выдаёт НОВУЮ ссылку и пишет в журнал
 * `file_downloaded` (ТЗ §25.2): скачивания журналируются по выдаче ссылки.
 * Поэтому готовую выгрузку экран больше не перечитывает сам — ни опросом,
 * ни при возврате фокуса на вкладку, ни при повторном монтировании
 * (`staleTime: Infinity`): иначе журнал наполнился бы «скачиваниями»,
 * которых никто не делал. Истёкшую ссылку человек обновляет сам кнопкой
 * «Получить новую ссылку» — это и есть новое скачивание.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { Download, FileWarning, RefreshCw } from 'lucide-react';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { errorStatus } from '@/lib/apiError';

import { formatDateTime } from '../format';
import { StatusBadge } from '../core/StatusBadge';

/** Пока выгрузка «готовится» — опрос раз в столько миллисекунд. */
const POLL_MS = 3000;

/** `setTimeout` принимает не больше 2^31−1 мс (~24,8 суток). */
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

interface ExportJobOut {
  id: string;
  name: string;
  status: 'queued' | 'done' | 'error';
  row_count: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  url?: string;
  expires_at?: string;
}

export function ExportStatusPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();

  const {
    data, isLoading, error, refetch, isFetching,
  } = useQuery({
    queryKey: ['bpp', 'export', id],
    queryFn: () => api.get<ExportJobOut>(apiPath('bpp', `exports/${id}`)).then((r) => r.data),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === 'queued' ? POLL_MS : false),
    // Готовая выгрузка — только по явной кнопке: каждый GET выдаёт новую
    // ссылку и пишет скачивание в журнал (см. шапку файла).
    staleTime: (query) => (query.state.data?.status === 'done' ? Infinity : 0),
    refetchOnWindowFocus: (query) => query.state.data?.status !== 'done',
    refetchOnReconnect: (query) => query.state.data?.status !== 'done',
  });

  // Ссылка истекает, пока страница открыта: перерисоваться в момент истечения.
  const expiresAt = data?.status === 'done' && data.expires_at ? Date.parse(data.expires_at) : NaN;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (Number.isNaN(expiresAt)) return undefined;
    const left = expiresAt - Date.now();
    if (left <= 0) return undefined;
    const timer = setTimeout(() => setNow(Date.now()), Math.min(left + 50, MAX_TIMEOUT_MS));
    return () => clearTimeout(timer);
  }, [expiresAt]);
  const expired = !Number.isNaN(expiresAt) && expiresAt <= now;

  if (isLoading) {
    return (
      <Card className="mx-auto max-w-xl">
        <CardHeader><Skeleton className="h-6 w-48" /></CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    const notFound = errorStatus(error) === 404;
    return (
      <Card className="mx-auto max-w-xl">
        <CardContent className="flex flex-col items-center gap-3 py-10 text-center text-sm text-muted-foreground">
          <FileWarning className="h-8 w-8" />
          <p>
            {notFound
              ? t('bpp.exports.notFound', 'Выгрузка не найдена. Возможно, её заказал другой пользователь — запросите экспорт заново.')
              : t('bpp.exports.loadError', 'Не удалось загрузить состояние выгрузки. Обновите страницу.')}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="text-lg">{data.name}</CardTitle>
        <StatusBadge kind="export" status={data.status} />
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">
          {t('bpp.exports.rowCount', 'Строк в выборке: {{count}}', { count: data.row_count })}
        </p>

        {data.status === 'queued' && (
          <p role="status" className="text-muted-foreground">
            {t('bpp.exports.queued', 'Файл собирается в фоне. Страница обновится сама, когда он будет готов.')}
          </p>
        )}

        {data.status === 'error' && (
          <p role="alert" className="text-destructive">
            {data.error || t('bpp.exports.errorFallback', 'Не удалось собрать файл. Повторите экспорт.')}
          </p>
        )}

        {data.status === 'done' && expired && (
          <div className="space-y-3">
            <p role="status" className="text-muted-foreground">
              {t('bpp.exports.expired', 'Ссылка истекла.')}
            </p>
            <Button onClick={() => { void refetch(); }} disabled={isFetching}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              {t('bpp.exports.renewLink', 'Получить новую ссылку')}
            </Button>
          </div>
        )}

        {data.status === 'done' && !expired && (
          <div className="space-y-3">
            <Button asChild>
              <a href={data.url} target="_blank" rel="noreferrer">
                <Download className="mr-1.5 h-4 w-4" />
                {t('bpp.exports.download', 'Скачать')}
              </a>
            </Button>
            {data.expires_at && (
              <p className="text-xs text-muted-foreground">
                {t('bpp.exports.expiresAt', 'Ссылка действует до {{date}}', {
                  date: formatDateTime(data.expires_at),
                })}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ExportStatusPage;
