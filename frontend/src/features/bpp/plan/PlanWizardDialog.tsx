/**
 * Мастер F-03 «Сформировать закупку» (ТЗ §8.4): после проверки выбора
 * сервером (`plan/validate`, BR-021) — проект, статья, вид закупки и
 * позиции; количество по каждой позиции правится, но не больше «Остатка
 * кол-во» (шаг 2).
 *
 * Шаг 3 — сохранение документа — открывает форму договора (F-04) или счёта
 * (F-05). Эти формы — этап 3 (B3.1, B3.2); до них мастер показывает
 * заготовку и честно говорит, что оформить документ пока нельзя.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';

import type { PlanSelection } from './api';
import { qtyProblem, shownQty } from './planSelection';

const TITLES = { contract: 'Оформить договор', invoice: 'Оформить счёт' } as const;


export function PlanWizardDialog({ selection, onClose }: {
  selection: PlanSelection | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [qty, setQty] = useState<Record<string, string>>({});

  useEffect(() => {
    if (selection) {
      setQty(Object.fromEntries(selection.items.map((item) => [item.id, shownQty(item.qty_left)])));
    }
  }, [selection]);

  if (!selection) return null;
  const problems = Object.fromEntries(selection.items.map((item) => [
    item.id, qtyProblem(qty[item.id] ?? '', item.qty_left),
  ]));

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t(`bpp.plan.${selection.target}`, TITLES[selection.target])}</DialogTitle>
          <DialogDescription>
            {t('bpp.plan.wizardHint', 'Проверьте количество по каждой позиции — не больше остатка к закупке.')}
          </DialogDescription>
        </DialogHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('bpp.plan.position', 'Позиция')}</TableHead>
              <TableHead>{t('bpp.plan.name', 'Наименование')}</TableHead>
              <TableHead className="text-right">{t('bpp.plan.qtyLeft', 'Остаток кол-во')}</TableHead>
              <TableHead className="w-36 text-right">{t('bpp.plan.qty', 'Количество')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {selection.items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>{item.sys_number}</TableCell>
                <TableCell>{item.name}</TableCell>
                <TableCell className="text-right">{shownQty(item.qty_left)}</TableCell>
                <TableCell>
                  <Input
                    className="text-right"
                    inputMode="decimal"
                    aria-label={`${t('bpp.plan.qty', 'Количество')} ${item.sys_number}`}
                    value={qty[item.id] ?? ''}
                    onChange={(event) => setQty({ ...qty, [item.id]: event.target.value })}
                  />
                  {problems[item.id] && (
                    <p className="mt-1 text-xs text-destructive">{problems[item.id]}</p>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="text-sm text-muted-foreground">
          {t('bpp.plan.documentsLater',
            'Формы договора и счёта появятся на этапе 3 модуля — тогда мастер откроет документ с этими позициями.')}
        </p>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t('bpp.document.cancel', 'Отмена')}
          </Button>
          <Button type="button" disabled>
            {t('bpp.plan.continue', 'Продолжить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
