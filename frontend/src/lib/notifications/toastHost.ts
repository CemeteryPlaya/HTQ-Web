/**
 * Смонтирован ли приёмник тостов — тот самый `<Toaster/>` из sonner, в котором
 * карточки уведомлений появляются в правом нижнем углу страницы.
 *
 * Зачем вообще знать: **sonner доставляет тост только тем подписчикам, что
 * подписаны в момент вызова**, и ничего не копит. В его исходнике это одна
 * строка — `addToast = e => { this.publish(e); this.toasts = [...] }`, а
 * `subscribe` прошлое не проигрывает: список `toasts` нужен ему только для
 * `dismiss`. Значит `toast(...)`, вызванный до монтирования `<Toaster/>`,
 * пропадает молча — без исключения, без предупреждения, без следа в DOM.
 *
 * Это не теория. В `App.tsx` `<Toaster/>` монтируется по таймеру 1500 мс (плюс
 * загрузка отдельного чанка), а колокольчик в шапке — по таймеру 1200 мс и
 * сразу запрашивает список уведомлений. То есть на КАЖДОМ открытии платформы
 * первая порция уведомлений разбиралась раньше, чем появлялся приёмник:
 * `playNotificationSound` отрабатывал, id уходил в «уже показанные», а карточка
 * не появлялась ни тогда, ни потом. Снаружи это выглядело ровно так, как на это
 * и жаловались: звук есть, уведомления нет.
 *
 * Отсюда правило, которое держит этот модуль: **ничего не отправлять в пустоту**
 * — источник уведомлений ждёт готовности приёмника и до неё не трогает ни звук,
 * ни отметку «показано». Проверять готовность таймером или щупом по DOM было бы
 * гаданием: приёмник сам сообщает о себе.
 */
import { useSyncExternalStore } from 'react';

let mounted = false;
const listeners = new Set<() => void>();

/** Вызывается самим `<Toaster/>` на монтировании и размонтировании. */
export function setToastHostMounted(value: boolean): void {
  if (mounted === value) return;
  mounted = value;
  listeners.forEach((listener) => listener());
}

export function isToastHostMounted(): boolean {
  return mounted;
}

export function subscribeToastHost(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Готовность приёмника как состояние компонента.
 *
 * `getServerSnapshot` возвращает `false`: на сервере (и в любом рендере без
 * DOM) приёмника нет по определению, и притвориться готовым — значит вернуть
 * ту самую потерю тостов, ради которой модуль и написан.
 */
export function useToastHostMounted(): boolean {
  return useSyncExternalStore(subscribeToastHost, isToastHostMounted, () => false);
}
