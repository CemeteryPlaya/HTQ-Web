/**
 * Готовые колонки реестров модуля (задача 8): «Статус» — бейдж по словарю
 * вида документа; «Сейчас у» — исполнитель этапа или «нет исполнителя».
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import i18n from '@/i18n';

import { currentHoldersColumn, statusColumn } from './registryColumns';
import type { CurrentHolders } from './registryTypes';

const t = i18n.t.bind(i18n);

describe('statusColumn', () => {
  it('рисует StatusBadge по коду строки', () => {
    const column = statusColumn<{ status: string }>(t, 'request');
    render(<>{column.render!({ status: 'on_review' })}</>);
    expect(screen.getByText('На согласовании')).toBeInTheDocument();
  });
});

describe('currentHoldersColumn', () => {
  const column = currentHoldersColumn<{ current_holders?: CurrentHolders | null }>(t);

  it('никого не ждёт — прочерк', () => {
    render(<>{column.render!({ current_holders: null })}</>);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('нет исполнителя — предупреждение с этапом', () => {
    render(<>{column.render!({
      current_holders: {
        stage: 'Технический директор', users: [], position: null, since: '', no_executor: true,
      },
    })}</>);
    expect(screen.getByText(/Нет исполнителя: Технический директор/)).toBeInTheDocument();
  });

  it('есть держатели — имена, этап и «с» дата', () => {
    render(<>{column.render!({
      current_holders: {
        stage: 'Финансовый директор',
        users: [{ id: 1, name: 'Иванов А.' }, { id: 2, name: 'Петров Б.' }],
        position: null,
        since: '2026-09-27T20:30:00Z',
        no_executor: false,
      },
    })}</>);
    expect(screen.getByText('Иванов А., Петров Б.')).toBeInTheDocument();
    expect(screen.getByText(/Финансовый директор/)).toBeInTheDocument();
    expect(screen.getByText(/28.09.2026 01:30/)).toBeInTheDocument();
  });
});
