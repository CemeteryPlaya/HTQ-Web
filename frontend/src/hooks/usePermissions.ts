import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { accessApi } from '@/api/access';
import {
  levelFor,
  meetsLevel,
  scopeFor,
  type AccessLevel,
  type AccessScope,
  type PermissionMap,
} from '@/lib/auth/permissions';
import type { AccessMe } from '@/types/access';

/**
 * Права текущего пользователя в компании запроса (`/access/v1/me`, §4.5).
 *
 * Заменяет ролевые проверки во фронте. `useHRLevel` **не заменяет** — тот
 * относится к внутренней модели HR и живёт своей жизнью (§1.6 спеки).
 *
 * **Отказ в закрытую.** Пока ответа нет — загрузка, ошибка сети, отсутствие
 * контекста компании — карта прав пуста, а значит разрешено ровно ничего.
 * Обратное поведение (показать, пока не знаем) отдало бы пользователю разделы,
 * которых сервер ему не даст, и разбираться пришлось бы с 403 в консоли, а не
 * с причиной.
 */
export interface Permissions {
  /** Слаг компании запроса; `null` вне контекста компании — не ошибка. */
  company: string | null;
  /** Уровень модуля; `none`, если модуля нет в карте. */
  level: (module: string) => AccessLevel;
  /** Правило §3: разрешено, если уровень не ниже требуемого. */
  atLeast: (module: string, required: AccessLevel) => boolean;
  /** Область модуля; `null`, если доступа нет. */
  scope: (module: string) => AccessScope | null;
  /** Компании ниже по внешней иерархии. Только отображение (§7). */
  subordinateCompanies: string[];
  isLoading: boolean;
  /**
   * Права НЕ УДАЛОСЬ получить — это не то же самое, что «прав нет».
   *
   * Различать обязательно. Пустая карта приходит штатно (вне контекста
   * компании, у человека без ролей), а неудачный запрос выглядит точно так
   * же: закрывается всё, включая администрирование, и человек ищет причину
   * в правах, хотя дело в недоступной ручке. Ровно так и вышло при первой
   * проверке стадии 2 — dev-прокси не знал про `/api/access/`, и
   * администратор платформы остался без единого раздела.
   */
  isError: boolean;
  /** Повторить запрос прав — для экрана «не загрузились». */
  refetch: () => void;
}

const EMPTY: PermissionMap = {};

export function usePermissions(): Permissions {
  const { data, isLoading, isError, refetch } = useQuery<AccessMe>({
    queryKey: ['access', 'me'],
    queryFn: () => accessApi.getMe(),
    // Тот же горизонт, что у useHRLevel: права меняются редко, а запрос
    // висит на каждой защищённой странице.
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  return useMemo(() => {
    const permissions = data?.permissions ?? EMPTY;
    return {
      company: data?.company ?? null,
      level: (module) => levelFor(permissions, module),
      atLeast: (module, required) => meetsLevel(levelFor(permissions, module), required),
      scope: (module) => scopeFor(permissions, module),
      subordinateCompanies: data?.subordinate_companies ?? [],
      isLoading,
      isError,
      refetch: () => { void refetch(); },
    };
  }, [data, isLoading, isError, refetch]);
}

export default usePermissions;
