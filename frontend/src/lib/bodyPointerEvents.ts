/**
 * Снятие осиротевшей модальной блокировки с <body>.
 *
 * Radix в модальном режиме ставит на <body> `pointer-events: none` и снимает
 * его на пути закрытия. Если внутри модалки был открыт вложенный слой (Select,
 * Popover, DropdownMenu, Command) и модалку закрыли, НЕ выбрав в нём значение
 * (Escape / «Отмена» / «крестик»), восстановление теряется: диалог уходит из
 * DOM, а блокировка остаётся — внешне это «фриз», при котором всё видно, но ни
 * одна кнопка не реагирует.
 *
 * Логика вынесена из компонента-сторожа отдельно, чтобы её можно было звать и
 * проверять без монтирования React-дерева.
 */

/** Портированные Radix-слои, которые ЗАКОННО держат блокировку <body>. */
const OPEN_LAYER_SELECTOR = [
  '[role="dialog"]',
  '[role="alertdialog"]',
  '[role="listbox"]',
  '[role="menu"]',
  '[data-radix-popper-content-wrapper]',
].join(',');

/**
 * Снимает блокировку, ТОЛЬКО если в DOM не осталось ни одного открытого
 * модального слоя. Пока хоть один открыт — не вмешивается, и своя логика Radix
 * продолжает работать как есть.
 *
 * @returns было ли что-то снято (для тестов и отладки).
 */
export function releaseStuckBodyLock(): boolean {
  if (document.body.style.pointerEvents !== 'none') return false;
  if (document.querySelector(OPEN_LAYER_SELECTOR)) return false;
  document.body.style.removeProperty('pointer-events');
  return true;
}
