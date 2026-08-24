/**
 * Сессия внешнего участника конференции.
 *
 * Гость — человек без учётки: открыл ссылку-приглашение, назвался, вошёл в
 * звонок. Его токен нельзя класть туда же, где живёт токен сотрудника
 * (`localStorage`, ключ `access`), по двум причинам, и обе неприятные:
 *
 *  * сотрудник, открывший гостевую ссылку, затёр бы себе рабочую сессию;
 *  * гостевой токен пережил бы закрытие вкладки на чужом или общем
 *    компьютере — а это ключ от переговорной.
 *
 * Отсюда `sessionStorage` и отдельный ключ: сессия живёт ровно одну вкладку
 * и умирает вместе с ней.
 */
const KEY = 'htq_conference_guest';

export interface GuestSession {
  token: string;
  roomId: string;
  displayName: string;
  title: string;
  /** Абсолютное время истечения токена, мс — по нему протухшая сессия
   *  отбрасывается, не дожидаясь отказа от SFU. */
  expiresAt: number;
  /** Рантайм-конфиг конференции: у гостя нет доступа к /conference/config,
   *  поэтому адрес сигналинга приезжает вместе с токеном. */
  conference: unknown;
}

export function saveGuestSession(session: GuestSession): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // Приватный режим или переполненное хранилище — не повод не пустить
    // человека в звонок: сессия просто не переживёт перезагрузку страницы.
  }
}

export function readGuestSession(): GuestSession | null {
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as GuestSession;
    if (!parsed?.token || !parsed?.roomId) return null;
    if (parsed.expiresAt && parsed.expiresAt <= Date.now()) {
      clearGuestSession();
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearGuestSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* см. saveGuestSession */
  }
}
