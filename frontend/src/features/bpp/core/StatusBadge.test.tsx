/**
 * Бейдж статуса документа модуля (ТЗ §15, §19, задача 8): подпись и тон по
 * словарю вида документа, неизвестный код — нейтральный бейдж с самим кодом.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusBadge } from './StatusBadge';

describe('StatusBadge', () => {
  it('известный статус — переведённая подпись и тон', () => {
    render(<StatusBadge kind="request" status="on_review" />);
    const badge = screen.getByText('На согласовании');
    expect(badge).toHaveAttribute('data-tone', 'progress');
  });

  it('тот же код — разная подпись в разных видах документа', () => {
    render(
      <>
        <StatusBadge kind="budget" status="approved" />
        <StatusBadge kind="request" status="approved" />
      </>,
    );
    expect(screen.getByText('Утверждён')).toBeInTheDocument();
    expect(screen.getByText('Утверждена')).toBeInTheDocument();
  });

  it('неизвестный статус — нейтральный бейдж с самим кодом, а не подмена', () => {
    render(<StatusBadge kind="request" status="mystery_code" />);
    const badge = screen.getByText('mystery_code');
    expect(badge).toHaveAttribute('data-tone', 'unknown');
    expect(badge).toHaveAttribute('title', 'Статус, неизвестный интерфейсу');
  });

  it('пустой статус — код «—», а не пустой бейдж', () => {
    render(<StatusBadge kind="request" status="" />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
