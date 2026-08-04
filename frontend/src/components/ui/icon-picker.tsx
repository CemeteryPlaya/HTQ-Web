/**
 * IconPicker — выбор иконки из lucide-react с поиском и предпросмотром.
 *
 * ПОЧЕМУ НЕ ВЕСЬ НАБОР. В lucide больше полутора тысяч иконок; отрисовать их
 * все — это полторы тысячи React-компонентов в одном поповере и заметное
 * подвисание при открытии. Поэтому список фильтруется по запросу и режется до
 * `MAX_RESULTS`: редактор всё равно ищет по названию, а не листает.
 *
 * Имя иконки хранится строкой в БД (`HomeSectionItem.icon`), а сам компонент
 * достаётся по имени в `LucideIcon`. Незнакомое имя просто не рисуется — это
 * штатный случай для данных, заведённых до появления пикера.
 */
import { useMemo, useState } from 'react';
import * as LucideIcons from 'lucide-react';
import { Check, Search, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

const MAX_RESULTS = 120;

/** Имена всех иконок набора. Считается один раз на модуль: перебор ключей
 *  библиотеки на каждый рендер заметно дороже самого поиска. */
const ICON_NAMES: string[] = Object.keys(LucideIcons).filter((name) => {
  if (!/^[A-Z][A-Za-z0-9]*$/.test(name)) return false;
  if (name === 'Icon' || name === 'LucideIcon') return false;
  // Каждая иконка экспортируется трижды: `Award`, `AwardIcon`, `LucideAward`.
  // Это один и тот же компонент, и без отсева пикер показывал бы по три
  // одинаковых плитки на каждую иконку. Оставляем каноническое имя.
  if (name.startsWith('Lucide')) return false;
  if (name.endsWith('Icon') && name !== 'Icon') return false;
  const candidate = (LucideIcons as Record<string, unknown>)[name];
  return typeof candidate === 'object' || typeof candidate === 'function';
});

/** Рисует иконку по имени. Экспортируется отдельно: тем же способом её
 *  достаёт лендинг, и правило «неизвестное имя не рисуем» должно быть одно. */
export function LucideIcon({ name, className }: { name: string; className?: string }) {
  if (!name) return null;
  const Cmp = (LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string }>>)[name];
  if (!Cmp) return null;
  return <Cmp className={className} />;
}

export function IconPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const source = q
      ? ICON_NAMES.filter((n) => n.toLowerCase().includes(q))
      : ICON_NAMES;
    return source.slice(0, MAX_RESULTS);
  }, [query]);

  return (
    <div className="flex items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" className="w-full justify-start gap-2 font-normal">
            {value
              ? <><LucideIcon name={value} className="h-4 w-4" /> {value}</>
              : <span className="text-muted-foreground">Выбрать иконку</span>}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[320px] p-0" align="start">
          <div className="relative border-b p-2">
            <Search className="absolute left-4 top-4 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск: sun, zap, building…"
              className="pl-7"
            />
          </div>
          <div className="grid max-h-[260px] grid-cols-6 gap-1 overflow-y-auto p-2">
            {results.map((name) => (
              <button
                key={name}
                type="button"
                title={name}
                onClick={() => { onChange(name); setOpen(false); }}
                className={cn(
                  'flex h-9 w-9 items-center justify-center rounded-md border transition-colors hover:bg-accent',
                  value === name && 'border-primary bg-accent',
                )}
              >
                <LucideIcon name={name} className="h-4 w-4" />
              </button>
            ))}
            {results.length === 0 && (
              <p className="col-span-6 py-6 text-center text-sm text-muted-foreground">
                Ничего не найдено
              </p>
            )}
          </div>
          {!query && ICON_NAMES.length > MAX_RESULTS && (
            <p className="border-t px-3 py-2 text-xs text-muted-foreground">
              Показаны первые {MAX_RESULTS} из {ICON_NAMES.length}. Уточните поиск.
            </p>
          )}
        </PopoverContent>
      </Popover>
      {value && (
        <Button
          variant="ghost" size="icon" className="h-9 w-9 shrink-0"
          onClick={() => onChange('')}
          aria-label="Убрать иконку"
        >
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

export default IconPicker;
