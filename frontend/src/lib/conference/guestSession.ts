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
import i18next from '@/i18n';

const KEY = 'htq_conference_guest';

/** Языки, которые реально умеет показывать фронт (см. `src/i18n.js`). */
export const SUPPORTED_CONFERENCE_LOCALES = ['ru', 'en'] as const;
export type ConferenceLocale = (typeof SUPPORTED_CONFERENCE_LOCALES)[number];

/** Привести произвольное значение к тому, что понимает фронт, либо к «не
 *  задано». Тот же контракт, что и на бэкенде (`_normalize_locale` в
 *  `apps/cms/services/conference_invite_service.py`) — опечатка или будущий
 *  язык не должны ничего ломать, а должны молча вести себя как отсутствие
 *  локали. */
export function normalizeConferenceLocale(value: unknown): ConferenceLocale | null {
  return typeof value === 'string'
    && (SUPPORTED_CONFERENCE_LOCALES as readonly string[]).includes(value)
    ? (value as ConferenceLocale)
    : null;
}

/**
 * Переключить интерфейс на язык приглашения — не оставляя следа в
 * `localStorage`.
 *
 * `i18next-browser-languagedetector` по умолчанию кэширует ЛЮБОЙ явный
 * `changeLanguage()` в `localStorage` (ключ `i18nextLng`). Это правильно для
 * осознанного выбора человека (переключатель в шапке), но неправильно для
 * языка чужого приглашения: иначе после того, как гость уйдёт, следующий
 * сотрудник, открывший платформу с того же браузера (общий компьютер
 * переговорной — обычная ситуация для видеозвонков), получил бы язык,
 * который сам не выбирал, и не понял бы, почему. Поэтому кэширование на
 * время переключения отключается: язык гостя живёт в `sessionStorage`
 * (`GuestSession.locale` ниже) ровно по той же причине, по которой там же
 * живёт его токен — см. докстринг файла.
 */
export async function applyGuestLocale(
  locale: ConferenceLocale | null | undefined,
): Promise<void> {
  if (!locale) return;
  if (i18next.language?.split('-')[0] === locale) return;
  // `Services.languageDetector` типизирован как `any` в самом i18next —
  // это внутренний объект модуля, публичного типа для его `options` нет.
  const detector = i18next.services?.languageDetector;
  const prevCaches = detector?.options?.caches;
  if (detector?.options) detector.options.caches = [];
  try {
    await i18next.changeLanguage(locale);
  } finally {
    if (detector?.options && prevCaches !== undefined) detector.options.caches = prevCaches;
  }
}

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
  /** Язык приглашения — пусто/undefined, если организатор его не задавал.
   *  Хранится здесь же, а не только применяется на странице входа, иначе
   *  при переходе в комнату (обновление вкладки, прямой заход на /room/id)
   *  язык откатился бы на тот, что определит браузер. */
  locale?: ConferenceLocale | null;
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
