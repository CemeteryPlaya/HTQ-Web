/**
 * Фильтр доски — выдвижная панель справа, как фильтр Trello: ключевое слово,
 * участники, срок, метки, активность, выполнение. Внутри группы — «или»,
 * между группами — «и» (сервер, `Filters`). Состояние живёт в адресе
 * (`useBoardFilters`), поэтому панель только читает и пишет его.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { fetchLabels } from '@/api/tasks';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { UserAvatar } from '@/components/ui/UserAvatar';

import type { BoardFilters, CardMember } from './types';

type ListName = 'label' | 'member' | 'due' | 'completion' | 'activity';

/** Ключевое слово уходит в адрес (и на сервер) не на каждую букву, а после
 * паузы в наборе. */
function KeywordInput({ value, onCommit, placeholder }: {
  value: string;
  onCommit: (value: string) => void;
  placeholder: string;
}) {
  const [text, setText] = useState(value);
  useEffect(() => { setText(value); }, [value]);
  useEffect(() => {
    if (text === value) return undefined;
    const timer = window.setTimeout(() => onCommit(text), 300);
    return () => window.clearTimeout(timer);
  }, [text, value, onCommit]);
  return <Input value={text} placeholder={placeholder} onChange={(event) => setText(event.target.value)} />;
}

