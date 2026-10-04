/**
 * Диалог несохранённых изменений (ТЗ §05): клик по внутренней ссылке при
 * `dirty` не уводит со страницы, а спрашивает «Сохранить черновик / Уйти
 * без сохранения / Отмена»; закрытие вкладки — диалог браузера.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, onTestFinished, vi } from 'vitest';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }));

function Form({ dirty, onSaveDraft }: { dirty: boolean; onSaveDraft: () => unknown }) {
  const guard = useUnsavedChangesGuard({
    dirty,
    onSaveDraft: onSaveDraft as () => Promise<unknown>,
  });
  return (
    <div>
      <Link to="/elsewhere">Уйти</Link>
      <a href="/elsewhere" target="_blank" rel="noreferrer">В новой вкладке</a>
      <a href="https://example.com/x">Наружу</a>
      {guard}
    </div>
  );
}

function WhereAmI() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function setup(dirty: boolean, onSaveDraft: () => unknown = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/bpp/form']}>
      <Routes>
        <Route path="/bpp/form" element={<Form dirty={dirty} onSaveDraft={onSaveDraft} />} />
        <Route path="/elsewhere" element={<div>Другая страница</div>} />
      </Routes>
      <WhereAmI />
    </MemoryRouter>,
  );
}

describe('useUnsavedChangesGuard', () => {
  it('без изменений ссылка уводит сразу', () => {
    setup(false);
    fireEvent.click(screen.getByText('Уйти'));
    expect(screen.getByTestId('where')).toHaveTextContent('/elsewhere');
    expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument();
  });

  it('с изменениями клик по ссылке открывает диалог и не уводит', () => {
    setup(true);
    fireEvent.click(screen.getByText('Уйти'));
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
    expect(screen.getByTestId('where')).toHaveTextContent('/bpp/form');
  });

  it('«Отмена» оставляет на странице', async () => {
    setup(true);
    fireEvent.click(screen.getByText('Уйти'));
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    await waitFor(() =>
      expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument());
    expect(screen.getByTestId('where')).toHaveTextContent('/bpp/form');
  });

  it('«Уйти без сохранения» уводит, черновик не сохраняется', () => {
    const save = vi.fn();
    setup(true, save);
    fireEvent.click(screen.getByText('Уйти'));
    fireEvent.click(screen.getByRole('button', { name: 'Уйти без сохранения' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/elsewhere');
    expect(save).not.toHaveBeenCalled();
  });

  it('«Сохранить черновик» сохраняет и уводит', async () => {
    const save = vi.fn(() => Promise.resolve());
    setup(true, save);
    fireEvent.click(screen.getByText('Уйти'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/elsewhere'));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('черновик не сохранился — остаёмся, причина в тосте', async () => {
    const save = vi.fn(() => Promise.reject(new Error('сеть')));
    setup(true, save);
    fireEvent.click(screen.getByText('Уйти'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(
      'Не удалось сохранить черновик', undefined,
    ));
    expect(screen.getByTestId('where')).toHaveTextContent('/bpp/form');
  });

  it('новая вкладка и внешний адрес не перехватываются', () => {
    setup(true);
    // jsdom не умеет уходить на другой документ и ругается в консоль; гасим
    // действие по умолчанию ПОСЛЕ хука (всплытие идёт позже захвата).
    const silence = (event: Event) => event.preventDefault();
    window.addEventListener('click', silence);
    onTestFinished(() => window.removeEventListener('click', silence));
    const blank = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    screen.getByText('В новой вкладке').dispatchEvent(blank);
    const external = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    screen.getByText('Наружу').dispatchEvent(external);
    const modified = new MouseEvent('click', {
      bubbles: true, cancelable: true, button: 0, ctrlKey: true,
    });
    screen.getByText('Уйти').dispatchEvent(modified);
    expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument();
  });

  it('с изменениями закрытие вкладки просит подтверждения', () => {
    setup(true);
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it('без изменений закрытие вкладки не останавливается', () => {
    setup(false);
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});
