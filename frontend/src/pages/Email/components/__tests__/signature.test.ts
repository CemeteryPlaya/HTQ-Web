/**
 * Подстановка подписи в тело письма.
 *
 * Подпись вставляется В РЕДАКТОР, а не приклеивается на сервере при отправке:
 * человек должен видеть, что уйдёт от его имени. Отсюда и требования к этой
 * логике — она правит текст, который человек уже начал писать, и ошибка здесь
 * либо съедает написанное, либо оставляет две подписи под одним письмом.
 */
import { describe, expect, it } from 'vitest';

import { replaceSignature, withSignature } from '../signature';

const SIG = 'Руслан Амиров\nHi-Tech Group';
const OTHER = 'Иван Иванов\nОтдел продаж';

describe('withSignature', () => {
    it('дописывает подпись через стандартный разделитель', () => {
        expect(withSignature('Добрый день!', SIG))
            .toBe(`Добрый день!\n\n-- \n${SIG}`);
    });

    it('без подписи не трогает текст', () => {
        expect(withSignature('Добрый день!', '')).toBe('Добрый день!');
        expect(withSignature('Добрый день!', null)).toBe('Добрый день!');
        expect(withSignature('Добрый день!', '   \n ')).toBe('Добрый день!');
    });

    it('не дублирует уже вставленную подпись', () => {
        const once = withSignature('Добрый день!', SIG);
        expect(withSignature(once, SIG)).toBe(once);
    });

    it('работает на пустом теле — письмо начинают писать с подписью', () => {
        expect(withSignature('', SIG)).toBe(`\n\n-- \n${SIG}`);
    });
});

describe('replaceSignature', () => {
    it('меняет подпись прежнего отправителя на новую, а не добавляет вторую', () => {
        const body = withSignature('Добрый день!', OTHER);
        const swapped = replaceSignature(body, OTHER, SIG);

        expect(swapped).toBe(`Добрый день!\n\n-- \n${SIG}`);
        expect(swapped).not.toContain(OTHER);
    });

    it('сохраняет написанный текст при смене отправителя', () => {
        const body = withSignature('Отправляю договор во вложении.', OTHER);
        expect(replaceSignature(body, OTHER, SIG))
            .toContain('Отправляю договор во вложении.');
    });

    it('убирает подпись, когда у нового отправителя её нет', () => {
        const body = withSignature('Добрый день!', OTHER);
        expect(replaceSignature(body, OTHER, '')).toBe('Добрый день!');
    });

    it('первая подстановка обходится без прежней подписи', () => {
        expect(replaceSignature('Добрый день!', null, SIG))
            .toBe(`Добрый день!\n\n-- \n${SIG}`);
    });

    it('переключение отправителя туда-обратно не плодит копий', () => {
        const start = 'Добрый день!';
        const a = replaceSignature(start, null, SIG);
        const b = replaceSignature(a, SIG, OTHER);
        const back = replaceSignature(b, OTHER, SIG);

        expect(back).toBe(a);
    });
});
