/**
 * Сверка адреса перед заведением корпоративного ящика.
 *
 * Зачем отдельный модуль: спрашивают одно и то же две разные формы — создание
 * ящика в /admin/mailboxes и галка «создать ящик» при создании пользователя.
 * Разойдись они в том, что считают «ящик уже есть», админ получал бы в одной
 * форме один вердикт, а в другой другой — при одинаковом поведении бэкенда.
 *
 * Бэкенд: GET /api/email/v1/mailboxes/lookup/ (apps/mail/services/lookup_service.py).
 * Он же считает и текст вердикта (`detail`) — здесь его не переписываем, чтобы
 * показанное в интерфейсе слово в слово совпадало с тем, по чему сервер потом
 * примет решение.
 */
import { useEffect, useState } from 'react';

import api from '@/api/client';

export type MailboxLookup = {
    address: string;
    exists: boolean;
    /** где нашли: только у нас, только на сервере, и там и там, или нигде */
    source: 'none' | 'local' | 'remote' | 'both';
    /** удалось ли вообще спросить почтовый сервер (см. докстринг lookup_service) */
    checked_remote: boolean;
    remote_detail: string | null;
    mailbox: { id: number; address: string; user_id: number | null } | null;
    owner_user_id: number | null;
    owner_conflict: boolean;
    can_attach: boolean;
    needs_password: boolean;
    detail: string;
};

export type LookupQuery = {
    address?: string;
    localPart?: string;
    firstName?: string;
    lastName?: string;
    /**
     * Email пользователя платформы. Если он в корпоративном домене, он же и
     * есть адрес ящика — бэкенд предпочтёт его транслитерации ФИО.
     */
    email?: string;
    userId?: number | null;
};

/**
 * Есть ли что спрашивать. Пустая форма адреса не задаёт, и запрос вернул бы
 * 400 — сверка должна молчать, пока админ не ввёл ни логина, ни ФИО.
 */
export const lookupIsAnswerable = (q: LookupQuery): boolean =>
    Boolean(
        q.address?.trim()
        || q.localPart?.trim()
        // Полуторный email («ruslan@») адреса ещё не задаёт — ждём собаку.
        || q.email?.includes('@')
        || (q.firstName?.trim() && q.lastName?.trim()),
    );

export const fetchMailboxLookup = async (q: LookupQuery): Promise<MailboxLookup> => {
    const params = new URLSearchParams();
    if (q.address?.trim()) {
        params.set('address', q.address.trim());
    } else {
        if (q.localPart?.trim()) params.set('local_part', q.localPart.trim());
        if (q.email?.trim()) params.set('email', q.email.trim());
        if (q.firstName?.trim()) params.set('first_name', q.firstName.trim());
        if (q.lastName?.trim()) params.set('last_name', q.lastName.trim());
    }
    if (q.userId) params.set('user_id', String(q.userId));
    const res = await api.get<MailboxLookup>(`email/v1/mailboxes/lookup/?${params.toString()}`);
    return res.data;
};

/** Что произойдёт по кнопке. */
export type LookupVerdict =
    /** адрес свободен — будет создан новый ящик */
    | 'free'
    /** ящик уже есть и будет подключён */
    | 'attach'
    /** ящик уже есть, но подключить его можно только с паролем */
    | 'needs-password'
    /** ящик занят другим сотрудником — платформа подберёт свободный адрес */
    | 'conflict';

export const lookupVerdict = (l?: MailboxLookup | null): LookupVerdict => {
    if (!l || !l.exists) return 'free';
    if (l.owner_conflict) return 'conflict';
    if (l.needs_password) return 'needs-password';
    return 'attach';
};

/** Подпись кнопки должна называть то, что произойдёт, а не то, что задумывал админ. */
export const lookupSubmitsAttach = (l?: MailboxLookup | null): boolean => {
    const verdict = lookupVerdict(l);
    return verdict === 'attach' || verdict === 'needs-password';
};

/**
 * Значение с задержкой — сверка не должна ходить на сервер на каждую букву.
 * Локальный хук вместо зависимости: он нужен ровно здесь.
 */
export const useDebounced = <T,>(value: T, delay = 400): T => {
    const [debounced, setDebounced] = useState(value);
    useEffect(() => {
        const id = setTimeout(() => setDebounced(value), delay);
        return () => clearTimeout(id);
    }, [value, delay]);
    return debounced;
};
