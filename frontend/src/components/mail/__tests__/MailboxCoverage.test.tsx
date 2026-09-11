/**
 * Список «у кого не работает почта» на странице «Корпоративные ящики».
 *
 * Смысл списка — не перечень фамилий, а понимание, чья очередь действовать:
 * завести ящик, свести бесхозный с владельцем или сходить к сотруднику за
 * паролем. Поэтому проверяется в первую очередь совет под каждой группой —
 * без него админ видит проблему, но не видит, что с ней делать.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MailboxCoverage } from '@/components/mail/MailboxCoverage';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { get } }));

const body = (over: Record<string, unknown> = {}) => ({
    domain: 'htq.group',
    provisioner: 'imap',
    can_create_remotely: false,
    users: [],
    ...over,
});

const row = (over: Record<string, unknown> = {}) => ({
    user_id: 1,
    email: 'ruslan.amirov@htq.group',
    full_name: 'Руслан Амиров',
    reason: 'no_mailbox',
    mailbox_id: null,
    ...over,
});

const show = async (data: Record<string, unknown>) => {
    get.mockResolvedValue({ data });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
        <QueryClientProvider client={client}>
            <MailboxCoverage />
        </QueryClientProvider>,
    );
    await screen.findByText((text) => text.length > 0, { selector: 'p,h3,td' });
};

beforeEach(() => get.mockReset());

describe('MailboxCoverage', () => {
    it('на голом IMAP не советует заводить ящик из платформы', async () => {
        // Платформа там ящики не создаёт — совет «нажмите создать» отправил бы
        // админа искать несуществующую кнопку.
        await show(body({ users: [row()] }));

        expect(await screen.findByText(/заводит почтовый администратор/)).toBeInTheDocument();
    });

    it('с Mailcow советует завести ящик прямо здесь', async () => {
        await show(body({
            provisioner: 'mailcow', can_create_remotely: true, users: [row()],
        }));

        expect(await screen.findByText(/платформа создаст его на сервере/)).toBeInTheDocument();
    });

    it('разводит три причины по группам, а не сваливает в один список', async () => {
        await show(body({
            users: [
                row({ user_id: 1, email: 'a@htq.group', reason: 'no_mailbox' }),
                row({ user_id: 2, email: 'b@htq.group', reason: 'not_linked' }),
                row({ user_id: 3, email: 'c@htq.group', reason: 'awaiting_password' }),
            ],
        }));

        expect(await screen.findByText('Ящика нет')).toBeInTheDocument();
        expect(screen.getByText('Ящик ничей')).toBeInTheDocument();
        expect(screen.getByText('Ждёт пароль')).toBeInTheDocument();
        // Совет у каждой группы свой — это и есть половина смысла списка.
        expect(screen.getByText(/вкладка «Сверка»/)).toBeInTheDocument();
        expect(screen.getByText(/Пароль вводит сотрудник/)).toBeInTheDocument();
    });

    it('пустой список — это хорошая новость, а не пустая таблица', async () => {
        await show(body());

        expect(await screen.findByText(/У всех сотрудников/)).toBeInTheDocument();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('без настроенного домена объясняет, чего не хватает', async () => {
        await show(body({ domain: '', provisioner: 'none' }));

        expect(await screen.findByText(/домен не настроен/i)).toBeInTheDocument();
    });
});
