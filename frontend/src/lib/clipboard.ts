/**
 * Копирование в буфер обмена, которое работает не только по HTTPS.
 *
 * `navigator.clipboard` существует **только в защищённом контексте** — то
 * есть по HTTPS или на `localhost`. Открытый по `http://192.168.x.x:3000`
 * стенд (обычный способ посмотреть платформу с другого устройства) получает
 * `navigator.clipboard === undefined`, и вызов падает с TypeError. Если
 * обработчик кнопки не ловит ошибку — а до этого модуля не ловил ни один из
 * девяти в проекте, — кнопка молча не делает ничего.
 *
 * Особенно больно это било там, где копируют то, что показывается ОДИН раз:
 * временный пароль в HR-учётках, реквизиты инфраструктуры. Не скопировал —
 * значит переписывай с экрана или сбрасывай заново.
 *
 * Поэтому здесь две попытки подряд:
 *
 * 1. `navigator.clipboard.writeText` — если он есть и контекст защищённый;
 * 2. скрытая `<textarea>` + `document.execCommand('copy')` — путь, который
 *    работает по обычному HTTP. `execCommand` объявлен устаревшим, но
 *    остаётся единственным способом скопировать текст вне защищённого
 *    контекста и поддерживается всеми браузерами.
 *
 * Возвращает `false`, а не бросает: вызывающему нужно решить, показать
 * галочку «скопировано» или подсказку «выделите и скопируйте вручную», и
 * падение на ровном месте здесь ничему не помогает.
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;

  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Не вышло даже в защищённом контексте (нет разрешения, документ не в
      // фокусе) — не сдаёмся, пробуем запасной путь ниже.
    }
  }

  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    // Вне экрана, но НЕ display:none и не hidden: невидимый элемент нельзя
    // выделить, а без выделения execCommand копировать нечего.
    area.style.position = 'fixed';
    area.style.top = '0';
    area.style.left = '0';
    area.style.opacity = '0';
    area.style.pointerEvents = 'none';

    document.body.appendChild(area);
    area.select();
    // iOS игнорирует select() у readonly-поля — там работает только явный
    // диапазон.
    area.setSelectionRange(0, text.length);

    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
