/**
 * Метки карточки: администратор задач заводит метку прямо в окне, новая метка
 * сразу встаёт на карточку, а фокус возвращается в поле названия (живая
 * проверка S2: кнопка «Создать метку» гасла под фокусом, и фокус терялся).
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Button } from '@/components/ui/button';
import { renderWithProviders } from '@/test/renderWithProviders';

const tasksApi = vi.hoisted(() => ({ fetchLabels: vi.fn(), createLabel: vi.fn() }));
vi.mock('@/api/tasks', () => tasksApi);
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => ({ atLeast: () => true }) }));

import { LabelsPopover } from '../LabelsPopover';

beforeEach(() => {
  vi.clearAllMocks();
  tasksApi.fetchLabels.mockResolvedValue([{ id: 1, name: 'Срочно', color: '#f87168' }]);
  tasksApi.createLabel.mockResolvedValue({ id: 2, name: 'Протокольные поручения', color: '#4bce97' });
});

describe('LabelsPopover', () => {
  it('новая метка встаёт на карточку, фокус остаётся в поле названия', async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <LabelsPopover selected={[1]} onChange={onChange} trigger={<Button>Метки</Button>} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Метки' }));
    const field = await screen.findByPlaceholderText('Название новой метки');
    await userEvent.type(field, 'Протокольные поручения');
    await userEvent.click(screen.getByRole('button', { name: 'Создать метку' }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([1, 2]));
    expect(tasksApi.createLabel).toHaveBeenCalledWith({ name: 'Протокольные поручения', color: '#4bce97' });
    expect(field).toHaveValue('');
    expect(field).toHaveFocus();
  });
});
