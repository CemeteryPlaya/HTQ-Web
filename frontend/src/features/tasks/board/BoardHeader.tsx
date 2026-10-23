/**
 * Шапка доски (Trello): название с переключателем досок, вид доски, справа —
 * «Запросы» со счётчиком ждущих решения (K-32), колокольчик уведомлений по
 * доске (K-30, у досок отделов и проектов), «Фильтр» со счётчиком условий и
 * «Колонки» у администратора доски (K-39).
 */
import { Bell, BellOff, Filter, KeyRound, Settings2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';

import { BoardSwitcher } from './BoardSwitcher';
import type { BoardKey } from './types';

export interface BoardHeaderProps {
  boardKey: BoardKey;
  title: string;
  activeFilters: number;
  hiddenColumns: number;
  canAdmin: boolean;
  onOpenFilter: () => void;
  onResetFilter: () => void;
  onOpenSettings: () => void;
  /** `null`/`undefined` — у доски выключателя нет (личная). */
  notificationsEnabled?: boolean | null;
  onToggleNotifications: (enabled: boolean) => void;
  requestsCount: number;
  onOpenRequests: () => void;
}

export function BoardHeader(props: BoardHeaderProps) {
  const { t } = useTranslation();
  const kindLabel = {
    personal: t('tasks.board.kind.personal', 'Личная доска'),
    department: t('tasks.board.kind.department', 'Доска отдела'),
    project: t('tasks.board.kind.project', 'Доска проекта'),
  }[props.boardKey.kind];

  return (
    <div className="flex flex-wrap items-center gap-2 bg-black/10 px-4 py-2 backdrop-blur-sm dark:bg-black/25">
      <BoardSwitcher current={props.boardKey} title={props.title} />
      <span className="hidden rounded-md bg-black/10 px-2 py-0.5 text-xs font-medium sm:inline dark:bg-white/10">
        {kindLabel}
      </span>
      <div className="ml-auto flex items-center gap-1.5">
        <Button variant="ghost" size="sm" onClick={props.onOpenRequests}
          className="gap-1.5 hover:bg-black/10 dark:hover:bg-white/10">
          <KeyRound className="h-4 w-4" />
          {t('tasks.requests.button', 'Запросы')}
          {props.requestsCount > 0 && (
            <span className="rounded-full bg-amber-500 px-1.5 text-xs text-white">{props.requestsCount}</span>
          )}
        </Button>
        {typeof props.notificationsEnabled === 'boolean' && (
          <Button variant="ghost" size="icon" className="h-8 w-8 hover:bg-black/10 dark:hover:bg-white/10"
            aria-pressed={!props.notificationsEnabled}
            aria-label={props.notificationsEnabled
              ? t('tasks.board.notifications.turnOff', 'Выключить уведомления о моих задачах этой доски')
              : t('tasks.board.notifications.turnOn', 'Включить уведомления о моих задачах этой доски')}
            title={props.notificationsEnabled
              ? t('tasks.board.notifications.on', 'Уведомления о ваших задачах на этой доске включены')
              : t('tasks.board.notifications.off', 'Уведомления о ваших задачах на этой доске выключены')}
            onClick={() => props.onToggleNotifications(!props.notificationsEnabled)}>
            {props.notificationsEnabled ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={props.onOpenFilter}
          className="gap-1.5 hover:bg-black/10 dark:hover:bg-white/10">
          <Filter className="h-4 w-4" />
          {t('tasks.board.filter.title', 'Фильтр')}
          {props.activeFilters > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
              {props.activeFilters}
            </span>
          )}
        </Button>
        {props.activeFilters > 0 && (
          <Button variant="ghost" size="icon" className="h-8 w-8 hover:bg-black/10 dark:hover:bg-white/10"
            aria-label={t('tasks.board.filter.reset', 'Сбросить фильтр')} onClick={props.onResetFilter}>
            <X className="h-4 w-4" />
          </Button>
        )}
        {props.canAdmin && (
          <Button variant="ghost" size="sm" onClick={props.onOpenSettings}
            className="gap-1.5 hover:bg-black/10 dark:hover:bg-white/10">
            <Settings2 className="h-4 w-4" />
            {t('tasks.board.settings.open', 'Колонки')}
            {props.hiddenColumns > 0 && (
              <span className="text-xs text-muted-foreground">
                {t('tasks.board.settings.hiddenCount', 'скрыто: {{count}}', { count: props.hiddenColumns })}
              </span>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
