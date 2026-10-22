/**
 * Телеметрия не уносит секрет из адреса страницы: токен ссылки портала
 * поставщика (`/supplier/<token>`) уходит в логи как `***`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { maskSecretUrl, reportClientError } from './telemetry';

const TOKEN = 'k3J9-token_value_0123456789abcdef0123456789';

describe('maskSecretUrl', () => {
  it('токен ссылки поставщика — ***, остальное как было', () => {
    expect(maskSecretUrl(`https://htq.group.kz/supplier/${TOKEN}`)).toBe('https://htq.group.kz/supplier/***');
    expect(maskSecretUrl(`http://group.localhost:3000/supplier/${TOKEN}?x=1#a`))
      .toBe('http://group.localhost:3000/supplier/***?x=1#a');
    expect(maskSecretUrl('https://htq.group/tender/tenders/12')).toBe('https://htq.group/tender/tenders/12');
  });
});

describe('reportClientError', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('в тело отчёта адрес уходит без токена', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);
    reportClientError({ message: 'boom', url: `https://htq.group/supplier/${TOKEN}` });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = String(fetchMock.mock.calls[0][1].body);
    expect(body).not.toContain(TOKEN);
    expect(JSON.parse(body).url).toBe('https://htq.group/supplier/***');
  });
});
