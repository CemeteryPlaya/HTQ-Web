/**
 * Оболочка формы документа (ТЗ §05 «Общие элементы всех форм», §26.2,
 * BR-060; задача 8 плана этапа 2 A):
 * - кнопки вне `allowedActions` не рисуются, пустой список — «только чтение»;
 * - кнопка заблокирована на время запроса, второй клик запрос не шлёт;
 * - «Отклонить» с комментарием короче 10 символов не отправляется, с 10 —
 *   отправляется, а повтор после 5xx идёт тем же `Idempotency-Key`;
 * - вкладки переключаются;
 * - плашка черновика восстанавливает значение формы.
 */
import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestQueryClient } from '@/test/renderWithProviders';
import type { ApprovalProcess } from '@/types/signoff';

import { BppDocumentShell, type BppDocumentAction, type BppDocumentShellProps } from './BppDocumentShell';

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }));

vi.mock('@/components/files/FilesPanel', () => ({
  FilesPanel: ({ ownerType, ownerId, readOnly }: { ownerType: string; ownerId: string; readOnly?: boolean }) => (
    <div>Файлы {ownerType} {ownerId} {readOnly ? 'только чтение' : 'правка'}</div>
  ),
}));
vi.mock('./HistoryTab', () => ({
  HistoryTab: ({ objectType, objectId }: { objectType: string; objectId: string }) => (
    <div>История по умолчанию {objectType} {objectId}</div>
  ),
}));
vi.mock('@/components/signoff/SubjectProcesses', () => ({
  SubjectProcesses: ({ subjectType, subjectId }: { subjectType: string; subjectId: string }) => (
    <div>Процессы {subjectType} {subjectId}</div>
  ),
}));
vi.mock('@/components/signoff/ProcessTimeline', () => ({
  ProcessTimeline: ({ process }: { process: ApprovalProcess }) => <div>Ход процесса №{process.id}</div>,
}));
vi.mock('@/api/signoff', () => ({
  signoffApi: {
    listProcesses: vi.fn(() => Promise.resolve({
      data: [{ id: 3, stages: [] }, { id: 7, stages: [] }, { id: 5, stages: [] }],
    })),
    getEnums: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

const DOC_ID = '3fa85f64-5717-4562-b3fc-2c963f66afa6';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const serverError = () =>
  Object.assign(new Error('Внутренняя ошибка сервера'), { status: 502, isServerError: true });

function renderShell(props: Partial<BppDocumentShellProps<unknown>> = {}) {
  const base: BppDocumentShellProps<unknown> = {
    subjectType: 'bpp.purchase_request',
    // Тип объекта журнала — `_meta.label_lower` модели, а не имя предмета
    // signoff: `bpp.purchaserequest`, без подчёркивания.
    historyType: 'bpp.purchaserequest',
    documentId: DOC_ID,
    number: 'ЗЗ-2026-000045',
    status: { kind: 'request', code: 'in_approval' },
    authorName: 'Иванов А.',
    createdAt: '2026-09-27T20:30:00Z',
    allowedActions: [],
    actions: {},
    children: <div>Тело формы</div>,
  };
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>
        <BppDocumentShell {...({ ...base, ...props } as BppDocumentShellProps<unknown>)} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('BppDocumentShell — шапка и режимы', () => {
  it('номер, бейдж статуса, автор и дата создания по Алматы', () => {
    renderShell();
    expect(screen.getByRole('heading', { name: 'ЗЗ-2026-000045' })).toBeInTheDocument();
    expect(screen.getByText('На согласовании')).toBeInTheDocument();
    expect(screen.getByText('Автор: Иванов А.')).toBeInTheDocument();
    expect(screen.getByText('Создан 28.09.2026 01:30')).toBeInTheDocument();
  });

  it('кнопки вне allowedActions не рисуются', () => {
    const run = vi.fn(() => Promise.resolve());
    renderShell({
      allowedActions: ['approve', 'unknown_without_label'],
      actions: {
        approve: { label: 'Согласовать', run },
        reject: { label: 'Отклонить', run },
        delete: { label: 'Удалить', run },
      },
    });
    expect(screen.getByRole('button', { name: 'Согласовать' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument();
    expect(screen.queryByText('Только просмотр')).not.toBeInTheDocument();
  });

  it('пустой allowedActions — «только чтение», и форме, и файлам', async () => {
    const user = userEvent.setup();
    renderShell({
      allowedActions: [],
      actions: { approve: { label: 'Согласовать', run: vi.fn() } },
      children: ({ readOnly }: { readOnly: boolean }) => <div>{readOnly ? 'форма закрыта' : 'форма открыта'}</div>,
    });
    expect(screen.queryByRole('button', { name: 'Согласовать' })).not.toBeInTheDocument();
    expect(screen.getByText('Только просмотр')).toBeInTheDocument();
    expect(screen.getByText('форма закрыта')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(screen.getByText(`Файлы bpp.purchase_request ${DOC_ID} только чтение`)).toBeInTheDocument();
  });

  it('панель файлов: по умолчанию наследует readOnly, filesReadOnly={false} открывает её при закрытой форме', async () => {
    const user = userEvent.setup();
    const { unmount } = renderShell({ allowedActions: [], readOnly: true });
    await user.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(screen.getByText(`Файлы bpp.purchase_request ${DOC_ID} только чтение`)).toBeInTheDocument();
    unmount();

    renderShell({
      allowedActions: [],
      readOnly: true,
      filesReadOnly: false,
      children: ({ readOnly }: { readOnly: boolean }) => <div>{readOnly ? 'форма закрыта' : 'форма открыта'}</div>,
    });
    expect(screen.getByText('форма закрыта')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(screen.getByText(`Файлы bpp.purchase_request ${DOC_ID} правка`)).toBeInTheDocument();
  });

  it('у нового документа вкладок нет', () => {
    renderShell({ documentId: null, number: null, status: null });
    expect(screen.getByRole('heading', { name: 'Новый документ' })).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });
});

describe('BppDocumentShell — действия', () => {
  it('кнопка заблокирована на время запроса, второй клик запрос не шлёт', async () => {
    const call = deferred<void>();
    const run = vi.fn(() => call.promise);
    const other = vi.fn(() => Promise.resolve());
    renderShell({
      allowedActions: ['submit', 'cancel'],
      actions: {
        submit: { label: 'Отправить', run },
        cancel: { label: 'Отменить', run: other },
      },
    });

    const button = screen.getByRole('button', { name: 'Отправить' });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    // Пока идёт одно действие, второе тоже закрыто.
    expect(screen.getByRole('button', { name: 'Отменить' })).toBeDisabled();
    fireEvent.click(button);
    expect(run).toHaveBeenCalledTimes(1);

    await act(async () => { call.resolve(); await call.promise; });
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(run).toHaveBeenCalledTimes(1);
    expect(other).not.toHaveBeenCalled();
  });

  it('кнопка исчезла (сменился статус), пока действие «шло», — занятость сброшена, соседнее действие доступно', async () => {
    const call = deferred<void>();
    const pay = { label: 'Оплачено', run: vi.fn(() => call.promise) };
    const request = { label: 'Запросить закрывающие', run: vi.fn(() => Promise.resolve()) };
    const props = {
      subjectType: 'bpp.invoice', historyType: 'bpp.invoice', documentId: DOC_ID,
      number: 'СЧ-2026-000001', status: { kind: 'invoice' as const, code: 'to_pay' },
      authorName: 'Иванов А.', createdAt: '2026-09-27T20:30:00Z',
      actions: { pay, request }, children: <div>Тело формы</div>,
    };
    const view = (allowed: string[]) => (
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter>
          <BppDocumentShell {...({ ...props, allowedActions: allowed } as unknown as BppDocumentShellProps<unknown>)} />
        </MemoryRouter>
      </QueryClientProvider>
    );
    const { rerender } = render(view(['pay', 'request']));
    fireEvent.click(screen.getByRole('button', { name: 'Оплачено' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Запросить закрывающие' })).toBeDisabled());

    // Ответ пришёл: статус сменился, кнопки «Оплачено» больше нет — размонтирована с pending=true.
    rerender(view(['request']));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Запросить закрывающие' })).toBeEnabled());
    await act(async () => { call.resolve(); await call.promise; });
  });

  it('«Отклонить» с 9 символами не отправляется, с 10 — отправляется; повтор после 5xx — тем же ключом', async () => {
    const user = userEvent.setup();
    const run = vi.fn<BppDocumentAction['run']>()
      .mockRejectedValueOnce(serverError())
      .mockResolvedValueOnce(undefined);
    renderShell({
      allowedActions: ['reject'],
      actions: {
        reject: {
          label: 'Отклонить',
          variant: 'destructive',
          confirm: { title: 'Отклонить заявку', commentMin: 10 },
          run,
        },
      },
    });

    await user.click(screen.getByRole('button', { name: 'Отклонить' }));
    const dialog = await screen.findByRole('dialog');
    const field = screen.getByLabelText('Комментарий');
    const submit = () => screen.getAllByRole('button', { name: 'Отклонить' })
      .find((b) => dialog.contains(b))!;

    await user.type(field, '123456789');
    expect(screen.getByText('Минимум 10 символов, сейчас 9')).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    await user.click(submit());
    expect(run).not.toHaveBeenCalled();

    await user.type(field, '0');
    expect(submit()).not.toBeDisabled();
    await user.click(submit());
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][1]).toBe('1234567890');
    // 5xx: причина — тостом, диалог открыт для повтора.
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Внутренняя ошибка сервера', undefined));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await waitFor(() => expect(submit()).not.toBeDisabled());
    await user.click(submit());
    await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
    expect(run.mock.calls[1][0]).toBe(run.mock.calls[0][0]);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});

describe('BppDocumentShell — вкладки', () => {
  it('переключаются: согласование → файлы → история', async () => {
    const user = userEvent.setup();
    renderShell({ historyType: undefined, history: <div>Журнал изменений</div> });

    expect(screen.getByText(`Процессы bpp.purchase_request ${DOC_ID}`)).toBeInTheDocument();
    // Ход — последнего круга согласования (наибольший id).
    expect(await screen.findByText('Ход процесса №7')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(screen.getByText(`Файлы bpp.purchase_request ${DOC_ID} только чтение`)).toBeInTheDocument();
    expect(screen.queryByText(/Процессы/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'История изменений' }));
    expect(screen.getByText('Журнал изменений')).toBeInTheDocument();
  });

  it('без слота истории вкладка — HistoryTab по historyType (label_lower модели), не по subjectType; владелец файлов переопределяется', async () => {
    const user = userEvent.setup();
    renderShell({ fileOwnerType: 'bpp.advance_report', withApproval: false });
    expect(screen.queryByRole('tab', { name: 'Согласование' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(screen.getByText(`Файлы bpp.advance_report ${DOC_ID} только чтение`)).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'История изменений' }));
    expect(screen.getByText(`История по умолчанию bpp.purchaserequest ${DOC_ID}`)).toBeInTheDocument();
  });

  it('history={null} — вкладки истории нет', () => {
    renderShell({ historyType: undefined, history: null });
    expect(screen.queryByRole('tab', { name: 'История изменений' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Файлы' })).toBeInTheDocument();
  });
});

describe('BppDocumentShell — черновик', () => {
  const KEY = `bpp:draft:bpp.purchase_request:${DOC_ID}`;

  beforeEach(() => { window.localStorage.clear(); });
  afterEach(() => { window.localStorage.clear(); });

  function DraftForm() {
    const [title, setTitle] = useState('с сервера');
    return (
      <BppDocumentShell
        subjectType="bpp.purchase_request"
        historyType="bpp.purchaserequest"
        documentId={DOC_ID}
        number="ЗЗ-2026-000045"
        allowedActions={['save']}
        actions={{ save: { label: 'Сохранить', run: () => Promise.resolve() } }}
        draft={{
          value: { title },
          dirty: title !== 'с сервера',
          onRestore: (value: { title: string }) => setTitle(value.title),
          onSaveDraft: vi.fn(),
        }}
      >
        <input aria-label="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
      </BppDocumentShell>
    );
  }

  const renderDraftForm = () => render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter><DraftForm /></MemoryRouter>
    </QueryClientProvider>,
  );

  it('плашка «Найден несохранённый черновик» восстанавливает значение', async () => {
    window.localStorage.setItem(KEY, JSON.stringify({
      savedAt: '2026-09-27T20:30:00Z', value: { title: 'из черновика' },
    }));
    const user = userEvent.setup();
    renderDraftForm();

    expect(screen.getByText('Найден несохранённый черновик от 28.09.2026 01:30')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Восстановить' }));
    expect(screen.getByLabelText('Название')).toHaveValue('из черновика');
    expect(screen.queryByText(/Найден несохранённый черновик/)).not.toBeInTheDocument();
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
  });

  it('«Удалить» стирает черновик', async () => {
    window.localStorage.setItem(KEY, JSON.stringify({
      savedAt: '2026-09-27T20:30:00Z', value: { title: 'из черновика' },
    }));
    const user = userEvent.setup();
    renderDraftForm();
    await user.click(screen.getByRole('button', { name: 'Удалить' }));
    expect(window.localStorage.getItem(KEY)).toBeNull();
    expect(screen.getByLabelText('Название')).toHaveValue('с сервера');
  });

  it('без черновика плашки нет', () => {
    renderDraftForm();
    expect(screen.queryByText(/Найден несохранённый черновик/)).not.toBeInTheDocument();
  });
});
