/**
 * Выбор контрагента для договора и счёта (ТЗ §9.2, §10.2): поиск по реестру
 * от 3 символов наименования или от 4 цифр БИН/ИИН, только «Активен» (BR-030).
 * Выбранный подставляет БИН/ИИН, страну и признак плательщика НДС — это
 * делает сервер при сохранении; здесь только выбор.
 *
 * Пустой результат объясняется ссылкой на реестр контрагентов: СН и ПМ
 * заводят контрагента сами (ТЗ §05 п.9).
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { COUNTERPARTIES_BASE, COUNTERPARTIES_ENDPOINT } from '../counterparties/api';

import type { CounterpartyBrief } from './api';

interface Props {
  value: CounterpartyBrief | null;
  onChange: (counterparty: CounterpartyBrief) => void;
  disabled?: boolean;
  id?: string;
}

const enoughToSearch = (text: string) => {
  const trimmed = text.trim();
  return /^\d{4,}$/.test(trimmed) || trimmed.length >= 3;
};

export function CounterpartyPicker({ value, onChange, disabled = false, id }: Props) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), 300);
    return () => clearTimeout(timer);
  }, [text]);

  const results = useQuery({
    queryKey: ['bpp', 'counterparty-search', query],
    queryFn: () => api.get<{ items: CounterpartyBrief[] }>(COUNTERPARTIES_ENDPOINT, {
      params: { q: query, status: 'active', page_size: 25 },
    }).then((r) => r.data.items),
    enabled: open && enoughToSearch(query),
  });

  if (disabled) {
    return (
      <p className="text-sm">
        {value ? `${value.short_name || value.name} · ${value.reg_number}` : '—'}
      </p>
    );
  }

  const items = results.data ?? [];
  return (
    <div className="relative space-y-1">
      <Input
        id={id}
        value={open ? text : value ? `${value.short_name || value.name} · ${value.reg_number}` : text}
        placeholder={t('bpp.counterparties.pickHint', 'Наименование (от 3 букв) или БИН/ИИН (от 4 цифр)')}
        onFocus={() => { setOpen(true); setText(''); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(event) => setText(event.target.value)}
      />
      {open && enoughToSearch(query) && results.isSuccess && (
        <div className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border bg-popover p-1 shadow">
          {items.length === 0 ? (
            <p className="p-2 text-sm text-muted-foreground">
              {t('bpp.counterparties.notFound', 'Активных контрагентов не найдено.')}{' '}
              <Link className="text-primary underline" to={`${COUNTERPARTIES_BASE}/new`}>
                {t('bpp.counterparties.create', 'Создать')}
              </Link>
            </p>
          ) : items.map((item) => (
            <Button
              key={item.id}
              type="button"
              variant="ghost"
              className="h-auto w-full justify-start py-1.5 text-left"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => { onChange(item); setOpen(false); }}
            >
              <span className="leading-tight">
                <span className="block">{item.short_name || item.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {item.reg_number} · {item.country_code}
                  {item.is_verified ? '' : ` · ${t('bpp.counterparties.unverified', 'не проверен')}`}
                </span>
              </span>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
