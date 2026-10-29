/**
 * Копирование текста в буфер обмена. Отдельным модулем — чтобы тесты
 * подменяли его целиком, а не `navigator.clipboard` (в jsdom его нет).
 * Без Clipboard API (http, старый браузер) — отказ: ссылку тогда копируют
 * из поля руками, оно рядом.
 */
export async function copyText(text: string): Promise<void> {
  if (!navigator.clipboard?.writeText) throw new Error('Clipboard API недоступен');
  await navigator.clipboard.writeText(text);
}
