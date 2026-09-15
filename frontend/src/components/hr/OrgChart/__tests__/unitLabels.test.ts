/**
 * Подпись вида подразделения берётся из словаря уровня модуля
 * (`UNIT_LABELS` через `translatedMap`), поэтому проверяется статически:
 * ключ обязан существовать в обоих словарях и упоминаться в компоненте.
 * Тот же приём, что в src/lib/i18n/__tests__/translationKeys.test.ts.
 */
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '../../../../..');

function unitLabels(lng: string): Record<string, string> {
  const file = path.join(FRONTEND, 'public', 'locales', lng, 'translation.json');
  const dict = JSON.parse(fs.readFileSync(file, 'utf-8'));
  return dict.hr.orgChart.unit;
}

describe('org chart unit labels', () => {
  it('names the directorate in both locales', () => {
    expect(unitLabels('ru').directorate).toBe('Дирекция');
    expect(unitLabels('en').directorate).toBe('Directorate');
  });

  it('OrgChartNode maps unit_type=directorate to that key', () => {
    const source = fs.readFileSync(path.join(HERE, '..', 'OrgChartNode.tsx'), 'utf-8');
    expect(source).toContain("directorate: 'hr.orgChart.unit.directorate'");
  });
});
