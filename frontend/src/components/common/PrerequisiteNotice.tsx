/**
 * Плашка «чего не хватает, чтобы заполнить форму».
 *
 * Единая форма подсказки о НЕВЫПОЛНЕННЫХ ПРЕДПОСЫЛКАХ: пустой справочник,
 * отсутствие согласованного документа, не заведённый родитель. Без неё
 * такое место выглядит как поломка — селект открывается пустым, кнопка
 * ничего не делает, и сотрудник идёт спрашивать вместо того, чтобы
 * дозаполнить справочник.
 *
 * Пункт показывается, только когда `when === true`, то есть когда условие
 * НЕ выполнено. Если не выполнено ни одного — компонент не рисует ничего,
 * поэтому его ставят в форму безусловно, рядом с полями, а не под `&&`.
 *
 * Точку в конце пункта ставит компонент: текст пишется без неё и
 * заканчивается тире, если дальше идёт ссылка («Реестр контрагентов пуст —»
 * + «добавьте поставщика» + «.»).
 */

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export interface Prerequisite {
  /** Условие НЕВЫПОЛНЕННОСТИ: `true` — пункт показывается. */
  when: boolean;
  /** Текст пункта, без завершающей точки. */
  text: ReactNode;
  /** Куда идти за недостающим. */
  to?: string;
  /** Подпись ссылки; без неё ссылка не рисуется. */
  linkText?: string;
}

interface Props {
  /** Заголовок карточки. В `inline` не показывается. */
  title?: string;
  items: Prerequisite[];
  /**
   * `card` — плашка над формой (не хватает справочников для всей формы);
   * `inline` — строчка под конкретным полем (пуст список именно этого поля).
   */
  variant?: 'card' | 'inline';
  className?: string;
}

function Line({ item }: { item: Prerequisite }) {
  return (
    <>
      {item.text}
      {item.to && item.linkText ? (
        <>
          {' '}
          <Link to={item.to} className="underline underline-offset-2">
            {item.linkText}
          </Link>
        </>
      ) : null}
      .
    </>
  );
}

export function PrerequisiteNotice({ title, items, variant = 'card', className }: Props) {
  const missing = items.filter((item) => item.when);
  if (missing.length === 0) return null;

  if (variant === 'inline') {
    return (
      <p role="note" className={cn('mt-1.5 text-xs text-muted-foreground', className)}>
        {missing.map((item, index) => (
          <span key={index}>
            {index > 0 && ' '}
            <Line item={item} />
          </span>
        ))}
      </p>
    );
  }

  return (
    <Card role="note" className={cn('mb-6 border-amber-500/50', className)}>
      <CardContent className="pt-6 text-sm">
        {title && <p className="font-medium mb-2">{title}</p>}
        <ul className="list-disc pl-5 space-y-1 text-muted-foreground">
          {missing.map((item, index) => (
            <li key={index}>
              <Line item={item} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
