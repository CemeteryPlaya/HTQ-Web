/**
 * Экспорт реестра (ТЗ §19, D-32): ответ ручки реестра с `format=xlsx` —
 * либо файл, либо JSON постановки в очередь `{id, status: "queued"}`;
 * любой другой JSON — ошибка «реестр не поддерживает выгрузку», а тело
 * ошибки 422 (Blob) разбирается обратно, чтобы тост показал текст сервера.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { reportApiError } from '@/lib/apiError';

import {
  EXPORT_FORMAT_PARAM, ExportNotSupportedError, exportRegistry, filenameFromDisposition,
} from './registryExport';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const toastError = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: toastError, info: vi.fn(), success: vi.fn() } }));

const jsonBlob = (body: unknown) =>
  new Blob([JSON.stringify(body)], { type: 'application/json' });
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;
let clicks: string[];

beforeEach(() => {
  get.mockReset();
  toastError.mockReset();
  clicks = [];
  createObjectURL = vi.fn(() => 'blob:export-1');
  revokeObjectURL = vi.fn();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(
    this: HTMLAnchorElement,
  ) {
    clicks.push(this.download);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('filenameFromDisposition', () => {
  it('filename* в UTF-8 — кириллица раскодируется', () => {
    expect(filenameFromDisposition(
      "attachment; filename=\"export.xlsx\"; filename*=utf-8''%D0%A0%D0%B5%D0%B5%D1%81%D1%82%D1%80.xlsx",
      'fallback.xlsx',
    )).toBe('Реестр.xlsx');
  });

  it('только filename, пустой заголовок — простое имя и запасное', () => {
    expect(filenameFromDisposition('attachment; filename="a.xlsx"', 'x.xlsx')).toBe('a.xlsx');
    expect(filenameFromDisposition(undefined, 'x.xlsx')).toBe('x.xlsx');
  });
});

describe('exportRegistry', () => {
  it('файл — скачивание с именем из заголовка; объектный URL отзывается после клика, не сразу', async () => {
    vi.useFakeTimers();
    get.mockResolvedValue({
      data: new Blob(['xlsx'], { type: XLSX }),
      headers: {
        'content-disposition': "attachment; filename*=utf-8''%D0%97%D0%B0%D1%8F%D0%B2%D0%BA%D0%B8.xlsx",
      },
    });

    const result = await exportRegistry('bpp/v1/requests', { status: 'draft' }, 'requests');

    expect(result).toEqual({ kind: 'file', filename: 'Заявки.xlsx' });
    expect(get).toHaveBeenCalledWith('bpp/v1/requests', {
      params: { status: 'draft', [EXPORT_FORMAT_PARAM]: 'xlsx' },
      responseType: 'blob',
    });
    expect(clicks).toEqual(['Заявки.xlsx']);
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:export-1');
  });

  it('без Content-Disposition — имя по запасному', async () => {
    get.mockResolvedValue({ data: new Blob(['xlsx'], { type: XLSX }), headers: {} });
    const result = await exportRegistry('bpp/v1/requests', {}, 'requests');
    expect(result).toEqual({ kind: 'file', filename: 'requests.xlsx' });
  });

  it('JSON постановки в очередь — queued с id и текстом', async () => {
    get.mockResolvedValue({
      data: jsonBlob({ id: 'job-1', status: 'queued', detail: 'Файл соберётся в фоне' }),
      headers: {},
    });
    const result = await exportRegistry('bpp/v1/requests', {}, 'requests');
    expect(result).toEqual({ kind: 'queued', id: 'job-1', detail: 'Файл соберётся в фоне' });
    expect(clicks).toEqual([]);
  });

  it('другой JSON (ручка не знает format=xlsx) — ошибка, а не «очередь»', async () => {
    get.mockResolvedValue({
      data: jsonBlob({ items: [], total: 0, page: 1, page_size: 50 }),
      headers: {},
    });
    await expect(exportRegistry('bpp/v1/requests', {}, 'requests'))
      .rejects.toBeInstanceOf(ExportNotSupportedError);
    expect(clicks).toEqual([]);
  });

  it('queued без id — тоже ошибка', async () => {
    get.mockResolvedValue({ data: jsonBlob({ status: 'queued' }), headers: {} });
    await expect(exportRegistry('bpp/v1/requests', {}, 'requests'))
      .rejects.toBeInstanceOf(ExportNotSupportedError);
  });

  it('422 E-EXP-01 — тело-Blob разбирается, тост показывает текст сервера', async () => {
    const detail = 'Выборка больше 50 000 строк. Сузьте фильтры и повторите экспорт.';
    get.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: jsonBlob({ detail, code: 'E-EXP-01' }) },
    });

    let caught: unknown;
    try {
      await exportRegistry('bpp/v1/requests', {}, 'requests');
    } catch (error) {
      caught = error;
    }
    expect((caught as { response: { data: unknown } }).response.data)
      .toEqual({ detail, code: 'E-EXP-01' });

    reportApiError(caught, 'Не удалось выгрузить реестр');
    expect(toastError).toHaveBeenCalledWith(detail, undefined);
  });
});
