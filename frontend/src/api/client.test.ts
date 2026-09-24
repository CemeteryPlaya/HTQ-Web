/**
 * api/client.test.ts
 * Базовые тесты API-клиента: проверяем конфигурацию и наличие перехватчиков.
 */

import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { describe, it, expect, vi } from 'vitest';

const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m) } }));

import api from './client';

describe('API Client', () => {
  it('должен быть экземпляром axios с перехватчиками', () => {
    expect(api).toBeDefined();
    expect(api.interceptors).toBeDefined();
  });

  it('baseURL должен заканчиваться на /api/', () => {
    expect(api.defaults.baseURL).toMatch(/\/api\/$/);
  });

  it('должен содержать заголовок ngrok-skip-browser-warning', () => {
    expect(api.defaults.headers['ngrok-skip-browser-warning']).toBe('true');
  });

  it('403 company_archived — без обновления токена и повтора, с тостом', async () => {
    const calls: string[] = [];
    const refresh = vi.spyOn(axios, 'post');
    const original = api.defaults.adapter;
    api.defaults.adapter = (async (config: InternalAxiosRequestConfig) => {
      calls.push(config.url ?? '');
      throw new AxiosError('Forbidden', 'ERR_BAD_REQUEST', config, null, {
        status: 403, statusText: 'Forbidden', headers: {}, config,
        data: { detail: 'Компания в архиве — только чтение', code: 'company_archived' },
      });
    }) as AxiosAdapter;
    try {
      await expect(api.post('hr/v1/departments/', {})).rejects.toBeTruthy();
      expect(calls).toHaveLength(1);
      expect(refresh).not.toHaveBeenCalled();
      expect(toastError).toHaveBeenCalledWith('Нельзя изменить: компания в архиве — только чтение');
    } finally {
      api.defaults.adapter = original;
      refresh.mockRestore();
    }
  });
});
