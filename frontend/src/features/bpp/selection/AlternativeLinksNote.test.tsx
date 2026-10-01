/**
 * Строка о связи с альтернативой (B5.1, D-B51-3): у нового документа —
 * основание, у исходного — чем заменён, ссылками на АП и новый документ.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { AlternativeLinksNote } from './AlternativeLinksNote';

const renderNote = (links: Parameters<typeof AlternativeLinksNote>[0]['links']) =>
  render(<MemoryRouter><AlternativeLinksNote links={links} /></MemoryRouter>);

describe('AlternativeLinksNote', () => {
  it('у нового документа — «Основание: альтернатива АП-…» со ссылкой на АП', () => {
    renderNote({ basis: { offer_id: 'of1', offer_number: 'АП-2026-000007' }, replaced_by: null });
    expect(screen.getByTestId('alternative-basis')).toHaveTextContent(
      'Основание: альтернатива АП-2026-000007');
    expect(screen.getByRole('link', { name: 'АП-2026-000007' }))
      .toHaveAttribute('href', '/bpp/alternatives/of1');
  });

  it('у исходного — чем заменён: альтернатива и новый документ', () => {
    renderNote({
      basis: null,
      replaced_by: {
        offer_id: 'of1', offer_number: 'АП-2026-000007', result_type: 'agreement',
        result_id: 'ag1', result_number: 'ДГ-2026-000009',
      },
    });
    expect(screen.getByTestId('alternative-replaced')).toHaveTextContent(
      'Заменён альтернативой АП-2026-000007, новый документ ДГ-2026-000009');
    expect(screen.getByRole('link', { name: 'ДГ-2026-000009' }))
      .toHaveAttribute('href', '/bpp/agreements/ag1');
  });

  it('без связи — ничего', () => {
    const { container } = renderNote({ basis: null, replaced_by: null });
    expect(container).toBeEmptyDOMElement();
  });
});
