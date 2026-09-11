/**
 * Плашка предпосылок — единственный способ, которым платформа объясняет
 * сотруднику пустой селект. Проверяем ровно три её обязательства:
 *
 * 1. молчит, когда всё на месте (иначе плашку пришлось бы оборачивать в
 *    условие на каждой форме, и однажды это забыли бы сделать);
 * 2. показывает ТОЛЬКО невыполненное — иначе человек пойдёт заводить то,
 *    что у него уже есть;
 * 3. даёт ссылку туда, где недостающее заводится: подсказка без адреса —
 *    это тот же тупик, только вежливый.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';

const draw = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('PrerequisiteNotice', () => {
  it('не рисует ничего, когда все предпосылки выполнены', () => {
    const { container } = draw(
      <PrerequisiteNotice
        title="Сначала нужны справочники:"
        items={[{ when: false, text: 'Нет бюджета —', to: '/x', linkText: 'создайте' }]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('показывает только невыполненные пункты', () => {
    draw(
      <PrerequisiteNotice
        title="Сначала нужны справочники:"
        items={[
          { when: true, text: 'Реестр контрагентов пуст —', to: '/c/new', linkText: 'добавьте поставщика' },
          { when: false, text: 'Нет ни одного бюджета —', to: '/b/new', linkText: 'создайте бюджетную строку' },
        ]}
      />,
    );
    expect(screen.getByText(/Реестр контрагентов пуст/)).toBeInTheDocument();
    expect(screen.queryByText(/Нет ни одного бюджета/)).not.toBeInTheDocument();
  });

  it('ведёт ссылкой туда, где недостающее заводится', () => {
    draw(
      <PrerequisiteNotice
        items={[{ when: true, text: 'Договоров пока нет —', to: '/contracts/agreements/new', linkText: 'оформите договор' }]}
      />,
    );
    expect(screen.getByRole('link', { name: 'оформите договор' }))
      .toHaveAttribute('href', '/contracts/agreements/new');
  });

  it('в inline-варианте обходится без карточки и заголовка', () => {
    draw(
      <PrerequisiteNotice
        variant="inline"
        title="Не показывается"
        items={[{ when: true, text: 'У этого администратора нет согласованных договоров' }]}
      />,
    );
    expect(screen.queryByText('Не показывается')).not.toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(
      'У этого администратора нет согласованных договоров.',
    );
  });
});
