/**
 * Логика вердикта сверки. Проверяется именно она, а не разметка: от того,
 * какой вердикт посчитан, зависит, потребует ли форма пароль и что напишет на
 * кнопке — ошибка здесь тихо возвращает старое поведение («создать дубль»),
 * ничего при этом не ломая заметно.
 */
import { describe, expect, it } from 'vitest';

import {
    MailboxLookup,
    lookupIsAnswerable,
    lookupSubmitsAttach,
    lookupVerdict,
} from '../mailboxLookup';

const lookup = (over: Partial<MailboxLookup> = {}): MailboxLookup => ({
    address: 'i.ivanov@htq.group',
    exists: false,
    source: 'none',
    checked_remote: true,
    remote_detail: null,
    mailbox: null,
    owner_user_id: null,
    owner_conflict: false,
    can_attach: false,
    needs_password: false,
    detail: '',
    ...over,
});

describe('lookupVerdict', () => {
    it('молчит, пока сверка не ответила', () => {
        expect(lookupVerdict(undefined)).toBe('free');
        expect(lookupVerdict(null)).toBe('free');
    });

    it('свободный адрес — обычное создание', () => {
        expect(lookupVerdict(lookup())).toBe('free');
    });

    it('найденный ничей ящик подключается', () => {
        expect(lookupVerdict(lookup({ exists: true, source: 'remote', can_attach: true })))
            .toBe('attach');
    });

    it('чужой ящик важнее пароля: подключать его нельзя в принципе', () => {
        const verdict = lookupVerdict(lookup({
            exists: true, source: 'local', owner_conflict: true,
            owner_user_id: 7, needs_password: true,
        }));
        expect(verdict).toBe('conflict');
    });

    it('ящик есть, но взять от него пароль неоткуда', () => {
        expect(lookupVerdict(lookup({
            exists: true, source: 'local', can_attach: true, needs_password: true,
        }))).toBe('needs-password');
    });
});

describe('lookupSubmitsAttach', () => {
    it('кнопка называет подключение и тогда, когда для него нужен пароль', () => {
        expect(lookupSubmitsAttach(lookup({ exists: true, can_attach: true }))).toBe(true);
        expect(lookupSubmitsAttach(lookup({
            exists: true, can_attach: true, needs_password: true,
        }))).toBe(true);
    });

    it('свободный адрес и чужой ящик оставляют кнопку «Создать»', () => {
        expect(lookupSubmitsAttach(lookup())).toBe(false);
        expect(lookupSubmitsAttach(lookup({ exists: true, owner_conflict: true }))).toBe(false);
    });
});

describe('lookupIsAnswerable', () => {
    it('пустая форма адреса не задаёт — спрашивать нечего', () => {
        expect(lookupIsAnswerable({})).toBe(false);
        expect(lookupIsAnswerable({ localPart: '   ', firstName: ' ', lastName: '' })).toBe(false);
    });

    it('одной фамилии мало: адрес собирается из имени И фамилии', () => {
        expect(lookupIsAnswerable({ lastName: 'Иванов' })).toBe(false);
        expect(lookupIsAnswerable({ firstName: 'Иван', lastName: 'Иванов' })).toBe(true);
    });

    it('явный логин или готовый адрес достаточны сами по себе', () => {
        expect(lookupIsAnswerable({ localPart: 'i.ivanov' })).toBe(true);
        expect(lookupIsAnswerable({ address: 'i.ivanov@htq.group' })).toBe(true);
    });

    it('email спрашивают только с собакой — «ruslan@» адреса ещё не задаёт', () => {
        expect(lookupIsAnswerable({ email: 'ruslan' })).toBe(false);
        expect(lookupIsAnswerable({ email: 'ruslan@' })).toBe(true);
        expect(lookupIsAnswerable({ email: 'ruslan.amirov@htq.group' })).toBe(true);
    });
});
