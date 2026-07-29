/**
 * Ссылка на предметный объект согласования.
 *
 * `subject_title`/`subject_url` строит колбэк `describe` предметной аппки —
 * движок не имеет права импортировать её модели и потому не знает ни как
 * назвать строку, ни где она живёт. Из этого следуют два случая, которые
 * здесь и разведены:
 *
 * 1. **`describe` не сработал** (тип больше не зарегистрирован, объект
 *    удалён) — бэкенд отдаёт `null`. Показываем техническую пару
 *    `subject_type #id`: это всё, что о строке достоверно известно.
 * 2. **URL пришёл, но такой страницы в SPA нет.** Так сейчас и обстоит с
 *    `/contracts/budgets/{id}` и соседями: API их знает, интерфейса ещё
 *    нет. Ссылка вела бы в 404, поэтому заголовок показывается текстом.
 *    Проверка идёт по НАСТОЯЩЕЙ таблице роутов, а не по списку известных
 *    префиксов: когда карточки договоров появятся, ссылки оживут сами,
 *    без правок здесь.
 */

import { Link, matchPath } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';

import { protectedRoutes, publicRoutes } from '@/app/routing/routeDefinitions';
import { cn } from '@/lib/utils';

const ALL_PATHS = [...publicRoutes, ...protectedRoutes].map((route) => route.path);

/** Есть ли в SPA страница, которая отрисует этот путь. */
function isRoutableUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  // Только внутренние пути: внешний адрес роутером не разрешается, а
  // отправлять пользователя на чужой хост из карточки согласования незачем.
  if (!url.startsWith('/')) return false;
  const pathname = url.split(/[?#]/)[0];
  return ALL_PATHS.some((pattern) => matchPath(pattern, pathname) !== null);
}

interface Props {
  title: string | null;
  url: string | null;
  subjectType: string;
  subjectId: number;
  className?: string;
}

export function SubjectLink({ title, url, subjectType, subjectId, className }: Props) {
  const label = title ?? `${subjectType} #${subjectId}`;

  if (!isRoutableUrl(url)) {
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
