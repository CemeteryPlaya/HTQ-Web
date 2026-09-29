/**
 * Редактор шаблона выписки: недостающие обязательные колонки видны сразу и
 * не пускают «Сохранить»; режим «Дебет/Кредит» требует обе колонки; 1С
 * колонок не требует; «Проверить на образце» — только по сохранённому
 * шаблону без несохранённых правок, результат — строки и ошибки строк.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import type { StatementTemplate } from './api';
import { TemplateEditor } from './TemplateEditor';

const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post, patch } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn(), info: vi.fn() } }));

const SAVED: StatementTemplate = {
  id: 'tpl-1', name: 'Халык CSV', format: 'csv', encoding: 'cp1251', delimiter: ';',
  date_format: 'ДД.ММ.ГГГГ', amount_mode: 'signed', is_active: true, active_accounts: 1, version: 3,
  columns: { date: 'Дата', doc_number: 'Номер', amount: 'Сумма', purpose: 'Назначение' },
};

let user: ReturnType<typeof userEvent.setup>;

beforeEach(() => {
  user = userEvent.setup();
  post.mockReset();
  patch.mockReset();
  toastError.mockReset();
});

function renderEditor(template: StatementTemplate | null, onSaved = vi.fn()) {
  renderWithProviders(
    <TemplateEditor template={template} canEdit onSaved={onSaved} onClose={vi.fn()} />,
  );
  return onSaved;
}

describe('TemplateEditor', () => {
  it('новый шаблон — показывает недостающие обязательные колонки и не сохраняет без них', async () => {
    renderEditor(null);
    expect(screen.getByRole('status')).toHaveTextContent(
      'Не заполнены обязательные колонки: «Дата», «Номер документа», «Сумма», «Назначение платежа»',
    );

    await user.type(screen.getByLabelText('Название'), 'Каспи Excel');
    await user.type(screen.getByLabelText(/^Дата/), 'Дата операции');
    await user.type(screen.getByLabelText(/^Номер документа/), '№ п/п');
    expect(screen.getByRole('status')).toHaveTextContent(
      'Не заполнены обязательные колонки: «Сумма», «Назначение платежа»',
    );
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(post).not.toHaveBeenCalled();
  });

  it('режим «Дебет/Кредит» требует обе колонки вместо «Суммы»', async () => {
    renderEditor(null);
    await user.click(screen.getByRole('combobox', { name: 'Сумма в файле' }));
    await user.click(await screen.findByRole('option', { name: 'Колонки «Дебет» и «Кредит»' }));

    expect(screen.getByRole('status')).toHaveTextContent('«Дебет», «Кредит»');
    expect(screen.queryByLabelText(/^Сумма \*?$/)).toBeNull();
  });

  it('1С — колонки не нужны, предупреждения нет', async () => {
    renderEditor(null);
    await user.click(screen.getByRole('combobox', { name: 'Формат файла' }));
    await user.click(await screen.findByRole('option', { name: /1С/ }));

    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByText(/колонки в шаблоне ей не нужны/)).toBeInTheDocument();
  });

  it('заполненный шаблон сохраняется с версией и только непустыми колонками', async () => {
    patch.mockResolvedValue({ data: { ...SAVED, version: 4 } });
    const onSaved = renderEditor(SAVED);
    await user.type(screen.getByLabelText(/^Получатель/), 'Бенефициар');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, body, config] = patch.mock.calls[0];
    expect(url).toBe('bpp/v1/bank/templates/tpl-1');
    expect(body).toMatchObject({
      version: 3,
      columns: { ...SAVED.columns, recipient_name: 'Бенефициар' },
    });
    expect(config.headers['Idempotency-Key']).toBeTruthy();
  });

  it('«Проверить на образце» — строки и ошибки строк; с правками — недоступно', async () => {
    post.mockResolvedValue({
      data: {
        header_row: 2,
        columns: [{ field: 'date', label: 'Дата', header: 'Дата', index: 0 }],
        rows: [{
          row_no: 3, date: '2026-09-03', doc_number: '117', amount: '1250000.10',
          direction: 'debit', recipient_name: 'ТОО «Альфа»', purpose: 'Оплата',
        }],
        errors: ['Строка 4: не распознана дата „31.02.2026“'],
      },
    });
    renderEditor(SAVED);

    const file = new File(['x'], 'sample.csv', { type: 'text/csv' });
    await user.upload(screen.getByLabelText('Образец выписки'), file);
    await user.click(screen.getByRole('button', { name: 'Проверить на образце' }));

    expect(await screen.findByText('1 250 000,10')).toBeInTheDocument();
    expect(screen.getByText('Строка 4: не распознана дата „31.02.2026“')).toBeInTheDocument();
    expect(post.mock.calls[0][0]).toBe('bpp/v1/bank/templates/tpl-1/preview');

    await user.type(screen.getByLabelText('Название'), ' 2');
    expect(screen.queryByLabelText('Образец выписки')).toBeNull();
    expect(screen.getByText(/Есть несохранённые изменения/)).toBeInTheDocument();
  });
});
