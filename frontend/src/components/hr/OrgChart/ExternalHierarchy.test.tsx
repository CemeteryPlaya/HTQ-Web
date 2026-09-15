/**
 * Внешняя иерархия: дерево владения компаниями, только для чтения.
 *
 * Четыре предмета проверки — ровно то, что отличает этот экран: дерево
 * рисуется из реестра, пустой результат ОБЪЯСНЯЕТСЯ (иначе читается как сбой
 * загрузки), при отсутствии прав на реестр экран деградирует до списка
 * слагов, а не показывает ошибку, и, пока дерево ещё в полёте, экран обязан
 * молчать о правах вовсе — не выдавать деградацию за истину.
 */
import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { ExternalHierarchy } from './ExternalHierarchy';

const tree = vi.fn();
vi.mock('@/api/companies', () => ({ companiesApi: { tree: () => tree() } }));

const permissions = vi.fn();
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const TREE = [{
  slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '',
  children: [
    { slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction', status: 'active', country: 'KZ', children: [] },
    { slug: 'hi-tech-systems', name: 'Hi-Tech Systems', kind: 'it', status: 'active', country: 'KZ', children: [] },
  ],
}];

describe('ExternalHierarchy', () => {
  beforeEach(() => {
    tree.mockReset();
    permissions.mockReturnValue({
      company: 'hi-tech-group', subordinateCompanies: ['hi-tech-qazaqstan', 'hi-tech-systems'],
      isLoading: false,
    });
  });

  it('пока дерево компаний ещё грузится, показывает загрузку, а не «доступа нет»', () => {
    // permissions уже тёплые (isLoading: false, как бывает почти всегда — кэш
    // на 5 минут), а запрос дерева ещё не разрешился и не отклонён — сознательно
    // never-resolving промис вместо mockResolvedValue/mockRejectedValue. Синхронная
    // проверка сразу после рендера (без findBy*, который дождался бы оседания
    // запроса) — это и есть первый кадр, где раньше на миг показывалась
    // деградация вместо загрузки.
    tree.mockImplementation(() => new Promise(() => {}));
    permissions.mockReturnValue({
      company: 'hi-tech-group', subordinateCompanies: ['hi-tech-qazaqstan'], isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(screen.getByText(/^Загрузка/)).toBeInTheDocument();
    expect(screen.queryByText(/доступа к реестру компаний/i)).toBeNull();
    expect(screen.queryByText('hi-tech-qazaqstan')).toBeNull();
  });

  it('рисует дерево владения и отмечает подчинённые компании', async () => {
    tree.mockResolvedValue({ data: TREE });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText('Hi-Tech Group')).toBeInTheDocument();
    expect(screen.getByText('Hi-Tech Qazaqstan')).toBeInTheDocument();
    expect(screen.getAllByText(/подчин/i).length).toBeGreaterThan(0);
  });

  it('объясняет пустой результат, а не показывает пустоту', async () => {
    tree.mockResolvedValue({ data: TREE });
    permissions.mockReturnValue({
      company: 'hi-tech-group', subordinateCompanies: [], isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText(/не помечена руководящей/i)).toBeInTheDocument();
  });

  it('без прав на реестр деградирует до списка слагов, а не до ошибки', async () => {
    tree.mockRejectedValue({ response: { status: 403 } });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText('hi-tech-qazaqstan')).toBeInTheDocument();
    expect(screen.queryByText(/ошибк/i)).toBeNull();
  });
});
