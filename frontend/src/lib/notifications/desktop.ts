/**
 * Уведомление в углу ЭКРАНА, а не страницы.
 *
 * Карточка sonner живёт внутри вкладки: свернули окно, ушли в другую программу
 * — и её никто не увидит, хотя звук при этом играет (аудио фоновой вкладке
 * браузер не глушит). Ровно этот разрыв закрывает Notification API: система
 * показывает уведомление поверх всего, у Windows — в правом нижнем углу.
 *
 * Три вещи здесь сделаны намеренно:
 *
 * 1. **Разрешение не спрашивается при загрузке.** Браузеры штрафуют сайты,
 *    которые просят его без повода, и человек почти всегда жмёт «Блокировать»
 *    — а это решение необратимо из кода. Поэтому запрос идёт только по жесту:
 *    открыли колокольчик, нажали на мессенджер.
 * 2. **Конструктор обёрнут в try/catch.** В Chrome под Android `new
 *    Notification()` не «не показывает уведомление», а БРОСАЕТ TypeError:
 *    там уведомления умеет только service worker. Без catch падал бы весь
 *    разбор списка уведомлений, то есть и звук, и карточка в углу страницы.
 * 3. **`tag` обязателен у вызывающего.** Одно и то же сообщение может прийти
 *    двумя путями (сокет мессенджера и опрос уведомлений); одинаковый `tag`
 *    заставляет систему заменить уведомление, а не показать второе.
 */

export interface DesktopNotificationOptions {
  title: string;
  body?: string;
  /** Ключ схлопывания дублей на стороне ОС. */
  tag?: string;
  /** Клик по уведомлению — обычно переход к источнику. */
  onClick?: () => void;
}

function supported(): boolean {
  return typeof window !== 'undefined' && typeof Notification !== 'undefined';
}

/** Есть ли смысл спрашивать разрешение (браузер умеет, человек ещё не решал). */
export function canAskDesktopPermission(): boolean {
  return supported() && Notification.permission === 'default';
}

/**
 * Спросить разрешение. Зовётся ИЗ ОБРАБОТЧИКА ЖЕСТА — см. пункт 1 в шапке.
 * Молчит, если спрашивать нечего: разрешение уже дано или уже отклонено.
 */
export function requestDesktopPermission(): void {
  if (!canAskDesktopPermission()) return;
  Notification.requestPermission().catch(() => {
    /* отказ — это ответ, повторно не пристаём */
  });
}

/**
 * Показать уведомление ОС. Возвращает, дошло ли дело до показа, — вызывающему
 * это нужно, чтобы не считать уведомление доставленным, когда его не было.
 */
export function showDesktopNotification({
  title,
  body,
  tag,
  onClick,
}: DesktopNotificationOptions): boolean {
  if (!supported() || Notification.permission !== 'granted') return false;

  try {
    const notification = new Notification(title, { body, tag });
    if (onClick) {
      notification.onclick = () => {
        window.focus();
        notification.close();
        onClick();
      };
    }
    return true;
  } catch {
    // Платформа без конструктора (Chrome/Android) — см. пункт 2 в шапке.
    return false;
  }
}

/**
 * Смотрит ли человек сейчас на страницу.
 *
 * Одного `document.hidden` мало: вкладка активна, но окно браузера за окном
 * другой программы — `hidden` при этом `false`, а страницы человек не видит.
 * `hasFocus()` ловит и этот случай.
 */
export function pageIsInBackground(): boolean {
  if (typeof document === 'undefined') return false;
  if (document.hidden) return true;
  return typeof document.hasFocus === 'function' ? !document.hasFocus() : false;
}
