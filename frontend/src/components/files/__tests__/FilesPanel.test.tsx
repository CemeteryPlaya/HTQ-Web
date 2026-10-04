/**
 * «Документы» — общая панель файловой подсистемы ТЗ §21.
 *
 * Правил панель у себя не держит — их решает сервер флагами папки
 * (`can_modify`, `can_add`, `delete_is_physical`), — поэтому тест проверяет,
 * что панель им следует, что новая версия уходит поверх той действующей,
 * которую видел пользователь (`base_file_id`), и что отказ 409 E-CON-01
 * показывается текстом сервера, а папка перечитывается. Скачивание — только
 * через ссылку, выданную на клик (сервер журналирует его, ТЗ §25.2).
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FilesPanel } from '@/components/files/FilesPanel';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { FileFolder, FileTypeInfo, FileVersion } from '@/types/files';

const files = vi.hoisted(() => ({
  list: vi.fn(),
  upload: vi.fn(),
  uploadVersion: vi.fn(),
  remove: vi.fn(),
  link: vi.fn(),
}));
// Каждый новый ключ повтора — свой: иначе не отличить повтор от нового действия.
const keys = vi.hoisted(() => ({ issued: 0 }));
vi.mock('@/api/files', () => ({
  filesApi: files,
  newIdempotencyKey: () => `key-${++keys.issued}`,
}));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

const OWNER = 'approvals.request';
const ID = 42;
const DOC = '0b6f2f3e-1111-4222-8333-444455556666';
const FORMATS = ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png'];

const version = (over: Partial<FileVersion>): FileVersion => ({
  id: 1,
  document_id: DOC,
  file_type: 'request.kp',
  version_no: 1,
  is_replaced: false,
  replaced_by_id: null,
  name: 'КП.pdf',
  mime: 'application/pdf',
  size: 2048,
  sha256: 'a'.repeat(64),
  storage_key: `file_object/public/request/${ID}/x/original.pdf`,
  uploaded_by_id: 7,
  uploaded_by_name: 'Иван Петров',
  uploaded_by_department_id: 3,
  uploaded_by_department_name: 'Снабжение',
  uploaded_at: '2026-09-24T10:15:03.123456+00:00',
  deleted_at: null,
  ...over,
});

const type = (code: string, name: string, over: Partial<FileTypeInfo> = {}): FileTypeInfo => ({
  code, name, formats: FORMATS, max_mb: 20, cardinality: 'multi', required: false,
  quota_group: 'request', can_add: true, reason: null, ...over,
});

function folder(over: Partial<FileFolder> = {}): FileFolder {
  const v2 = version({ id: 2, version_no: 2, name: 'КП v2.pdf', uploaded_at: '2026-09-24T10:15:09.5+00:00' });
  const v1 = version({ id: 1, version_no: 1, is_replaced: true, replaced_by_id: 2 });
  const spec = version({
    id: 3, document_id: 'spec-doc', file_type: 'request.spec', name: 'Спецификация.xlsx',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  return {
    owner_type: OWNER,
    owner_id: String(ID),
    storage_prefix: `file_object/public/request/${ID}/`,
    can_modify: true,
    modify_reason: null,
    delete_is_physical: true,
    types: [type('request.kp', 'КП'), type('request.spec', 'Спецификация')],
    quotas: [{ group: 'request', max: 20, used: 2 }],
    documents: [
      { document_id: DOC, file_type: 'request.kp', file_type_name: 'КП', deleted_at: null,
        current: v2, versions: [v2, v1] },
      { document_id: 'spec-doc', file_type: 'request.spec', file_type_name: 'Спецификация',
        deleted_at: null, current: spec, versions: [spec] },
    ],
    ...over,
  };
}

const render = (props: { readOnly?: boolean } = {}) =>
  renderWithProviders(<FilesPanel ownerType={OWNER} ownerId={ID} {...props} />);

beforeEach(() => {
  keys.issued = 0;
  Object.values(files).forEach((fn) => fn.mockReset());
  toast.success.mockReset();
  toast.error.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FilesPanel', () => {
  it('показывает документы, счётчик квоты и время загрузки по Алматы с секундами', async () => {
    files.list.mockResolvedValue(folder());
    render();

    expect(await screen.findByText('КП v2.pdf')).toBeInTheDocument();
    expect(screen.getByText('Спецификация.xlsx')).toBeInTheDocument();
    expect(screen.getByText('2 из 20')).toBeInTheDocument();
    expect(screen.getAllByText('Действующий')).toHaveLength(2);
    // 10:15:09 UTC — 15:15:09 в Алматы (UTC+5), в каком бы поясе ни был браузер.
    const time = screen.getByText('24.09.2026 15:15:09');
    expect(time).toHaveAttribute('title', '24.09.2026 15:15:09.500 (Asia/Almaty)');
    expect(files.list).toHaveBeenCalledWith(OWNER, ID);
  });

  it('PDF открывается во вкладке по ссылке, выданной на этот клик', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder());
    files.link.mockResolvedValue({ url: '/api/media/v1/files/m2/?sig=s&exp=1', expires_at: '' });
    const tab = { opener: {}, location: { href: '' }, close: vi.fn() };
    const open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    render();

    await user.click(await screen.findByRole('button', { name: 'КП v2.pdf' }));

    expect(open).toHaveBeenCalledWith('', '_blank');
    await waitFor(() => expect(tab.location.href).toBe('/api/media/v1/files/m2/?sig=s&exp=1'));
    expect(files.link).toHaveBeenCalledWith(OWNER, ID, DOC, 2);
    expect(tab.opener).toBeNull();
  });

  it('таблица скачивается, не уводя со страницы; отказ — текстом сервера', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder());
    files.link.mockResolvedValueOnce({ url: '/api/media/v1/files/m3/?sig=s&exp=1', expires_at: '' });
    const open = vi.spyOn(window, 'open');
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render();

    const xlsx = await screen.findByRole('button', { name: 'Спецификация.xlsx' });
    await user.click(xlsx);

    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(open).not.toHaveBeenCalled();
    expect(files.link).toHaveBeenCalledWith(OWNER, ID, 'spec-doc', 3);

    const message = 'Документ не найден. Возможно, он удалён или у вас нет к нему доступа.';
    files.link.mockRejectedValueOnce({
      response: { status: 404, data: { detail: message, code: 'E-FIL-05', fields: [], details: {} } },
    });
    await user.click(xlsx);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message, undefined));
  });

  it('в истории версий прежняя помечена «Заменён», номера — как выдал сервер', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder());
    render();

    await user.click(await screen.findByRole('button', { name: /Версии \(2\)/ }));

    expect(screen.getByText('Заменён')).toBeInTheDocument();
    expect(screen.getByText('КП.pdf')).toBeInTheDocument();
    expect(screen.getAllByText('v1').length).toBeGreaterThan(0);
  });

  it('новая версия уходит поверх действующей — base_file_id', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder());
    files.uploadVersion.mockResolvedValue(version({ id: 9, version_no: 3 }));
    const { container } = render();
    await screen.findByText('КП v2.pdf');

    const item = screen.getByText('КП v2.pdf').closest('li') as HTMLElement;
    const input = item.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['%PDF'], 'КП v3.pdf', { type: 'application/pdf' });
    await user.upload(input, file);

    await waitFor(() => expect(files.uploadVersion)
      .toHaveBeenCalledWith(OWNER, ID, DOC, file, 2, 'key-1'));
    expect(container).toBeTruthy();
  });

  it('на 409 E-CON-01 показывает текст сервера и перечитывает папку', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder());
    const message = 'Документ изменён пользователем Иванов А. в 14:32. Ваши изменения не сохранены.';
    files.uploadVersion.mockRejectedValue({
      response: { status: 409, data: { detail: message, code: 'E-CON-01', fields: [], details: {} } },
    });
    render();
    await screen.findByText('КП v2.pdf');
    const calls = files.list.mock.calls.length;

    const item = screen.getByText('КП v2.pdf').closest('li') as HTMLElement;
    await user.upload(item.querySelector('input[type="file"]') as HTMLInputElement,
      new File(['%PDF'], 'late.pdf', { type: 'application/pdf' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message, undefined));
    await waitFor(() => expect(files.list.mock.calls.length).toBeGreaterThan(calls));
  });

  it('без права менять — ни загрузки, ни новой версии, ни удаления; причина видна', async () => {
    files.list.mockResolvedValue(folder({
      can_modify: false,
      modify_reason: 'Файлы заявки меняются только в статусах «Черновик» и «На доработке».',
    }));
    render();

    await screen.findByText('КП v2.pdf');
    expect(screen.queryByRole('button', { name: /Приложить файл/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Новая версия/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
    expect(screen.getByText(/меняются только в статусах/)).toBeInTheDocument();
  });

  it('правило документа сильнее папки: после отправки — только новая версия', async () => {
    // Заявка отправлена: добавлять и удалять нельзя (`can_modify: false`), а
    // новую версию её документа владелец разрешает (`can_version`, ТЗ §21).
    const base = folder({ can_modify: false });
    files.list.mockResolvedValue({
      ...base,
      documents: base.documents.map((doc) => ({ ...doc, can_version: true, can_delete: false })),
    });
    render();

    await screen.findByText('КП v2.pdf');
    expect(screen.getAllByRole('button', { name: /Новая версия/ })).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Приложить файл/ })).not.toBeInTheDocument();
  });

  it('и в обратную сторону: папка открыта, а тип документа закрыт', async () => {
    const base = folder();
    files.list.mockResolvedValue({
      ...base,
      documents: base.documents.map((doc) => (doc.document_id === DOC
        ? { ...doc, can_version: false, can_delete: false }
        : { ...doc, can_version: true, can_delete: true })),
    });
    render();

    const item = (await screen.findByText('КП v2.pdf')).closest('li') as HTMLElement;
    expect(within(item).queryByRole('button', { name: /Новая версия/ })).not.toBeInTheDocument();
    expect(within(item).queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
    const spec = screen.getByText('Спецификация.xlsx').closest('li') as HTMLElement;
    expect(within(spec).getByRole('button', { name: /Новая версия/ })).toBeInTheDocument();
  });

  it('readOnly перекрывает can_modify (карточка согласования)', async () => {
    files.list.mockResolvedValue(folder());
    render({ readOnly: true });

    await screen.findByText('КП v2.pdf');
    expect(screen.queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
  });

  it('удаление — после подтверждения, текст зависит от delete_is_physical', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder({ delete_is_physical: false }));
    files.remove.mockResolvedValue(undefined);
    render();

    await user.click(await screen.findByRole('button', { name: 'Удалить: КП v2.pdf' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/помечен удалённым/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(files.remove).toHaveBeenCalledWith(OWNER, ID, DOC));
  });

  it('на пределе новый документ не приложить, а новую версию — можно', async () => {
    const reason = 'Уже приложено документов: 20 из 20 — это предел.';
    files.list.mockResolvedValue(folder({
      quotas: [{ group: 'request', max: 20, used: 20 }],
      types: [type('request.kp', 'КП', { can_add: false, reason }),
        type('request.spec', 'Спецификация', { can_add: false, reason })],
    }));
    render();

    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Приложить файл/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Новая версия: КП v2.pdf' })).toBeEnabled();
  });

  it('удалённый документ виден в истории, но без действий', async () => {
    const gone = version({ id: 9, document_id: 'gone', file_type: 'request.tz',
      name: 'Старое ТЗ.pdf', deleted_at: '2026-09-24T11:00:00+00:00' });
    const base = folder({ delete_is_physical: false });
    files.list.mockResolvedValue({
      ...base,
      documents: [...base.documents, {
        document_id: 'gone', file_type: 'request.tz', file_type_name: 'ТЗ',
        deleted_at: gone.deleted_at, current: gone, versions: [gone],
      }],
    });
    render();

    const item = (await screen.findByText('Старое ТЗ.pdf')).closest('li') as HTMLElement;
    expect(within(item).getByText('Удалён')).toBeInTheDocument();
    expect(within(item).queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
    expect(within(item).queryByRole('button', { name: /Новая версия/ })).not.toBeInTheDocument();
  });

  it('файл не того формата отсекается до запроса', async () => {
    const user = userEvent.setup({ applyAccept: false });
    files.list.mockResolvedValue(folder());
    render();
    await screen.findByText('КП v2.pdf');

    const item = screen.getByText('КП v2.pdf').closest('li') as HTMLElement;
    await user.upload(item.querySelector('input[type="file"]') as HTMLInputElement,
      new File(['MZ'], 'setup.exe', { type: 'application/x-msdownload' }));

    expect(toast.error).toHaveBeenCalledWith(
      'Файл setup.exe не загружен: допустимы PDF, DOCX, XLSX, JPG, PNG до 20 МБ.');
    expect(files.uploadVersion).not.toHaveBeenCalled();
  });

  it('повтор после обрыва уходит с тем же ключом, после ответа сервера — с новым', async () => {
    const user = userEvent.setup();
    files.list.mockResolvedValue(folder());
    files.uploadVersion
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce(version({ id: 9, version_no: 3 }))
      .mockResolvedValueOnce(version({ id: 10, version_no: 4 }));
    render();
    await screen.findByText('КП v2.pdf');
    const pick = async () => {
      const item = screen.getByText('КП v2.pdf').closest('li') as HTMLElement;
      await user.upload(item.querySelector('input[type="file"]') as HTMLInputElement,
        new File(['%PDF'], 'КП v3.pdf', { type: 'application/pdf', lastModified: 1 }));
    };

    await pick();
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    await pick();
    await waitFor(() => expect(files.uploadVersion).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    await pick();
    await waitFor(() => expect(files.uploadVersion).toHaveBeenCalledTimes(3));

    const keys = files.uploadVersion.mock.calls.map((call) => call[5]);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });
});
