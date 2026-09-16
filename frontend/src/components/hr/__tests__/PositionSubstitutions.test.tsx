/**
 * Секция замещения на карточке должности.
 *
 * Проверяем не разметку, а три вещи, ради которых секция существует:
 * правило видно со всеми колонками документа (кто, каким приказом, до
 * какой даты), истёкшее правило отличимо от действующего, и ошибка
 * пересечения от сервера показывается человеку, а не глотается.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PositionSubstitutions } from '../PositionSubstitutions';
import * as hrApi from '@/api/hr';

vi.mock('@/api/hr', async (importOriginal) => {
  const actual = await importOriginal<typeof hrApi>();
  return { ...actual, fetchSubstitutions: vi.fn(), createSubstitution: vi.fn(),
           deleteSubstitution: vi.fn() };
});

const POSITIONS = [
  { id: 1, title: 'Генеральный директор' },
  { id: 2, title: 'Операционный директор' },
  { id: 3, title: 'Финансовый директор' },
];

const ROW = {
  id: 10, position_id: 1, substitute_position_id: 2,
  substitute_position_title: 'Операционный директор',
  kind: 'primary' as const, basis: 'Приказ ГД; доверенность',
  note: 'Право первой подписи', valid_from: '2026-01-01', valid_to: null,
  created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00',
};

beforeEach(() => vi.clearAllMocks());

describe('PositionSubstitutions', () => {
  it('показывает замещающего, вид, основание и примечание', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([ROW]);
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);

    expect(await screen.findByText('Операционный директор')).toBeInTheDocument();
    expect(screen.getByText(/Основной/)).toBeInTheDocument();
    expect(screen.getByText(/Приказ ГД; доверенность/)).toBeInTheDocument();
    expect(screen.getByText(/Право первой подписи/)).toBeInTheDocument();
  });

  it('пустая матрица объясняет себя, а не показывает пустоту', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([]);
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);
    expect(await screen.findByText(/замещающих не назначено/i)).toBeInTheDocument();
  });

  it('истёкшее правило помечено, а не выглядит действующим', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([
      { ...ROW, valid_to: '2025-12-31' },
    ]);
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);
    expect(await screen.findByText(/истекло/i)).toBeInTheDocument();
  });

  it('ошибку пересечения от сервера показывает человеку', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([]);
    vi.mocked(hrApi.createSubstitution).mockRejectedValue({
      response: { status: 409, data: { detail: 'Закройте прежнее замещение датой окончания перед добавлением нового' } },
    });
    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);

    const addBtn = await screen.findByRole('button', { name: /добавить/i });
    await userEvent.click(addBtn);

    // Выбрать замещающую должность
    const selectTrigger = screen.getByRole('combobox', { name: /замещающая должность/i });
    await userEvent.click(selectTrigger);
    const option = await screen.findByText('Операционный директор');
    await userEvent.click(option);

    // Заполнить основание
    await userEvent.type(screen.getByLabelText(/основание/i), 'Приказ ГД');

    // Кликнуть сохранить
    const saveBtn = screen.getByRole('button', { name: /сохранить/i });
    await userEvent.click(saveBtn);

    // Проверить, что ошибка показана
    await waitFor(() =>
      expect(screen.getByText(/Закройте прежнее замещение/i)).toBeInTheDocument());
  });
});
