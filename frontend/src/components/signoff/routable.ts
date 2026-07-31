/**
 * Ведёт ли ссылка на предметный объект в живую страницу SPA.
 *
 * `subject_url` строит предметная аппка (колбэк `describe` в её
 * `approval_hooks`), и знать, есть ли для этого пути страница во фронтенде,
 * она не может. Поэтому проверяем по НАСТОЯЩЕЙ таблице роутов, а не по
 * списку известных префиксов: заведут страницу — ссылка оживёт сама.
 *
 * Отдельным модулем, а не экспортом из `SubjectLink`: файл с компонентом,
 * экспортирующий ещё и функцию, ломает fast refresh (react-refresh).
 */

import { matchPath } from 'react-router-dom';

import { protectedRoutes, publicRoutes } from '@/app/routing/routeDefinitions';

const ALL_PATHS = [...publicRoutes, ...protectedRoutes].map((route) => route.path);

export function isRoutableUrl(url: string | null | undefined): boolean {
  // Только внутренние пути: внешний адрес роутером не разрешается, а
  // отправлять пользователя на чужой хост из карточки согласования незачем.
  if (!url) return false;
  if (!url.startsWith('/')) return false;
  const pathname = url.split(/[?#]/)[0];
  return ALL_PATHS.some((pattern) => matchPath(pattern, pathname) !== null);
}
