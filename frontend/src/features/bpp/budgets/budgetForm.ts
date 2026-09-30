/**
 * Состояние формы F-01 и её проверки до отправки (ТЗ §6.4–6.5) — отдельно от
 * экрана: так их можно проверить без рендера, а файл экрана экспортирует
 * только компоненты (Fast Refresh).
 */
import { formatMoney, parseMoneyInput } from '../format';

import type { BudgetCard, BudgetLine, BudgetLineInput } from './api';
import { lessThan } from './cents';

export const COMMENT_MIN = 10;

/** Строка формы: `limit` — как ввёл человек, `locked` — статья не меняется. */
export interface EditLine {
  key: string;
  article_id: string;
  limit: string;
  comment: string;
  locked: boolean;
  /** «Задействовано» по статье; `null` — бюджет ещё не утверждён. */
  committed: string | null;
  /** «Оплачено факт» по статье — только для показа. */
  paid_fact: string | null;
}

export interface BudgetFormState {
  project_id: string;
  currency: string;
  lines: EditLine[];
  comment: string;
}

let lineSeq = 0;
export const nextLineKey = () => `line-${(lineSeq += 1)}`;

export const lineOf = (line: BudgetLine, locked: boolean): EditLine => ({
  key: nextLineKey(),
  article_id: line.article_id,
  limit: formatMoney(line.limit_amount),
  comment: line.comment,
  locked,
  committed: line.committed,
  paid_fact: line.paid_fact,
});

export const emptyLine = (correction: boolean): EditLine => ({
  key: nextLineKey(), article_id: '', limit: '0,00', comment: '', locked: false,
  committed: correction ? '0.00' : null,
  paid_fact: correction ? '0.00' : null,
});

/** Форма из карточки: в корректировке — строки черновика версии N+1, и у
 * строк, уже бывших в действующей версии, статья заперта (ТЗ §6.5 п.2). */
export function formOf(card: BudgetCard | undefined): BudgetFormState {
  if (!card) return { project_id: '', currency: 'KZT', lines: [], comment: '' };
  if (card.correction) {
    const active = new Set(card.lines.map((line) => line.article_id));
    return {
      project_id: card.project.id,
      currency: card.currency_code,
      comment: card.correction.comment,
      lines: card.correction.lines.map((line) => lineOf(line, active.has(line.article_id))),
    };
  }
  return {
    project_id: card.project.id,
    currency: card.currency_code,
    comment: '',
    lines: card.lines.map((line) => lineOf(line, false)),
  };
}

/** Ошибки по строкам (`key` строки → текст): статья выбрана и не повторяется
 * (BR-002), лимит — сумма ≥ 0, в корректировке — не ниже задействованного
 * (BR-004, текст ТЗ §6.5 п.3). */
export function validateLines(
  lines: EditLine[],
  { correction }: { correction: boolean },
): Record<string, string> {
  const errors: Record<string, string> = {};
  const seen = new Map<string, number>();
  lines.forEach((line, index) => {
    if (!line.article_id) {
      errors[line.key] = 'Выберите статью';
      return;
    }
    const first = seen.get(line.article_id);
    if (first !== undefined) {
      errors[line.key] = `Статья уже есть в бюджете, строка ${first + 1}`;
      return;
    }
    seen.set(line.article_id, index);
    const amount = parseMoneyInput(line.limit);
    if (amount === null || lessThan(amount, 0)) {
      errors[line.key] = 'Введите сумму в формате 1 250 000,00, не меньше нуля';
      return;
    }
    if (correction && line.committed && lessThan(amount, line.committed)) {
      errors[line.key] =
        `Лимит не может быть меньше задействованной суммы ${formatMoney(line.committed)}`;
    }
  });
  return errors;
}

export const linesInput = (lines: EditLine[]): BudgetLineInput[] => lines.map((line) => ({
  article_id: line.article_id,
  limit_amount: parseMoneyInput(line.limit) ?? '0.00',
  comment: line.comment.trim(),
}));
