import { describe, it, expect } from 'vitest';

import { companyStats, formatMw, legalLinks, socialLinks } from './company';
import { projects } from './projects';

describe('companyStats', () => {
  it('количество проектов следует за data/projects.ts', () => {
    expect(companyStats.projects).toBe(projects.length);
  });

  it('мощность полного цикла не превышает общую', () => {
    expect(companyStats.fullCycleMw).toBeLessThanOrEqual(companyStats.totalMw);
  });

  it('все показатели — положительные числа', () => {
    for (const value of Object.values(companyStats)) {
      expect(value).toBeGreaterThan(0);
    }
  });
});

describe('formatMw', () => {
  it('склеивает число с локализованной единицей', () => {
    expect(formatMw(160, 'МВт')).toBe('160 МВт');
    expect(formatMw(90, 'MW')).toBe('90 MW');
  });
});

describe('ссылки футера', () => {
  it('не содержат мёртвых href="#"', () => {
    for (const link of [...socialLinks, ...legalLinks]) {
      expect(link.href).not.toBe('#');
      expect(link.href.length).toBeGreaterThan(1);
    }
  });
});
