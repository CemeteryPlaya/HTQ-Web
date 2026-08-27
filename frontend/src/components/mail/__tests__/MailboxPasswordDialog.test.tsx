/**
 * Окно ввода пароля от корпоративного ящика.
 *
 * Проверяется то, ради чего у диалога вообще появился `kind`: текст отказа.
 * На пути `pending` ящик найден, и отказ означает ровно одно — не тот пароль.
 * На пути `suggest` платформа не знала, есть ли ящик (у голого IMAP это
 * нельзя выяснить без пароля), и причин у отказа две. Умолчи об этом — и
 * человек будет перебирать пароли от ящика, которого не существует.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MailboxPasswordDialog } from '@/components/mail/MailboxPasswordDialog';

const post = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock('@/api/client', () => ({ default: { post } }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: toastError } }));
vi.mock('@/components/mail/useCorporateMailbox', () => ({
    useInvalidateCorporateMailbox: () => () => {},
}));

const show = (kind: 'pending' | 'suggest') => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
        <QueryClientProvider client={client}>
            <MailboxPasswordDialog
                open
                onOpenChange={() => {}}
                domain="htq.group"
                fixedAddress="ruslan.amirov@htq.group"
                kind={kind}
            />
        </QueryClientProvider>,
    );
};

const submitWithPassword = async () => {
    fireEvent.change(screen.getByLabelText(/Пароль ящика/), {
        target: { value: 'S3cret!' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Подключить ящик/ }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    return String(toastError.mock.calls[0][0]);
};

beforeEach(() => {
    post.mockReset();
    toastError.mockReset();
    post.mockRejectedValue({ response: { data: { detail: 'Вход не выполнен' } } });
});

describe('MailboxPasswordDialog', () => {
    it('на пути догадки называет обе возможные причины отказа', async () => {
        show('suggest');
        const text = await submitWithPassword();

        expect(text).toContain('Вход не выполнен');
        expect(text).toContain('нет такого ящика');
    });

    it('на пути найденного ящика не выдумывает вторую причину', async () => {
        // Ящик тут точно есть — платформа сама его нашла. Намёк «возможно,
        // ящика не существует» отправил бы человека проверять несуществующую
        // проблему.
        show('pending');
        const text = await submitWithPassword();

        expect(text).toBe('Вход не выполнен');
    });

    it('ответ сервера показывается дословно, а не подменяется своим текстом', async () => {
        // «не тот пароль» и «сервер недоступен» требуют разных действий, и
        // сервер об этом знает больше нас.
        post.mockRejectedValue({ response: { data: { detail: 'Сервер недоступен: таймаут' } } });
        show('suggest');

        expect(await submitWithPassword()).toContain('Сервер недоступен: таймаут');
    });

    it('без ответа сервера остаётся общее сообщение', async () => {
        post.mockRejectedValue(new Error('network'));
        show('pending');

        expect(await submitWithPassword()).toBe('Не удалось подключить ящик');
    });
});
