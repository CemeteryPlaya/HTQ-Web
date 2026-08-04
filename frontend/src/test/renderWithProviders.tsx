import React from 'react';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

/**
 * Рендер компонента со всем контекстом, который нужен страницам приложения.
 *
 * В проекте до сих пор был ровно один компонентный тест — на диалог без
 * зависимостей, поэтому обходились голым `render()`. Страницы же держатся на
 * react-query (`useQuery`/`useMutation`) и react-router (`useSearchParams`,
 * `NavLink`), и без провайдеров падают на первом же хуке.
 *
 * i18next поднят глобально в `src/test/setup.ts` с пустыми ресурсами:
 * компоненты зовут `t(key, 'фолбэк')`, и в тестах видно именно фолбэк-строку.
 * Поэтому `react-i18next` мокать не нужно.
 */

interface Options extends Omit<RenderOptions, 'wrapper'> {
  /** Начальный URL — для страниц, читающих query-параметры (?tab=levels). */
  route?: string;
}

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // retry=false — иначе тест на ошибку 409 ждёт три повтора и падает по
      // таймауту вместо того, чтобы сразу показать сообщение.
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: React.ReactElement,
  { route = '/', ...options }: Options = {},
): RenderResult & { queryClient: QueryClient } {
  const queryClient = createTestQueryClient();

  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );

  return { ...render(ui, { wrapper: Wrapper, ...options }), queryClient };
}
