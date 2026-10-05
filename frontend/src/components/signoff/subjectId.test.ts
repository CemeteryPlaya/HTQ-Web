import { describe, expect, it } from 'vitest';

import { isSubjectIdReady } from './subjectId';

describe('isSubjectIdReady', () => {
  it('целый ключ — только конечное число', () => {
    expect(isSubjectIdReady(5)).toBe(true);
    expect(isSubjectIdReady(Number.NaN)).toBe(false);
  });

  it('строковый ключ (UUID документа БЗО) — непустая строка', () => {
    expect(isSubjectIdReady('3f0c1a52-9d1e-4a57-9a7e-2b1c0d4e5f60')).toBe(true);
    expect(isSubjectIdReady('')).toBe(false);
    expect(isSubjectIdReady('  ')).toBe(false);
  });
});
