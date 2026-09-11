/**
 * Политика показа ошибок — одна на всю платформу, поэтому проверяется здесь,
 * а не на каждой странице.
 *
 * Главное, что закрывает этот тест, — ДВЕ формы ошибки. Интерцептор
 * `api/client.ts` сворачивает всё от 500 и выше в обычный `Error` без
 * `response`, и разбор, смотревший только на `response`, молча терял причину:
 * на отказ mailcow (502) пользователь видел буквальное слово «Error».
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { toast } from 'sonner';

import { errorDetail, errorStatus, explainedDetail, reportApiError } from '@/lib/apiError';

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

/** Обычный отказ axios: статус и конверт `{"detail": …}` на месте. */
const axiosError = (status: number, detail: unknown) => ({
  response: { status, data: { detail } },
});

/** 5xx после интерцептора: `response` уже потерян. */
const collapsed = (status: number, message: string) =>
  Object.assign(new Error(message), { status, isServerError: true });

beforeEach(() => vi.mocked(toast.error).mockClear());

describe('errorStatus / errorDetail', () => {
  it('читают обычный отказ axios', () => {
    const err = axiosError(409, 'Номер договора занят');
    expect(errorStatus(err)).toBe(409);
    expect(errorDetail(err)).toBe('Номер договора занят');
  });

  it('читают свёрнутую 5xx, у которой нет response', () => {
    const err = collapsed(502, 'Mailcow error: mailbox already exists');
    expect(errorStatus(err)).toBe(502);
    expect(errorDetail(err)).toBe('Mailcow error: mailbox already exists');
  });

  it('склеивают список ошибок Pydantic из 422', () => {
    expect(errorDetail(axiosError(422, [{ msg: 'поле обязательно' }, { msg: 'не число' }])))
      .toBe('поле обязательно; не число');
  });

  it('ничего не выдумывают, когда конверта нет', () => {
    expect(errorDetail(new Error('Network Error'))).toBeNull();
    expect(errorStatus(new Error('Network Error'))).toBeUndefined();
  });
});

describe('explainedDetail', () => {
  it('отдаёт текст только для кодов, где он объясняет причину', () => {
    expect(explainedDetail(axiosError(409, 'Объект уже на согласовании')))
      .toBe('Объект уже на согласовании');
    expect(explainedDetail(collapsed(503, 'Модуль отключён'))).toBe('Модуль отключён');
  });

  it('молчит на 500: внутренности пользователю не показывают', () => {
    expect(explainedDetail(collapsed(500, 'IntegrityError at /api/hr/v1/…'))).toBeNull();
  });

  it('отдаёт и 403, и 400 — разбор их не различает, различает показ', () => {
    expect(explainedDetail(axiosError(403, 'Senior HR access required')))
      .toBe('Senior HR access required');
    expect(explainedDetail(axiosError(400, 'Текущий пароль неверен')))
      .toBe('Текущий пароль неверен');
  });
});

describe('reportApiError', () => {
  it('показывает объяснение сервера вместо общей отписки', () => {
    reportApiError(axiosError(409, 'Системный блок нельзя удалить'), 'Не удалось удалить блок');
    expect(toast.error).toHaveBeenCalledWith('Системный блок нельзя удалить', undefined);
  });

  it('на 500 показывает запасную фразу — она называет действие', () => {
    reportApiError(collapsed(500, 'IntegrityError'), 'Не удалось сохранить проект');
    expect(toast.error).toHaveBeenCalledWith('Не удалось сохранить проект', undefined);
  });

  it('прячет машинную строку сторожа прав за переведённой фразой', () => {
    for (const machine of ['Forbidden', 'Missing permission: hr.card.finance.edit',
      'Senior HR access required', 'Admin privileges required', 'Department access denied']) {
      vi.mocked(toast.error).mockClear();
      reportApiError(axiosError(403, machine), 'Не удалось сохранить');
      expect(vi.mocked(toast.error).mock.calls[0][0]).toBe('Недостаточно прав для этого действия');
    }
  });

  it('но человеческую фразу на 403 показывает как есть', () => {
    reportApiError(
      axiosError(403, 'Самостоятельное подключение ящиков отключено — обратитесь к администратору'),
      'Не удалось подключить ящик',
    );
    expect(toast.error).toHaveBeenCalledWith(
      'Самостоятельное подключение ящиков отключено — обратитесь к администратору',
      undefined,
    );
  });

  it('на 400 показывает причину: исправлять пользователю', () => {
    reportApiError(axiosError(400, 'Адрес не из корпоративного домена'), 'Не удалось подключить ящик');
    expect(toast.error).toHaveBeenCalledWith('Адрес не из корпоративного домена', undefined);
  });

  it('пробрасывает настройки тоста: длинные почтовые ошибки читают дольше', () => {
    reportApiError(collapsed(502, 'AUTHENTICATIONFAILED'), 'Не удалось подключить', { duration: 12_000 });
    expect(toast.error).toHaveBeenCalledWith('AUTHENTICATIONFAILED', { duration: 12_000 });
  });
});
