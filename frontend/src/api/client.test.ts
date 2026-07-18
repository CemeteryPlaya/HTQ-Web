/**
 * api/client.test.ts
 * Базовые тесты API-клиента: проверяем конфигурацию и наличие перехватчиков.
 */

import { describe, it, expect } from 'vitest';
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
});
