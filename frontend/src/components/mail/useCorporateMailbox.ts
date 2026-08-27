/**
 * Состояние корпоративного ящика текущего сотрудника.
 *
 * Один запрос на три поверхности — карточку в профиле, раздел «Почта» и
 * баннер после входа. Общий ключ react-query здесь не оптимизация, а условие
 * связности: разъедься они, сотрудник закрыл бы баннер вводом пароля и
 * продолжил видеть «введите пароль» в почте.
 *
 * Бэкенд: GET /api/email/v1/accounts/connect-corporate/
 * (apps/mail/views.py::corporate_connect_info).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';

import api from '@/api/client';

export type CorporateMailboxInfo = {
    /**
     * Показывать ли сотруднику форму подключения. Истинно, если админ включил
     * самообслуживание ЛИБО ящик уже назначен и ждёт пароль.
     */
    allowed: boolean;
    /** Собственно режим самообслуживания — без учёта «ждущего» ящика. */
    self_service: boolean;
    domain: string;
    /**
     * Рабочий адрес сотрудника, если он в корпоративном домене. Считается на
     * сервере: адрес — ещё и признак, по которому подключение разрешено без
     * `self_service`, и доверять присланному клиентом тут нельзя.
     */
    own_address: string;
    mailbox: {
        id: number;
        address: string;
        status: 'active' | 'archived' | 'deleted' | 'error';
        last_error: string | null;
        awaiting_password: boolean;
    } | null;
    /** Ящик привязан, но платформа не смогла получить к нему доступ сама. */
    awaiting_password: boolean;
    /**
     * Ящика нет, но рабочий адрес корпоративный — стоит предложить подключить.
     *
     * Не «ящик найден»: на голом IMAP существование ящика нельзя проверить
     * без пароля, поэтому подтверждением служит сам успешный вход при
     * подключении. См. apps/mail/views.py::corporate_connect_info.
     */
    suggest_connect: boolean;
};

export const CORPORATE_MAILBOX_KEY = ['corporate-mailbox-connect'] as const;

export const useCorporateMailbox = (enabled = true) =>
    useQuery({
        queryKey: CORPORATE_MAILBOX_KEY,
        queryFn: async () =>
            (await api.get<CorporateMailboxInfo>('email/v1/accounts/connect-corporate/')).data,
        staleTime: 60_000,
        retry: false,
        enabled,
    });

/** Сбросить всё, на что влияет подключение ящика. */
export const useInvalidateCorporateMailbox = () => {
    const qc = useQueryClient();
    return () => {
        qc.invalidateQueries({ queryKey: CORPORATE_MAILBOX_KEY });
        qc.invalidateQueries({ queryKey: ['email-accounts'] });
    };
};
