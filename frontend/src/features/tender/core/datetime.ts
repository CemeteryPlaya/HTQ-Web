/**
 * Момент времени ↔ значение поля `datetime-local` (местное время браузера,
 * `ГГГГ-ММ-ДДTЧЧ:ММ`). Сервер хранит и отдаёт ISO с поясом; поле знает
 * только местное время — переводим на границе формы.
 */
const pad = (value: number) => String(value).padStart(2, '0');

export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return '';
  return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}`
    + `T${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
}

/** `null` — пусто или не дата. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}
