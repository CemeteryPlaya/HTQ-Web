/**
 * Клиент портала поставщика (T3.5; план этапа 3 §1): анонимные запросы
 * мимо JWT-интерсептора axios — `fetch` с cookie устройства
 * (`credentials: 'include'`), JSON-тело, без `Authorization`, даже если в
 * браузере лежит токен сотрудника; отказ — `PortalError` с кодом конверта
 * и `Retry-After`; файлы — multipart с полем `file`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PortalError, portalApi, portalBase } from './client';
import { fakeResponse } from './testData';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  // Токен сотрудника в браузере не должен уйти поставщику на сервер.
  window.localStorage.setItem('access_token', 'jwt-of-employee');
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.removeItem('access_token');
});

describe('portalApi', () => {
  it('GET карточки — по адресу с закодированным токеном, cookie включены, без Authorization', async () => {
    fetchMock.mockResolvedValue(fakeResponse(200, { company_name: 'HTQ', tender_number: 'ТН-1' }));
    const card = await portalApi.card('Ab/c+1');

    expect(card).toEqual({ company_name: 'HTQ', tender_number: 'ТН-1' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tender/v1/supplier/Ab%2Fc%2B1');
    expect(portalBase('Ab/c+1')).toBe('/api/tender/v1/supplier/Ab%2Fc%2B1');
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('include');
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBeNull();
    expect(headers.get('Accept')).toBe('application/json');
  });

  it('PUT предложения — JSON-тело и Content-Type application/json', async () => {
    fetchMock.mockResolvedValue(fakeResponse(200, { version: 4 }));
    await portalApi.saveOffer('tok', { version: 3 } as never);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tender/v1/supplier/tok/offer');
    expect(init.method).toBe('PUT');
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ version: 3 });
  });

  it('действия — свои пути', async () => {
    fetchMock.mockResolvedValue(fakeResponse(200, {}));
    await portalApi.bind('tok');
    await portalApi.submit('tok', { version: 2, pd_consent: true });
    await portalApi.withdraw('tok', { version: 3 });
    await portalApi.decline('tok', { reason: 'Нет на складе' });
    expect(fetchMock.mock.calls.map(([url, init]) => `${init.method} ${url}`)).toEqual([
      'POST /api/tender/v1/supplier/tok/bind',
      'POST /api/tender/v1/supplier/tok/offer/submit',
      'POST /api/tender/v1/supplier/tok/offer/withdraw',
      'POST /api/tender/v1/supplier/tok/decline',
    ]);
  });

  it('загрузка файла — multipart, поле file, Content-Type ставит браузер', async () => {
    fetchMock.mockResolvedValue(fakeResponse(201, { id: 'd1', name: 'kp.pdf', size: 10 }));
    const file = new File(['%PDF'], 'kp.pdf', { type: 'application/pdf' });
    await portalApi.uploadFile('tok', file);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tender/v1/supplier/tok/offer/files');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get('file')).toBe(file);
    expect(new Headers(init.headers).get('Content-Type')).toBeNull();
  });

  it('DELETE файла и ответ 204 без тела', async () => {
    fetchMock.mockResolvedValue(fakeResponse(204, null));
    await expect(portalApi.removeFile('tok', 'd1')).resolves.toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tender/v1/supplier/tok/offer/files/d1');
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });

  it('ссылка на файл ТЗ — путь портала (302 на скачивание отдаёт сервер)', () => {
    expect(portalApi.fileHref('tok', 'doc-1')).toBe('/api/tender/v1/supplier/tok/files/doc-1');
  });
});

describe('PortalError', () => {
  it('конверт {detail, code, fields, details} и Retry-After', async () => {
    fetchMock.mockResolvedValue(fakeResponse(429, { detail: 'Слишком много', code: 'E-RATE-01' }, { 'Retry-After': '17' }));
    const error = await portalApi.tender('tok').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PortalError);
    expect(error).toMatchObject({ status: 429, code: 'E-RATE-01', detail: 'Слишком много', retryAfter: 17 });
  });

  it('Retry-After без заголовка — из details.retry_after конверта', async () => {
    fetchMock.mockResolvedValue(fakeResponse(429, { detail: 'Лимит', code: 'E-RATE-01', details: { retry_after: 9 } }));
    const error = await portalApi.offer('tok').catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 429, retryAfter: 9 });
  });

  it('403 устройства несёт details.rebind', async () => {
    fetchMock.mockResolvedValue(fakeResponse(403, {
      detail: 'Ссылка открыта на другом устройстве', code: 'E-TND-06', fields: [], details: { rebind: 'otp' },
    }));
    const error = await portalApi.offer('tok').catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 403, code: 'E-TND-06', details: { rebind: 'otp' } });
  });

  it('сеть недоступна — PortalError со статусом 0', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const error = await portalApi.card('tok').catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 0, code: null });
  });

  it('ответ не JSON (HTML шлюза) — без detail', async () => {
    fetchMock.mockResolvedValue(fakeResponse(502, '<html>bad gateway</html>'));
    const error = await portalApi.card('tok').catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 502, code: null, detail: null });
  });

  it('429 от nginx: HTML без Retry-After — retryAfter null, без падения', async () => {
    fetchMock.mockResolvedValue(fakeResponse(429, '<html>429 Too Many Requests</html>'));
    const error = await portalApi.card('tok').catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 429, code: null, retryAfter: null });
  });
});
