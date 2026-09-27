/**
 * Проверка файла до запроса — общая для панели документов и форм, где файл
 * выбирают раньше, чем появится его владелец.
 *
 * `accept` у input лишь подсказка диалогу выбора («Все файлы» её обходит), а
 * отказ сервера приходил бы уже после того, как ради файла сохранён черновик
 * и 20 МБ ушли по сети. Последнее слово — по-прежнему за сервером (сигнатура
 * содержимого, 415). Текст — тот же, что у отказов сервера (E-FIL-01/02):
 * по ТЗ §13.2 он один на формат и размер.
 */
import type { TFunction } from 'i18next';
import { toast } from 'sonner';

const MB = 1024 * 1024;

/** Что нужно проверке о типе файла: форматы и предельный размер. */
export interface FileRules {
  formats: string[];
  max_mb: number;
}

/** «PDF, DOCX, JPG, PNG» — как в текстах сервера; `.jpeg` и `.jpg` — одно. */
export function formatsLabel(formats: string[]): string {
  const labels: string[] = [];
  for (const ext of formats) {
    const label = ext === '.jpeg' ? 'JPG' : ext.replace(/^\./, '').toUpperCase();
    if (!labels.includes(label)) labels.push(label);
  }
  return labels.join(', ');
}

/** Годится ли файл по расширению и размеру; нет — объясняет тостом. */
export function acceptableFile(t: TFunction, file: File, rules: FileRules): boolean {
  const name = file.name.toLowerCase();
  const fits = rules.formats.some((ext) => name.endsWith(ext.toLowerCase()))
    && file.size <= rules.max_mb * MB;
  if (!fits) {
    toast.error(t('attachments.wrongType', {
      name: file.name, types: formatsLabel(rules.formats), mb: rules.max_mb,
    }));
  }
  return fits;
}
