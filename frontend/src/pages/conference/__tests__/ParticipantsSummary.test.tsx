/**
 * Сводка «кто был и когда»: минуты считаются от начала встречи, а не от
 * абсолютного времени, — иначе человеку пришлось бы вычитать в уме.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ParticipantsSummary } from '../ConferenceSessionDetail';

const participant = (over = {}) => ({
  id: 1, user_id: 1, display_name: 'Пётр', is_guest: false,
  joined_at: '2026-08-25T10:02:00Z', left_at: '2026-08-25T10:17:00Z',
  joined_offset_ms: 120000, left_offset_ms: 1020000, ...over,
});

describe('ParticipantsSummary', () => {
  it('показывает минуту входа и выхода', () => {
    render(<ParticipantsSummary participants={[participant()]} />);

    expect(screen.getByText('02:00')).toBeInTheDocument();
    expect(screen.getByText('17:00')).toBeInTheDocument();
  });

  it('не вышедшего помечает как досидевшего до конца', () => {
    render(<ParticipantsSummary participants={[participant({
      id: 2, left_at: null, left_offset_ms: null,
    })]} />);

    expect(screen.getByText(/до конца/i)).toBeInTheDocument();
  });

  it('гостя помечает', () => {
    render(<ParticipantsSummary participants={[participant({
      id: 3, is_guest: true, display_name: 'Внешний',
    })]} />);

    expect(screen.getByText(/гость/i)).toBeInTheDocument();
  });
});
