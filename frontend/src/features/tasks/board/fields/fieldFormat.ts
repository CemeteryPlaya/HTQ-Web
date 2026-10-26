/**
 * Показ значений своих полей доски (этап S3): одно правило для значка на
 * карточке, блока «Поля доски» в окне и строки ленты; тем же видом лента
 * пишет срок и начало задачи.
 */
import { format, parseISO } from 'date-fns';
import { enUS, ru } from 'date-fns/locale';
import type { TFunction } from 'i18next';
import { Calendar, CheckSquare, Hash, List, Type } from 'lucide-react';

import type { BoardFieldType } from '@/types/tasks';

/** Порядок типов в выборе при создании поля — как в Trello. */
export const FIELD_TYPES: BoardFieldType[] = ['text', 'number', 'date', 'checkbox', 'list'];

export const FIELD_TYPE_ICON = {
  text: Type, number: Hash, date: Calendar, checkbox: CheckSquare, list: List,
} as const;

export function fieldTypeLabel(type: BoardFieldType, t: TFunction): string {
  switch (type) {
    case 'text': return t('tasks.fields.type.text', 'Текст');
    case 'number': return t('tasks.fields.type.number', 'Число');
    case 'date': return t('tasks.fields.type.date', 'Дата');
    case 'checkbox': return t('tasks.fields.type.checkbox', 'Флажок');
    default: return t('tasks.fields.type.list', 'Список');
  }
}

/** Дата поля — как сроки на доске: год только если не текущий. */
export function fieldDate(iso: string, language: string | undefined): string {
  const date = parseISO(iso);
  const locale = language?.startsWith('en') ? enUS : ru;
  return format(date, date.getFullYear() === new Date().getFullYear() ? 'd MMM' : 'd MMM yyyy',
    { locale });
}

/** Число строкой с сервера (`"1234.5"`) — с разрядами по языку интерфейса. */
export function fieldNumber(value: string, language: string | undefined): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return new Intl.NumberFormat(language?.startsWith('en') ? 'en-US' : 'ru-RU',
    { maximumFractionDigits: 4 }).format(number);
}
