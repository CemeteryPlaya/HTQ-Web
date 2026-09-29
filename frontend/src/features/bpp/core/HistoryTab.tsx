/**
 * Вкладка «История изменений» формы документа модуля (ТЗ §25.2, §05):
 * журнал `AuditLog` через `GET /api/bpp/v1/history/<тип>/<id>`.
 *
 * Ручка отдаёт 404 и на чужой документ, и на тип без зарегистрированной
 * проверки доступа (`services/core/audit.py`), — вкладка в этом случае
 * говорит «История недоступна», не различая причин: различать их ручка не
 * даёт намеренно.
 *
 * Кто — `actor_name`, если сервер его прислал; иначе «Пользователь №id»:
 * ручки «имя по id» на платформе нет, а журнал пишет только `actor_id`.
 * Пусто — действие системы (ночная сверка, фоновые задачи).
 *
 * Поля журнала — имена полей модели (`total_amount`); подписи и список
 * денежных полей даёт экран документа (`fieldLabels`, `moneyFields`): он
 * знает свою модель, вкладка — нет. Без подписи поле показывается именем.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { errorStatus } from '@/lib/apiError';

import { formatDateTime } from '../format';

import { changeRows } from './historyChanges';

export interface HistoryEntry {
  id: string;
  action: string;
  actor_id: number | null;
  actor_name?: string | null;
  changes: Record<string, unknown>;
  comment: string;
  created_at: string;
}

/** Подписи действий журнала; неизвестное действие показывается кодом. */
const ACTIONS: Record<string, [string, string]> = {
  created: ['bpp.history.action.created', 'Создан'],
  updated: ['bpp.history.action.updated', 'Изменён'],
  deleted: ['bpp.history.action.deleted', 'Удалён'],
  copied: ['bpp.history.action.copied', 'Скопирован'],
  submitted: ['bpp.history.action.submitted', 'Отправлен на согласование'],
  withdrawn: ['bpp.history.action.withdrawn', 'Отозван'],
  approved: ['bpp.history.action.approved', 'Утверждён'],
  rejected: ['bpp.history.action.rejected', 'Отклонён'],
  returned: ['bpp.history.action.returned', 'Возвращён на доработку'],
  cancelled: ['bpp.history.action.cancelled', 'Отменён'],
  closed: ['bpp.history.action.closed', 'Закрыт'],
  reopened: ['bpp.history.action.reopened', 'Открыт повторно'],
  paid: ['bpp.history.action.paid', 'Оплачен'],
  remainder_closed: ['bpp.history.action.remainder_closed', 'Остаток закрыт'],
  report_added: ['bpp.history.action.report_added', 'Добавлен авансовый отчёт'],
  correction_started: ['bpp.history.action.correction_started', 'Начата корректировка'],
  correction_approved: ['bpp.history.action.correction_approved', 'Корректировка утверждена'],
  correction_cancelled: ['bpp.history.action.correction_cancelled', 'Корректировка отменена'],
  item_reassigned: ['bpp.history.action.item_reassigned', 'Позиция переназначена'],
  blocked: ['bpp.history.action.blocked', 'Заблокирован'],
  unblocked: ['bpp.history.action.unblocked', 'Разблокирован'],
  archived: ['bpp.history.action.archived', 'В архиве'],
  verified_set: ['bpp.history.action.verified_set', 'Изменена метка «Проверенный»'],
  account_added: ['bpp.history.action.account_added', 'Добавлен банковский счёт'],
  account_updated: ['bpp.history.action.account_updated', 'Изменён банковский счёт'],
  file_attached: ['bpp.history.action.file_attached', 'Приложен файл'],
  file_replaced: ['bpp.history.action.file_replaced', 'Загружена новая версия файла'],
  file_deleted: ['bpp.history.action.file_deleted', 'Удалён файл'],
  file_downloaded: ['bpp.history.action.file_downloaded', 'Скачан файл'],
};

export interface HistoryFieldOptions {
  /** Подписи полей журнала: `{total_amount: 'Сумма'}`. */
  fieldLabels?: Record<string, string>;
  /** Поля-суммы — показываются как `1 250 000,00`. */
  moneyFields?: readonly string[];
}

interface Props extends HistoryFieldOptions {
  /** Тип объекта журнала — `app_label.model`: `bpp.purchaserequest`. */
  objectType: string;
  objectId: string;
}

export function HistoryTab({ objectType, objectId, fieldLabels, moneyFields }: Props) {
  const { t } = useTranslation();
  const { data = [], isLoading, error } = useQuery({
    queryKey: ['bpp', 'history', objectType, objectId],
    queryFn: () =>
      api.get<HistoryEntry[]>(apiPath('bpp', `history/${objectType}/${objectId}`))
        .then((r) => r.data),
  });

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((row) => <Skeleton key={row} className="h-8 w-full" />)}
      </div>
    );
  }
  if (error) {
    return (
      <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
        {errorStatus(error) === 404
          ? t('bpp.history.unavailable', 'История недоступна')
          : t('bpp.history.loadError', 'Не удалось загрузить историю. Обновите страницу.')}
      </p>
    );
  }
  if (data.length === 0) {
    return (
      <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
        {t('bpp.history.empty', 'Изменений пока нет')}
      </p>
    );
  }

  const actorOf = (entry: HistoryEntry) => {
    if (entry.actor_name) return entry.actor_name;
    if (entry.actor_id === null) return t('bpp.history.system', 'Система');
    return t('bpp.history.user', 'Пользователь №{{id}}', { id: entry.actor_id });
  };
  const actionOf = (action: string) => {
    const known = ACTIONS[action];
    return known ? t(known[0], known[1]) : action;
  };

  // Журнал сервер отдаёт по возрастанию; свежие события — сверху.
  const entries = [...data].reverse();

  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-36">{t('bpp.history.when', 'Когда')}</TableHead>
            <TableHead>{t('bpp.history.who', 'Кто')}</TableHead>
            <TableHead>{t('bpp.history.action', 'Действие')}</TableHead>
            <TableHead>{t('bpp.history.changes', 'Изменения')}</TableHead>
            <TableHead>{t('bpp.history.comment', 'Комментарий')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((entry) => {
            const rows = changeRows(entry.changes, { moneyFields });
            return (
              <TableRow key={entry.id}>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {formatDateTime(entry.created_at)}
                </TableCell>
                <TableCell>{actorOf(entry)}</TableCell>
                <TableCell>{actionOf(entry.action)}</TableCell>
                <TableCell>
                  {rows.length === 0 ? '—' : (
                    <ul className="space-y-0.5 text-xs">
                      {rows.map((row) => (
                        <li key={row.field}>
                          <span className="font-medium">{fieldLabels?.[row.field] ?? row.field}</span>
                          {': '}
                          {row.before !== undefined && (
                            <>
                              <span className="text-muted-foreground line-through">{row.before}</span>
                              {' → '}
                            </>
                          )}
                          <span>{row.after}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </TableCell>
                <TableCell className="whitespace-pre-wrap">{entry.comment || '—'}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export default HistoryTab;
