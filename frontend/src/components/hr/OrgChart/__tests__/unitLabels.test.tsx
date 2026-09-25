/**
 * Подпись вида подразделения берётся из словаря уровня модуля
 * (`UNIT_LABELS` через `translatedMap`).
 *
 * Первая проверка — сам словарь локалей: ключ `directorate` обязан
 * существовать и переводиться в обоих языках. Она статическая осознанно —
 * без реального словаря вторая проверка ниже не отличила бы «перевода нет»
 * от «ключ не резолвится».
 *
 * Вторая проверка раньше сверяла ТЕКСТ файла `OrgChartNode.tsx`
 * (`expect(source).toContain("directorate: 'hr.orgChart.unit.directorate'")`)
 * — то есть пиновала исходник, а не поведение: `unitLabel()` мог перестать
 * заглядывать в `UNIT_LABELS` вовсе, и такой регресс тест бы не заметил.
 * Теперь рендерится настоящий `OrgChartNode` с `unit_type: 'directorate'`
 * внутри `ReactFlowProvider` — минимальной обвязки, которой достаточно:
 * `<Handle>` внутри читает контекст стора (`useStoreApi`), а не дерево
 * `<ReactFlow>`, и без `nodeId` из `NodeIdContext` лишь один раз сообщает
 * `onError('010', ...)` в стор, не бросая исключение. Проверяется экранный
 * текст — «Дирекция» в русской локали, поднятой в src/test/setup.ts
 * настоящими ресурсами (public/locales/ru), а не мок-фолбэком.
 */
import { render, screen } from '@testing-library/react';
import { ReactFlowProvider, type NodeProps } from '@xyflow/react';
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { OrgChartNode, type OrgNodeData } from '../OrgChartNode';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '../../../../..');

function unitLabels(lng: string): Record<string, string> {
  const file = path.join(FRONTEND, 'public', 'locales', lng, 'translation.json');
  const dict = JSON.parse(fs.readFileSync(file, 'utf-8'));
  return dict.hr.orgChart.unit;
}

// Минимальный набор обязательных полей NodeProps: сам компонент читает
// только data/selected, остальные нужны лишь для соответствия типу.
const baseNodeProps = {
  id: 'dept_1',
  type: 'department',
  dragging: false,
  zIndex: 0,
  selectable: true,
  deletable: true,
  draggable: true,
  isConnectable: true,
  positionAbsoluteX: 0,
  positionAbsoluteY: 0,
} satisfies Partial<NodeProps>;

describe('org chart unit labels', () => {
  it('names the directorate in both locales', () => {
    expect(unitLabels('ru').directorate).toBe('Дирекция');
    expect(unitLabels('en').directorate).toBe('Directorate');
  });

  it('renders "Дирекция" for a department node with unit_type=directorate', () => {
    const data: OrgNodeData = {
      label: 'Дирекция по финансам и экономике',
      type: 'department',
      unit_type: 'directorate',
    };

    render(
      <ReactFlowProvider>
        <OrgChartNode {...baseNodeProps} selected={false} data={data} />
      </ReactFlowProvider>,
    );

    expect(screen.getByText('Дирекция')).toBeInTheDocument();
  });
});
