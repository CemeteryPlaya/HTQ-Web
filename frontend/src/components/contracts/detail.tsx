/**
 * Общие куски карточек домена «Договоры»: ссылка «назад», поле «подпись —
 * значение», скелет загрузки.
 *
 * Все три карточки (бюджет, контрагент, договор) устроены одинаково —
 * заголовок с плашками, несколько блоков полей, таблица связанных строк, —
 * и различаются только содержимым полей. Держать эту рамку в одном месте
 * дешевле, чем трижды повторять разметку и трижды же её править.
 */

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
    >
      <ArrowLeft className="h-4 w-4" />
      {children}
    </Link>
  );
}

/**
 * Пара «подпись — значение».
 *
 * `value` намеренно принимает ReactNode, а не строку: половина полей —
 * плашки и ссылки, и приводить их к тексту ради единообразия значило бы
 * потерять именно то, ради чего человек открыл карточку.
 */
export function Field({
  label,
  children,
  className,
  hint,
}: {
  label: string;
  children: ReactNode;
  className?: string;
  /** Пояснение под значением — там, где само число требует объяснения. */
  hint?: string;
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm break-words">{children}</dd>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Сетка полей карточки: одна колонка на телефоне, три на широком экране. */
export function FieldGrid({ children }: { children: ReactNode }) {
  return (
    <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
      {children}
    </dl>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-44 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}
