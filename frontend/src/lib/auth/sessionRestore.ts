/**
 * Восстановление сессии на новом поддомене компании (блок I.2, A1).
 *
 * Access-токен привязан к своему origin (localStorage и cookie без Domain —
 * см. profileStorage.ts), поэтому на `htq.htq.group` после входа на голом
 * `htq.group` его нет. Refresh-токен лежит в cookie на родительском домене и
 * виден здесь (схема — в докстринге companySwitch.ts). RequireAuth до
 * редиректа на /login зовёт `restoreSessionOnce()`: один обмен refresh → access
 * тем же механизмом, что у интерцептора (`refreshAccessToken` из api/client),
 * и только при неудаче отправляет на вход.
 *
 * Попытка — ОДНА на загрузку страницы: промис запоминается на уровне модуля,
 * поэтому повторные рендеры и другие экземпляры RequireAuth не шлют обмен
 * заново, а неудачный обмен не превращается в цикл «обмен → /login → обмен».
 */
import { refreshAccessToken } from '@/api/client';

import { getRefreshToken } from './profileStorage';

let attempt: Promise<boolean> | null = null;

/** Есть ли что обменивать: refresh-токен из cookie родительского домена. */
export const canRestoreSession = (): boolean => Boolean(getRefreshToken());

/**
 * Обменять refresh-cookie на access-токен, не больше одного раза за загрузку.
 * Резолвится `true`, если новый access-токен сохранён, иначе `false`; не
 * отклоняется никогда — вызывающему нужен только исход.
 */
export const restoreSessionOnce = (): Promise<boolean> => {
  if (attempt === null) {
    attempt = refreshAccessToken().then(
      () => true,
      () => false,
    );
  }
  return attempt;
};

/** Только для тестов: забыть попытку, как при новой загрузке страницы. */
export const resetSessionRestoreForTests = (): void => {
  attempt = null;
};
