/**
 * Раздел «Договоры» после переноса в «Закупки и оплаты» (A6.2): архив только
 * на чтение — плашка, формы закрыты, кнопок отправки и создания нет,
 * карточка ведёт «перенесён в ДГ-…» в модуль.
 */
import { screen } from '@testing-library/react';
import { FileText } from 'lucide-react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { renderWithProviders } from '@/test/renderWithProviders';

import { CollectionPageHeader } from './CollectionPage';
import { ContractsShell } from './ContractsShell';
import { MigratedTo } from './FrozenNotice';

vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));
vi.mock('@/components/BackToProfile', () => ({ BackToProfile: () => null }));

const NOT_FROZEN = { frozen: false, frozenAt: null as string | null, comment: '', isLoading: false };
const FROZEN = { ...NOT_FROZEN, frozen: true, frozenAt: '2026-10-01T10:00:00Z' };
const freeze = vi.fn(() => NOT_FROZEN);
vi.mock('@/hooks/useContractsFreeze', () => ({ useContractsFreeze: () => freeze() }));

afterEach(() => { freeze.mockReturnValue(NOT_FROZEN); });

const submit = vi.fn();

describe('ContractsShell — архив', () => {
  it('заморожен: плашка над экраном, заголовок «Архив договоров»', () => {
    freeze.mockReturnValue(FROZEN);
    renderWithProviders(<ContractsShell><div>Реестр договоров</div></ContractsShell>,
      { route: '/contracts/agreements' });
    expect(screen.getByTestId('contracts-frozen-banner')).toHaveTextContent('Раздел перенесён в «Закупки и оплаты»');
    expect(screen.getByText('Реестр договоров')).toBeInTheDocument();
    expect(screen.getByText('Архив договоров')).toBeInTheDocument();
  });

  it.each(['/contracts/agreements/new', '/contracts/invoices/5/edit'])(
    'заморожен: форма %s не показывается', (route) => {
      freeze.mockReturnValue(FROZEN);
      renderWithProviders(<ContractsShell><div>Форма</div></ContractsShell>, { route });
      expect(screen.queryByText('Форма')).not.toBeInTheDocument();
      expect(screen.getByText(/создавать и править документы здесь больше нельзя/)).toBeInTheDocument();
    },
  );

  it('не заморожен: ни плашки, ни замка на формах', () => {
    renderWithProviders(<ContractsShell><div>Форма</div></ContractsShell>,
      { route: '/contracts/agreements/new' });
    expect(screen.queryByTestId('contracts-frozen-banner')).not.toBeInTheDocument();
    expect(screen.getByText('Форма')).toBeInTheDocument();
  });
});

describe('Кнопки правки в архиве', () => {
  it('«Новый …» в шапке реестра не рисуется', () => {
    freeze.mockReturnValue(FROZEN);
    renderWithProviders(
      <CollectionPageHeader icon={FileText} title="Договоры" actions={<button type="button">Новый договор</button>} />,
    );
    expect(screen.queryByRole('button', { name: 'Новый договор' })).not.toBeInTheDocument();
  });

  it('незамороженный реестр — кнопка на месте', () => {
    renderWithProviders(
      <CollectionPageHeader icon={FileText} title="Договоры" actions={<button type="button">Новый договор</button>} />,
    );
    expect(screen.getByRole('button', { name: 'Новый договор' })).toBeInTheDocument();
  });

  it('отправки на согласование у документа раздела нет', () => {
    freeze.mockReturnValue(FROZEN);
    renderWithProviders(
      <SubmitForApproval subjectType="contracts.agreement" subjectId={1} state="draft" submit={submit} />,
    );
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('документы других разделов заморозка не трогает', () => {
    freeze.mockReturnValue(FROZEN);
    renderWithProviders(
      <SubmitForApproval subjectType="hr.bonus" subjectId={1} state="draft" submit={submit} />,
    );
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});

describe('MigratedTo — «перенесён в …»', () => {
  it('номер документа — ссылкой на карточку модуля', () => {
    renderWithProviders(
      <MigratedTo targets={[{ target_type: 'bpp.agreement', target_id: 'a-1', number: 'ДГ-2026-000001' }]} />,
    );
    expect(screen.getByText('Перенесён в')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ДГ-2026-000001' })).toHaveAttribute('href', '/bpp/agreements/a-1');
  });

  it('контрагент без номера — ссылка на карточку', () => {
    renderWithProviders(
      <MigratedTo targets={[{ target_type: 'bpp.counterparty', target_id: 'c-1', number: null }]} />,
    );
    expect(screen.getByRole('link', { name: 'карточку в «Закупках и оплатах»' }))
      .toHaveAttribute('href', '/bpp/counterparties/c-1');
  });

  it('неперенесённая запись — ничего', () => {
    const { container } = renderWithProviders(<MigratedTo targets={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
