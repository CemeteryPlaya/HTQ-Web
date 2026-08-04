/**
 * BodyPointerEventsGuard — страховка от «страница видна, но клики не работают».
 *
 * ПРОБЛЕМА. Radix в модальном режиме ставит на <body> `pointer-events: none`
 * и снимает его на пути закрытия. Если внутри модалки был открыт вложенный
 * слой (`Select`, `Popover`, `DropdownMenu`, `Command`) и модалку закрыли,
 * НЕ выбрав в нём значение — Escape, «Отмена» или «крестик», — восстановление
 * теряется: диалог уходит из DOM, а блокировка на <body> остаётся. Внешне это
 * выглядит как зависший фронт: всё отрисовано, скролл может работать, но ни
 * одна кнопка и ссылка не реагируют. Воспроизводится почти на любой форме
 * этого проекта, потому что почти в каждой есть выпадающий список.
 * Регрессия зафиксирована в components/__tests__/BodyPointerEventsGuard.test.tsx
 * (первый тест воспроизводит утечку без сторожа).
 *
 * Усугубляющий фактор: `@radix-ui/react-alert-dialog` тянет собственную копию
 * `@radix-ui/react-dialog` рядом с верхнеуровневой (1.1.14 против 1.1.15).
 * Реестр слоёв у Radix модульного уровня, поэтому две копии не видят слои
 * друг друга. Дедупликация версий — отдельная задача; сторож закрывает симптом
 * независимо от неё.
 *
 * РЕШЕНИЕ — инвариант, а не заплатка на конкретную модалку: если в DOM не
 * осталось ни одного открытого модального слоя, блокировки на <body> быть не
 * должно. Сторож следит за атрибутами <body> и за появлением/исчезновением
 * порталов и снимает ТОЛЬКО осиротевшую блокировку.
 *
 * Монтируется один раз в App.tsx.
 */
import { useEffect } from 'react';

import { releaseStuckBodyLock } from '@/lib/bodyPointerEvents';

export const BodyPointerEventsGuard = () => {
  useEffect(() => {
    // Проверяем после того, как Radix отработал свои cleanup-эффекты и снял
    // слои: на момент самой мутации DOM ещё может содержать закрывающийся
    // слой, и синхронная проверка дала бы ложноотрицательный результат.
    let scheduled = false;
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        releaseStuckBodyLock();
      });
    };

    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['style'],
      childList: true,
    });

    return () => observer.disconnect();
  }, []);

  return null;
};

export default BodyPointerEventsGuard;
