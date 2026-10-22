/**
 * Проверяющий качества выбора (T-11): необязательный пользователь. Пусто —
 * проверяет технический директор по должности (так решает сервер).
 * Поиск — общая ручка подбора пользователей (`users/options`, от 2 знаков,
 * не больше 20 строк), с задержкой ввода.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

import { searchUserOptions } from '@/api/users';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const SEARCH_DELAY_MS = 250;

interface Props {
  value: number | null;
  /** Подпись выбранного (имя), если известна. */
  valueLabel: string | null;
  onChange: (id: number | null, label: string | null) => void;
}

export function ReviewerPicker({ value, valueLabel, onChange }: Props) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const found = useQuery({
    queryKey: ['users', 'options', query],
    queryFn: () => searchUserOptions(query),
    enabled: query.length >= 2,
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium">
          {value === null
            ? t('tender.tenders.reviewerDefault', 'Технический директор (по должности)')
            : valueLabel ?? t('tender.tenders.reviewerUser', 'Пользователь № {{id}}', { id: value })}
        </span>
        {value !== null && (
          <Button
            type="button" size="icon" variant="ghost" className="h-7 w-7"
            aria-label={t('tender.tenders.reviewerReset', 'Вернуть технического директора')}
            onClick={() => onChange(null, null)}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>
      <Label htmlFor="tender-reviewer-search" className="sr-only">
        {t('tender.tenders.reviewerSearch', 'Найти пользователя')}
      </Label>
      <Input
        id="tender-reviewer-search"
        value={search}
        placeholder={t('tender.tenders.reviewerSearchHint', 'Другой проверяющий: начните вводить имя')}
        onChange={(event) => setSearch(event.target.value)}
      />
      {query.length >= 2 && (found.data ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {(found.data ?? []).map((user) => (
            <Button
              key={user.id} type="button" size="sm" variant="outline"
              onClick={() => { onChange(user.id, user.full_name); setSearch(''); }}
            >
              {user.full_name}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
