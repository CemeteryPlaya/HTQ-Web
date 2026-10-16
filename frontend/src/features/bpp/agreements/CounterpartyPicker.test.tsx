/**
 * Выбор контрагента: таймер закрытия списка после ухода фокуса не переживает
 * компонент. Без этого он менял состояние уже снятого компонента, и vitest
 * ловил «window is not defined» после снятия среды (плавающее падение CI 16.10).
 */
import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { CounterpartyPicker } from './CounterpartyPicker';

vi.mock('@/api/client', () => ({ default: { get: vi.fn(() => Promise.resolve({ data: { items: [] } })) } }));

afterEach(() => { vi.restoreAllMocks(); });

describe('CounterpartyPicker', () => {
  it('гасит таймер закрытия списка при размонтировании', () => {
    const { unmount } = renderWithProviders(
      <CounterpartyPicker value={null} onChange={vi.fn()} id="cp" />,
    );
    const input = screen.getByRole('textbox');
    fireEvent.focus(input);

    const setSpy = vi.spyOn(globalThis, 'setTimeout');
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout');
    fireEvent.blur(input);
    const blurTimer = setSpy.mock.results.at(-1)?.value;
    expect(blurTimer).toBeDefined();

    unmount();
    expect(clearSpy).toHaveBeenCalledWith(blurTimer);
  });
});
