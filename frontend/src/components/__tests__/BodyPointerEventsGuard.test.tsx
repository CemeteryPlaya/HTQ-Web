/**
 * Регрессия на баг «страница видна, но клики не работают».
 *
 * Сценарий заказчика: в форме открыт выпадающий список, форму закрывают, не
 * выбрав значение → Radix оставляет на <body> pointer-events: none, и весь
 * фронт перестаёт реагировать на клики.
 *
 * Первый тест воспроизводит саму утечку (фиксирует, что баг Radix никуда не
 * делся и сторож нужен). Второй проверяет, что сторож её снимает. Третий —
 * что сторож НЕ вмешивается, пока модалка честно открыта.
 */
import { render, fireEvent, screen, act } from '@testing-library/react';
import { describe, expect, it, afterEach, beforeAll } from 'vitest';
import { useState } from 'react';

import { BodyPointerEventsGuard } from '@/components/BodyPointerEventsGuard';
import { releaseStuckBodyLock } from '@/lib/bodyPointerEvents';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogClose, DialogContent, DialogFooter, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

beforeAll(() => {
  // jsdom не реализует Pointer Capture API — без заглушек Radix Select молча
  // не открывается и тест даёт ложноотрицательный результат.
  const proto = window.HTMLElement.prototype as unknown as Record<string, unknown>;
  proto.hasPointerCapture ??= () => false;
  proto.setPointerCapture ??= () => {};
  proto.releasePointerCapture ??= () => {};
  proto.scrollIntoView ??= () => {};
});

afterEach(() => { document.body.style.removeProperty('pointer-events'); });

const bodyLock = () => document.body.style.pointerEvents;
const dialogInDom = () => Boolean(document.querySelector('[role="dialog"]'));

/** Форма с выпадающим списком — типовая модалка этого проекта. */
function FormModal({ withGuard }: { withGuard: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {withGuard && <BodyPointerEventsGuard />}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button data-testid="open">Открыть</Button>
        </DialogTrigger>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Форма</DialogTitle>
          <Select>
            <SelectTrigger data-testid="select"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="a">A</SelectItem>
            </SelectContent>
          </Select>
          <DialogFooter>
            <DialogClose asChild>
              <Button data-testid="cancel">Отмена</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** Открыть модалку и выпадающий список внутри неё, значение НЕ выбирать. */
function openModalThenSelect(withGuard: boolean) {
  render(<FormModal withGuard={withGuard} />);
  act(() => { fireEvent.click(screen.getByTestId('open')); });
  act(() => {
    fireEvent.pointerDown(screen.getByTestId('select'),
      { button: 0, ctrlKey: false, pointerType: 'mouse' });
  });
  expect(document.querySelector('[role="option"]')).not.toBeNull();
}

describe('BodyPointerEventsGuard', () => {
  it('без сторожа: закрытие формы с открытым списком оставляет <body> заблокированным', () => {
    openModalThenSelect(false);

    act(() => { fireEvent.click(screen.getByTestId('cancel')); });

    expect(dialogInDom()).toBe(false);       // модалка закрыта…
    expect(bodyLock()).toBe('none');          // …а клики по странице заблокированы
  });

  it('сторож снимает осиротевшую блокировку после закрытия формы', async () => {
    openModalThenSelect(true);

    act(() => { fireEvent.click(screen.getByTestId('cancel')); });
    expect(dialogInDom()).toBe(false);

    // Ничего вручную не зовём: проверяем, что срабатывает именно подписка
    // MutationObserver. Она откладывает работу на requestAnimationFrame,
    // поэтому ждём реального кадра.
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    });

    expect(bodyLock()).toBe('');
  });

  it('пока модалка открыта, сторож блокировку НЕ трогает', () => {
    openModalThenSelect(true);

    act(() => { releaseStuckBodyLock(); });

    expect(dialogInDom()).toBe(true);
    expect(bodyLock()).toBe('none');
  });
});
