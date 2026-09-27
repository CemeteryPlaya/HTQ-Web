/**
 * Карта представлений карточки согласования (B2.5): ключ приходит строкой,
 * UUID документа БЗО доходит до представления как есть, а старому домену с
 * целыми id переходник отдаёт число.
 */
import { render, screen } from '@testing-library/react';
import { Suspense } from 'react';
import { describe, expect, it } from 'vitest';

import {
  intKeyed,
  SIGNOFF_SUBJECT_VIEWS,
  stringKeyed,
  type IntSubjectViewProps,
  type SubjectViewProps,
} from '@/app/signoffSubjectViews';

const IntProbe = ({ id, embedded }: IntSubjectViewProps) => (
  <p>{`${typeof id}:${id}:${embedded ? 'embedded' : 'page'}`}</p>
);
const StringProbe = ({ id }: SubjectViewProps) => <p>{`${typeof id}:${id}`}</p>;

describe('SIGNOFF_SUBJECT_VIEWS', () => {
  it('отдаёт представлению с целыми id число', async () => {
    const View = intKeyed(async () => ({ default: IntProbe }));
    render(
      <Suspense fallback="…">
        <View id="42" embedded />
      </Suspense>,
    );
    expect(await screen.findByText('number:42:embedded')).toBeInTheDocument();
  });

  it('отдаёт UUID документа БЗО строкой, без NaN', async () => {
    const uuid = '0b7c6a52-7f2e-4a51-9d0c-3e8f1f2a9c11';
    const View = stringKeyed(async () => ({ default: StringProbe }));
    render(
      <Suspense fallback="…">
        <View id={uuid} />
      </Suspense>,
    );
    expect(await screen.findByText(`string:${uuid}`)).toBeInTheDocument();
  });

  it('держит представления старых доменов в карте', () => {
    expect(Object.keys(SIGNOFF_SUBJECT_VIEWS)).toEqual(
      expect.arrayContaining(['approvals.request', 'contracts.agreement']),
    );
  });
});
