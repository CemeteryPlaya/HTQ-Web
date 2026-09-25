/**
 * Секция замещения на карточке должности.
 *
 * Проверяем не разметку, а то, ради чего секция существует: правило видно
 * со всеми колонками документа (кто, каким приказом, до какой даты),
 * истёкшее и «должность неактивна» отличимы от действующего, интерфейс
 * даёт закрыть бессрочное правило (а не только удалить историю), выбор
 * замещающего не предлагает неактивные должности, и ошибка от сервера
 * доходит до человека — БЕЗ подмены `reportApiError`, иначе тест доказывает
 * только то, что вызван мок, а не то, что текст увидел человек.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PositionSubstitutions } from '../PositionSubstitutions';
import * as hrApi from '@/api/hr';
import { todayIso } from '@/lib/dates';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

vi.mock('@/api/hr', async (importOriginal) => {
  const actual = await importOriginal<typeof hrApi>();
  return {
    ...actual,
    fetchSubstitutions: vi.fn(),
    createSubstitution: vi.fn(),
    updateSubstitution: vi.fn(),
    deleteSubstitution: vi.fn(),
  };
});

const POSITIONS = [
  { id: 1, title: 'Генеральный директор', is_active: true },
  { id: 2, title: 'Операционный директор', is_active: true },
  { id: 3, title: 'Финансовый директор', is_active: true },
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

  it('замещающий из неактивной должности помечен, а не выглядит действующим', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([ROW]);
    const positionsWithInactiveSubstitute = [
      POSITIONS[0],
      { id: 2, title: 'Операционный директор', is_active: false },
      POSITIONS[2],
    ];
    renderWithProviders(
      <PositionSubstitutions positionId={1} positions={positionsWithInactiveSubstitute} />,
    );
    expect(await screen.findByText(/должность неактивна/i)).toBeInTheDocument();
  });

  it('в выборе замещающего неактивных должностей нет', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([]);
    const positionsWithInactive = [
      POSITIONS[0],
      { id: 2, title: 'Операционный директор', is_active: true },
      { id: 3, title: 'Финансовый директор', is_active: false },
    ];
    renderWithProviders(
      <PositionSubstitutions positionId={1} positions={positionsWithInactive} />,
    );

    const addBtn = await screen.findByRole('button', { name: /добавить/i });
    await userEvent.click(addBtn);
    const selectTrigger = screen.getByRole('combobox', { name: /замещающая должность/i });
    await userEvent.click(selectTrigger);

    expect(await screen.findByText('Операционный директор')).toBeInTheDocument();
    expect(screen.queryByText('Финансовый директор')).not.toBeInTheDocument();

    // Закрыть слои штатным путём (выбор значения, затем «Отмена»): иначе
    // Radix оставляет на <body> `pointer-events: none` от модального
    // Select'а, и следующий тест в файле не может кликнуть ничего вовсе.
    await userEvent.click(screen.getByText('Операционный директор'));
    await userEvent.click(screen.getByRole('button', { name: /отмена/i }));
  });

  it('закрытие бессрочной строки отправляет valid_to и перезапрашивает список', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([ROW]);
    vi.mocked(hrApi.updateSubstitution).mockResolvedValue({ ...ROW, valid_to: todayIso() });

    renderWithProviders(<PositionSubstitutions positionId={1} positions={POSITIONS} />);

    const closeBtn = await screen.findByRole('button', { name: /закрыть замещение/i });
    await userEvent.click(closeBtn);

    const confirmBtn = await screen.findByRole('button', { name: 'Закрыть' });
    await userEvent.click(confirmBtn);

    await waitFor(() => {
      expect(hrApi.updateSubstitution).toHaveBeenCalledWith(ROW.id, { valid_to: todayIso() });
    });
    // Перезапрос списка — тот же ключ запроса, которым закладка загружается.
    await waitFor(() => {
      expect(hrApi.fetchSubstitutions).toHaveBeenCalledTimes(2);
    });
  });

  it('ошибку пересечения от сервера показывает человеку', async () => {
    vi.mocked(hrApi.fetchSubstitutions).mockResolvedValue([]);
    const testError = {
      response: { status: 409, data: { detail: 'Закройте прежнее замещение датой окончания перед добавлением нового' } },
    };
    vi.mocked(hrApi.createSubstitution).mockRejectedValue(testError);

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

    // Человек видит ИМЕННО текст сервера, а не общую отписку — через
    // настоящий `reportApiError` (он не подменён), а не через мок.
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining('Закройте прежнее замещение'),
        undefined,
      );
    });
  });
});
