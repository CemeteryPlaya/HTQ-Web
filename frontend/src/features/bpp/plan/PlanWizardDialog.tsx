/**
 * Мастер F-03 «Сформировать закупку» (ТЗ §8.4): после проверки выбора
 * сервером (`plan/validate`, BR-021) — позиции с количеством; количество по
 * каждой позиции правится, но не больше «Остатка кол-во» (шаг 2).
 *
 * Шаг 3 — «Продолжить» создаёт черновик договора (F-04) или счёта без
 * договора (F-05) из этих позиций и открывает его форму. Если количество
 * меньше остатка, сумма позиции пересчитывается пропорционально остатку
 * суммы (до копейки, без `float`) — дальше её правят на форме.
 */
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { agreementApi, AGREEMENTS_BASE } from '../agreements/api';
import { sumMoney } from '../budgets/cents';
import { useIdempotentAction } from '../core/useIdempotentAction';
import { invoiceApi, INVOICES_BASE } from '../invoices/api';
import type { InitiatorRole } from '../requests/api';
import { parseQtyInput } from '../requests/requestForm';

import type { PlanSelection } from './api';
import { proportionalAmount, qtyProblem, shownQty } from './planSelection';

const TITLES = { contract: 'Оформить договор', invoice: 'Оформить счёт' } as const;

export function PlanWizardDialog({ selection, role, onClose }: {
  selection: PlanSelection | null;
  role: InitiatorRole | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [qty, setQty] = useState<Record<string, string>>({});

  useEffect(() => {
    if (selection) {
      setQty(Object.fromEntries(selection.items.map((item) => [item.id, shownQty(item.qty_left)])));
    }
  }, [selection]);

  const create = useIdempotentAction(async (key: string) => {
    if (!selection) return;
    const ids = selection.items.map((item) => item.id);
    const wanted = new Map(selection.items.map((item) => {
      const entered = parseQtyInput(qty[item.id] ?? '') ?? item.qty_left;
      return [item.id, {
        qty: entered, amount: proportionalAmount(item.amount_left, qty[item.id] ?? '', item.qty_left),
      }];
    }));
    const changed = selection.items.some((item) =>
      wanted.get(item.id)!.qty !== parseQtyInput(shownQty(item.qty_left)));
    if (selection.target === 'contract') {
      let card = await agreementApi.createFromPlan(key, ids, role);
      if (changed) {
        const items = card.items.map((item) => ({
          id: item.id, ...wanted.get(item.request_item_id)!,
        }));
        card = await agreementApi.save(card.id, `${key}-qty`, {
          version: card.version, items, amount: sumMoney(items.map((item) => item.amount)),
        });
      }
      void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry'] });
      navigate(`${AGREEMENTS_BASE}/${card.id}`);
      return;
    }
    let card = await invoiceApi.createFromPlan(key, ids, role);
    if (changed) {
      const lines = card.lines.map((line) => ({
        id: line.id, ...wanted.get(line.request_item_id)!,
      }));
      card = await invoiceApi.save(card.id, `${key}-qty`, {
        version: card.version, lines, amount: sumMoney(lines.map((line) => line.amount)),
      });
    }
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry'] });
    navigate(`${INVOICES_BASE}/${card.id}`);
  });

  if (!selection) return null;
  const problems = Object.fromEntries(selection.items.map((item) => [
    item.id, qtyProblem(qty[item.id] ?? '', item.qty_left),
  ]));
  const blocked = Object.values(problems).some(Boolean);

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
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t('bpp.document.cancel', 'Отмена')}
          </Button>
          <Button
            type="button"
            disabled={blocked || create.pending}
            onClick={() => {
              create.run().catch((error: unknown) =>
                reportApiError(error, t('bpp.plan.createFailed', 'Не удалось оформить документ')));
            }}
          >
            {create.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('bpp.plan.continue', 'Продолжить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
