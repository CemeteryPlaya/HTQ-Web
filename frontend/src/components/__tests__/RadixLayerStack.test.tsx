/**
 * Слои Radix видят друг друга: Esc закрывает только верхний.
 *
 * Реестр слоёв `@radix-ui/react-dismissable-layer` живёт на уровне модуля.
 * Если пакеты Radix тянут разные его версии, у Dialog и у Popover/Select
 * оказываются два независимых реестра: окно не знает, что поверх него открыт
 * список, и Esc закрывает оба. Так было с `@radix-ui/react-dialog@1.1.15`
 * (слой 1.1.11) при остальных пакетах на слое 1.1.10: Esc в окне «Участники»
 * карточки задачи закрывал саму карточку, а в поле поиска не делал ничего.
 * Первый тест называет расхождение прямо, по lock-файлу; остальные проверяют
 * поведение.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

const dialogOpen = () => Boolean(document.querySelector('[role="dialog"][data-state="open"]'));

function Modal() {
  return (
    <Dialog defaultOpen>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Карточка</DialogTitle>
        <Popover>
          <PopoverTrigger asChild><Button>Участники</Button></PopoverTrigger>
          <PopoverContent>
            <button type="button">Иван Петров</button>
          </PopoverContent>
        </Popover>
        <Select>
          <SelectTrigger data-testid="select"><SelectValue placeholder="—" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="a">A</SelectItem>
          </SelectContent>
        </Select>
      </DialogContent>
    </Dialog>
  );
}

describe('стек слоёв Radix', () => {
  it('у всех пакетов Radix один реестр слоёв', () => {
    const lock = JSON.parse(readFileSync(resolve(__dirname, '../../../package-lock.json'), 'utf-8')) as {
      packages: Record<string, { version?: string }>;
    };
    const versions = Object.entries(lock.packages)
      .filter(([path]) => path.endsWith('node_modules/@radix-ui/react-dismissable-layer'))
      .map(([path, entry]) => `${path} ${entry.version}`);
    const distinct = new Set(versions.map((line) => line.split(' ')[1]));
    // Расхождение лечится выравниванием версий пакетов Radix (обычно одного
    // из них), а не правкой этого теста.
    expect(distinct.size, versions.join('\n')).toBe(1);
  });

  it('Esc в окне поверх диалога закрывает только это окно', async () => {
    render(<Modal />);
    await userEvent.click(screen.getByRole('button', { name: 'Участники' }));
    await userEvent.click(screen.getByRole('button', { name: 'Иван Петров' }));
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Иван Петров' })).not.toBeInTheDocument();
    expect(dialogOpen()).toBe(true);
    await userEvent.keyboard('{Escape}');
    expect(dialogOpen()).toBe(false);
  });

  it('Esc в открытом списке закрывает только список', () => {
    render(<Modal />);
    act(() => {
      fireEvent.pointerDown(screen.getByTestId('select'), { button: 0, ctrlKey: false, pointerType: 'mouse' });
    });
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    act(() => { fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' }); });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(dialogOpen()).toBe(true);
  });
});
