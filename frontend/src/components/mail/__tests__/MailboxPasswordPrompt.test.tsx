/**
 * Подсказка «подключите рабочую почту» — два разных повода и одно окно.
 *
 * Проверяется то, что легко сломать незаметно: подсказка ДОЛЖНА появляться у
 * сотрудника, которому ящик ещё не заводили (раньше она молчала, и человек
 * не узнавал о своей почте ниоткуда), и НЕ должна превращаться в фоновый шум
 * — иначе её перестанут читать и пропустят действительно сломанный ящик.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MailboxPasswordPrompt } from '@/components/mail/MailboxPasswordPrompt';
import type { CorporateMailboxInfo } from '@/components/mail/useCorporateMailbox';

const info = vi.hoisted(() => ({ current: null as CorporateMailboxInfo | null }));

vi.mock('@/components/mail/useCorporateMailbox', () => ({
    useCorporateMailbox: () => ({ data: info.current }),
    useInvalidateCorporateMailbox: () => () => {},
    CORPORATE_MAILBOX_KEY: ['corporate-mailbox-connect'],
}));

const base: CorporateMailboxInfo = {
    allowed: true,
    self_service: false,
    domain: 'htq.group',
    own_address: 'ruslan.amirov@htq.group',
    mailbox: null,
    awaiting_password: false,
    suggest_connect: false,
};

const show = (patch: Partial<CorporateMailboxInfo>, variant: 'inline' | 'banner' = 'inline') => {
    info.current = { ...base, ...patch };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
        <QueryClientProvider client={client}>
            <MailboxPasswordPrompt variant={variant} />
        </QueryClientProvider>,
    );
};

beforeEach(() => {
    info.current = null;
    localStorage.clear();
});

describe('MailboxPasswordPrompt', () => {
    it('предлагает подключить почту, когда рабочий адрес корпоративный, а ящика нет', () => {
        show({ suggest_connect: true });

        expect(screen.getByText(/ещё не подключена/)).toBeInTheDocument();
        expect(screen.getByText(/ruslan\.amirov@htq\.group/)).toBeInTheDocument();
    });

    it('молчит, когда предлагать нечего', () => {
        show({});
        expect(screen.queryByRole('button', { name: /Ввести пароль/ })).not.toBeInTheDocument();
    });

    it('про найденный ящик говорит иначе, чем про догадку', () => {
        // «Ящик найден» — утверждение; выдавать за него предположение нельзя,
        // иначе сотрудник пойдёт искать несуществующую почту.
        show({
            awaiting_password: true,
            mailbox: {
                id: 1, address: 'ruslan.amirov@htq.group',
                status: 'active', last_error: null, awaiting_password: true,
            },
        });

        expect(screen.getByText(/найден на почтовом сервере/)).toBeInTheDocument();
    });

    it('найденный ящик перебивает догадку — сообщение одно, а не два', () => {
        show({
            suggest_connect: true,
            awaiting_password: true,
            mailbox: {
                id: 1, address: 'ruslan.amirov@htq.group',
                status: 'active', last_error: null, awaiting_password: true,
            },
        });

        expect(screen.getByText(/найден на почтовом сервере/)).toBeInTheDocument();
        expect(screen.queryByText(/ещё не подключена/)).not.toBeInTheDocument();
    });

    it('закрытую догадку не показывает снова', () => {
        localStorage.setItem('htq.mail.suggestConnectDismissed', 'ruslan.amirov@htq.group');
        show({ suggest_connect: true }, 'banner');

        expect(screen.queryByText(/ещё не подключена/)).not.toBeInTheDocument();
    });

    it('но закрытая догадка не глушит подсказку про ДРУГОЙ адрес', () => {
        // Адрес сотрудника сменили — прежнее «не показывать» к новому ящику
        // отношения не имеет.
        localStorage.setItem('htq.mail.suggestConnectDismissed', 'old.address@htq.group');
        show({ suggest_connect: true }, 'banner');

        expect(screen.getByText(/ещё не подключена/)).toBeInTheDocument();
    });
});
