import { afterEach, describe, expect, it, vi } from 'vitest';

import { copyText } from '@/lib/clipboard';

/**
 * Смысл хелпера — работать там, где `navigator.clipboard` недоступен: стенд,
 * открытый по `http://192.168.x.x:3000`, не является защищённым контекстом, и
 * до этого кнопки копирования там молча не делали ничего.
 */

const setSecureContext = (value: boolean) => {
  Object.defineProperty(window, 'isSecureContext', { value, configurable: true });
};

const setClipboard = (value: unknown) => {
  Object.defineProperty(navigator, 'clipboard', { value, configurable: true });
};

afterEach(() => {
  vi.restoreAllMocks();
  setClipboard(undefined);
  setSecureContext(false);
});

describe('copyText', () => {
  it('в защищённом контексте пишет через Clipboard API', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    setSecureContext(true);

    await expect(copyText('secret')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('secret');
  });

  it('без защищённого контекста не трогает Clipboard API, а копирует запасным путём', async () => {
    const writeText = vi.fn();
    setClipboard({ writeText });
    setSecureContext(false);
    const exec = vi.fn().mockReturnValue(true);
    // @ts-expect-error execCommand в jsdom не реализован
    document.execCommand = exec;

    await expect(copyText('http-only')).resolves.toBe(true);
    expect(writeText).not.toHaveBeenCalled();
    expect(exec).toHaveBeenCalledWith('copy');
  });

  it('падение Clipboard API не заканчивает попытку — включается запасной путь', async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error('denied')) });
    setSecureContext(true);
    const exec = vi.fn().mockReturnValue(true);
    // @ts-expect-error execCommand в jsdom не реализован
    document.execCommand = exec;

    await expect(copyText('retry')).resolves.toBe(true);
    expect(exec).toHaveBeenCalled();
  });

  it('возвращает false, а не бросает, когда не сработало ничего', async () => {
    setClipboard(undefined);
    setSecureContext(false);
    // @ts-expect-error execCommand в jsdom не реализован
    document.execCommand = vi.fn().mockReturnValue(false);

    await expect(copyText('nope')).resolves.toBe(false);
  });

  it('после себя не оставляет мусор в DOM', async () => {
    setClipboard(undefined);
    setSecureContext(false);
    // @ts-expect-error execCommand в jsdom не реализован
    document.execCommand = vi.fn().mockReturnValue(true);

    await copyText('tidy');
    expect(document.querySelectorAll('textarea')).toHaveLength(0);
  });

  it('пустую строку копировать нечего', async () => {
    await expect(copyText('')).resolves.toBe(false);
  });
});
