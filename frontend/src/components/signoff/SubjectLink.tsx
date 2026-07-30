/**
 * Ссылка на предметный объект согласования.
 *
 * `subject_title`/`subject_url` строит колбэк `describe` предметной аппки —
 * движок не имеет права импортировать её модели и потому не знает ни как
 * назвать строку, ни где она живёт. Отсюда два случая, которые здесь
 * разведены:
 *
 * 1. **`describe` не сработал** (тип больше не зарегистрирован, объект
 *    удалён) — бэкенд отдаёт `null`. Показываем техническую пару
 *    `subject_type #id`: это всё, что о строке достоверно известно.
 * 2. **URL пришёл, но такой страницы в SPA нет.** Тогда ссылка вела бы в
 *    404, поэтому заголовок показывается текстом. Проверку делает
 *    `isRoutableUrl` — по настоящей таблице роутов.
 *
 * **Про `processId`.** Там, где строка сама по себе является задачей
 * согласования (очередь «Ждёт меня»), заголовок ведёт НЕ на документ, а на
 * карточку процесса: у неё есть и боковое меню раздела, и кнопки решения, и
 * тот же документ внутри. Уйти на страницу документа всё равно можно —
 * мелкой ссылкой ниже, — но это уже выход из раздела, и он не должен быть
 * основным действием.
 */

import { Link } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';

import { cn } from '@/lib/utils';

import { isRoutableUrl } from './routable';

interface Props {
  title: string | null;
  url: string | null;
  subjectType: string;
  subjectId: number;
  /** Задан — заголовок ведёт на карточку этого согласования, а не на
   *  документ. Для очереди согласований. */
  processId?: number;
  className?: string;
}

export function SubjectLink({
  title,
  url,
  subjectType,
  subjectId,
  processId,
  className,
}: Props) {
  const label = title ?? `${subjectType} #${subjectId}`;
  const routable = isRoutableUrl(url);

  if (processId !== undefined) {
    return (
      <div className="min-w-0">
        <Link
          to={`/signoff/processes/${processId}`}
          className={cn('font-medium hover:underline underline-offset-2', className)}
          title={`${subjectType} #${subjectId}`}
        >
          {label}
        </Link>
        {routable && (
          <div>
            <Link
              to={url as string}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline underline-offset-2"
            >
              открыть карточку в своём разделе
              <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
            </Link>
          </div>
        )}
      </div>
    );
  }

  if (!routable) {
    return (
      <span className={cn('font-medium', className)} title={`${subjectType} #${subjectId}`}>
        {label}
      </span>
    );
  }

  return (
    <Link
      to={url as string}
      className={cn(
        'font-medium inline-flex items-center gap-1 hover:underline underline-offset-2',
        className,
      )}
    >
      {label}
      <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-60" />
    </Link>
  );
}
