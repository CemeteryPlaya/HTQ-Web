/**
 * «Доска | Таблица» раздела «Задачи» (этап S6a, решение R-04): доска —
 * последняя открытая, таблица — прежний реестр с фильтрами по отделам,
 * исполнителям и подрядчикам (`/tasks/list`).
 */
import { LayoutList, SquareKanban } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/utils';

import { lastBoardUrl } from './boardRoutes';

export function TasksViewToggle({ current, className }: { current: 'board' | 'table'; className?: string }) {
  const { t } = useTranslation();
  const item = (active: boolean) => cn(
    'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors',
    active ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
  );
  return (
    <nav aria-label={t('tasks.views.label', 'Вид раздела «Задачи»')}
      className={cn('inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5', className)}>
      <Link to={lastBoardUrl()} className={item(current === 'board')}
        aria-current={current === 'board' ? 'page' : undefined}>
        <SquareKanban className="h-3.5 w-3.5" />
        {t('tasks.views.board', 'Доска')}
      </Link>
      <Link to="/tasks/list" className={item(current === 'table')}
        aria-current={current === 'table' ? 'page' : undefined}>
        <LayoutList className="h-3.5 w-3.5" />
        {t('tasks.views.table', 'Таблица')}
      </Link>
    </nav>
  );
}