function Option({ checked, onChange, children }: {
  checked: boolean;
  onChange: () => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 text-sm hover:bg-muted/60">
      <Checkbox checked={checked} onCheckedChange={onChange} />
      <span className="flex min-w-0 flex-1 items-center gap-2">{children}</span>
    </label>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h4 className="px-1.5 text-xs font-semibold text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

export interface FilterDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: BoardFilters;
  onChange: (filters: BoardFilters) => void;
  onReset: () => void;
  /** Участники карточек этой доски — из чего выбирать в «Участниках». */
  members: CardMember[];
  /** «Только новые» есть лишь на личной доске (K-28). */
  personal: boolean;
}

export function FilterDrawer({
  open, onOpenChange, filters, onChange, onReset, members, personal,
}: FilterDrawerProps) {
  const { t } = useTranslation();
  const { data: labels = [], isLoading: labelsLoading } = useQuery({
    queryKey: ['hr-labels'],
    queryFn: fetchLabels,
    enabled: open,
  });

  const has = (name: ListName, value: string) => filters[name].includes(value);
  const toggle = (name: ListName, value: string) => {
    const current = filters[name];
    onChange({
      ...filters,
      [name]: current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-sm">
        <SheetHeader className="border-b px-4 py-3 text-left">
          <SheetTitle>{t('tasks.board.filter.title', 'Фильтр')}</SheetTitle>
          <SheetDescription className="text-xs">
            {t('tasks.board.filter.hint',
              'Внутри группы подходит любое отмеченное условие, между группами — все сразу.')}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
          <section className="space-y-1.5 px-1.5">
            <h4 className="text-xs font-semibold text-muted-foreground">
              {t('tasks.board.filter.keyword', 'Ключевое слово')}
            </h4>
            <KeywordInput
              value={filters.q}
              placeholder={t('tasks.board.filter.keywordPlaceholder', 'Название или ключ задачи')}
              onCommit={(q) => onChange({ ...filters, q })}
            />
          </section>

          <Section title={t('tasks.board.filter.members', 'Участники')}>
            <Option checked={has('member', 'none')} onChange={() => toggle('member', 'none')}>
              {t('tasks.board.filter.noMembers', 'Нет исполнителей')}
            </Option>
            <Option checked={has('member', 'me')} onChange={() => toggle('member', 'me')}>
              {t('tasks.board.filter.assignedToMe', 'Назначенные мне')}
            </Option>
            {members.map((member) => (
              <Option key={member.user_id} checked={has('member', String(member.user_id))}
                onChange={() => toggle('member', String(member.user_id))}>
                <UserAvatar url={member.avatar_url} name={member.name} size={24} />
                <span className="truncate">{member.name ?? `#${member.user_id}`}</span>
              </Option>
            ))}
          </Section>

          <Section title={t('tasks.board.filter.completion', 'Выполнение')}>
            <Option checked={has('completion', 'complete')} onChange={() => toggle('completion', 'complete')}>
              {t('tasks.board.filter.complete', 'Отмечены выполненными')}
            </Option>
            <Option checked={has('completion', 'incomplete')} onChange={() => toggle('completion', 'incomplete')}>
              {t('tasks.board.filter.incomplete', 'Не отмечены выполненными')}
            </Option>
          </Section>

          <Section title={t('tasks.board.filter.due', 'Срок')}>
            <Option checked={has('due', 'none')} onChange={() => toggle('due', 'none')}>
              {t('tasks.board.filter.dueNone', 'Без срока')}
            </Option>
            <Option checked={has('due', 'overdue')} onChange={() => toggle('due', 'overdue')}>
              <span className="h-2.5 w-2.5 rounded-full bg-board-overdue" />
              {t('tasks.board.filter.dueOverdue', 'Просрочены')}
            </Option>
            <Option checked={has('due', 'day')} onChange={() => toggle('due', 'day')}>
              <span className="h-2.5 w-2.5 rounded-full bg-board-soon" />
              {t('tasks.board.filter.dueDay', 'Срок в ближайшие сутки')}
            </Option>
            <Option checked={has('due', 'week')} onChange={() => toggle('due', 'week')}>
              {t('tasks.board.filter.dueWeek', 'Срок в ближайшую неделю')}
            </Option>
            <Option checked={has('due', 'month')} onChange={() => toggle('due', 'month')}>
              {t('tasks.board.filter.dueMonth', 'Срок в ближайший месяц')}
            </Option>
          </Section>

          <Section title={t('tasks.board.filter.labels', 'Метки')}>
            <Option checked={has('label', 'none')} onChange={() => toggle('label', 'none')}>
              {t('tasks.board.filter.noLabels', 'Без меток')}
            </Option>
            {labels.map((label) => (
              <Option key={label.id} checked={has('label', String(label.id))}
                onChange={() => toggle('label', String(label.id))}>
                <span className="h-5 min-w-0 flex-1 truncate rounded px-2 text-xs font-medium leading-5 text-white"
                  style={{ backgroundColor: label.color }}>
                  {label.name}
                </span>
              </Option>
            ))}
            {!labelsLoading && labels.length === 0 && (
              <p className="px-1.5 text-xs text-muted-foreground">
                {t('tasks.board.filter.labelsEmpty', 'Меток в компании пока нет — их заводят в карточке задачи.')}
              </p>
            )}
          </Section>

          <Section title={t('tasks.board.filter.activity', 'Активность')}>
            <Option checked={has('activity', '1w')} onChange={() => toggle('activity', '1w')}>
              {t('tasks.board.filter.activity1w', 'За последнюю неделю')}
            </Option>
            <Option checked={has('activity', '2w')} onChange={() => toggle('activity', '2w')}>
              {t('tasks.board.filter.activity2w', 'За последние две недели')}
            </Option>
            <Option checked={has('activity', '4w')} onChange={() => toggle('activity', '4w')}>
              {t('tasks.board.filter.activity4w', 'За последние четыре недели')}
            </Option>
            <Option checked={has('activity', 'stale4w')} onChange={() => toggle('activity', 'stale4w')}>
              {t('tasks.board.filter.activityStale', 'Без активности последние четыре недели')}
            </Option>
          </Section>

          {personal && (
            <Section title={t('tasks.board.filter.newSection', 'Новые')}>
              <Option checked={filters.new} onChange={() => onChange({ ...filters, new: !filters.new })}>
                {t('tasks.board.filter.newOnly', 'Только ещё не открытые мной задачи')}
              </Option>
            </Section>
          )}
        </div>

        <div className="space-y-3 border-t px-4 py-3">
          <label className="flex items-center justify-between gap-3 text-sm">
            {t('tasks.board.filter.hideEmpty', 'Скрывать колонки без подходящих карточек')}
            <Switch checked={filters.hideEmpty}
              onCheckedChange={(value) => onChange({ ...filters, hideEmpty: value })} />
          </label>
          <Button variant="outline" className="w-full" onClick={onReset}>
            {t('tasks.board.filter.reset', 'Сбросить фильтр')}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
