/**
 * Блок 3 «Позиции» формы F-02 (ТЗ §7.4): наименование, характеристики, ед.
 * изм., количество, ориентировочная цена, сумма (CALC-004, на лету), дата
 * потребности; «Копировать» и «Удалить» строку; до 200 позиций; вставка из
 * буфера (Excel: Наименование / Ед. / Кол-во / Цена — ТЗ §7.4 [Л]).
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardPaste, Copy, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';

import { formatMoney } from '../format';

import {
  emptyItem, lineAmount, MAX_ITEMS, nextItemKey, parsePastedItems, totalAmount,
  type EditItem, type Uom,
} from './requestForm';

interface Props {
  items: EditItem[];
  onChange: (items: EditItem[]) => void;
  editable: boolean;
  uoms: Uom[];
  currency: string;
  defaultNeedDate: string;
  errors: Record<string, string>;
}

export function ItemsEditor({
  items, onChange, editable, uoms, currency, defaultNeedDate, errors,
}: Props) {
  const { t } = useTranslation();
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasted, setPasted] = useState('');
  const pcs = uoms.find((uom) => uom.code === 'pcs' || uom.short_name === 'шт')?.id ?? '';
  const uomName = new Map(uoms.map((uom) => [uom.id, uom.short_name]));

  const patch = (key: string, change: Partial<EditItem>) =>
    onChange(items.map((item) => (item.key === key ? { ...item, ...change } : item)));
  const full = items.length >= MAX_ITEMS;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">№</TableHead>
              <TableHead>{t('bpp.requests.itemName', 'Наименование')}</TableHead>
              <TableHead>{t('bpp.requests.itemSpecs', 'Характеристики')}</TableHead>
              <TableHead className="w-28">{t('bpp.requests.itemUom', 'Ед.')}</TableHead>
              <TableHead className="w-28 text-right">{t('bpp.requests.itemQty', 'Кол-во')}</TableHead>
              <TableHead className="w-36 text-right">{t('bpp.requests.itemPrice', 'Цена')}</TableHead>
              <TableHead className="w-36 text-right">{t('bpp.requests.itemAmount', 'Сумма')}</TableHead>
              <TableHead className="w-40">{t('bpp.requests.needDate', 'Дата потребности')}</TableHead>
              {editable && <TableHead className="w-20" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="text-center text-muted-foreground">
                  {t('bpp.requests.noItems', 'Позиций нет — добавьте или вставьте из Excel')}
                </TableCell>
              </TableRow>
            )}
            {items.map((item, index) => {
              const error = errors[`item:${item.key}`];
              const amount = lineAmount(item.qty, item.price);
              return (
                <TableRow key={item.key} data-testid="request-item">
                  <TableCell>
                    <div>{index + 1}</div>
                    {item.sys_number && (
                      <div className="text-xs text-muted-foreground">{item.sys_number}</div>
                    )}
                  </TableCell>
                  <TableCell className="min-w-56">
                    {editable ? (
                      <Input
                        value={item.name}
                        maxLength={500}
                        aria-label={t('bpp.requests.itemName', 'Наименование')}
                        onChange={(event) => patch(item.key, { name: event.target.value })}
                      />
                    ) : item.name}
                    {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                  </TableCell>
                  <TableCell className="min-w-48">
                    {editable ? (
                      <Input
                        value={item.specs}
                        maxLength={2000}
                        aria-label={t('bpp.requests.itemSpecs', 'Характеристики')}
                        onChange={(event) => patch(item.key, { specs: event.target.value })}
                      />
                    ) : item.specs || '—'}
                  </TableCell>
                  <TableCell>
                    {editable ? (
                      <Select
                        value={item.uom_id || undefined}
                        onValueChange={(value) => patch(item.key, { uom_id: value })}
                      >
                        <SelectTrigger aria-label={t('bpp.requests.itemUom', 'Ед.')}>
                          <SelectValue placeholder="—" />
                        </SelectTrigger>
                        <SelectContent>
                          {uoms.map((uom) => (
                            <SelectItem key={uom.id} value={uom.id}>{uom.short_name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : uomName.get(item.uom_id) ?? '—'}
                  </TableCell>
                  <TableCell className="text-right">
                    {editable ? (
                      <Input
                        className="text-right"
                        inputMode="decimal"
                        value={item.qty}
                        aria-label={t('bpp.requests.itemQty', 'Кол-во')}
                        onChange={(event) => patch(item.key, { qty: event.target.value })}
                      />
                    ) : item.qty}
                  </TableCell>
                  <TableCell className="text-right">
                    {editable ? (
                      <Input
                        className="text-right"
                        inputMode="decimal"
                        value={item.price}
                        aria-label={t('bpp.requests.itemPrice', 'Цена')}
                        onChange={(event) => patch(item.key, { price: event.target.value })}
                      />
                    ) : item.price}
                  </TableCell>
                  <TableCell className="text-right">
                    {amount === null ? '—' : formatMoney(amount)}
                  </TableCell>
                  <TableCell>
                    {editable ? (
                      <DateInput
                        value={item.need_date}
                        aria-label={t('bpp.requests.needDate', 'Дата потребности')}
                        onChange={(value) => patch(item.key, { need_date: value })}
                      />
                    ) : item.need_date.split('-').reverse().join('.')}
                  </TableCell>
                  {editable && (
                    <TableCell>
                      <div className="flex gap-1">
                        <Button
                          type="button" size="icon" variant="ghost" disabled={full}
                          aria-label={t('bpp.requests.copyItem', 'Копировать позицию')}
                          onClick={() => onChange([
                            ...items.slice(0, index + 1),
                            { ...item, key: nextItemKey(), sys_number: null },
                            ...items.slice(index + 1),
                          ])}
                        >
                          <Copy className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button" size="icon" variant="ghost"
                          aria-label={t('bpp.requests.removeItem', 'Удалить позицию')}
                          onClick={() => onChange(items.filter((other) => other.key !== item.key))}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              );
            })}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={6}>{t('bpp.requests.total', 'Сумма заявки')}</TableCell>
              <TableCell className="text-right" data-testid="request-total">
                {formatMoney(totalAmount(items), currency)}
              </TableCell>
              <TableCell colSpan={editable ? 2 : 1} />
            </TableRow>
          </TableFooter>
        </Table>
      </div>
      {errors.items && <p className="text-sm text-destructive">{errors.items}</p>}
      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button" variant="outline" size="sm" disabled={full}
            onClick={() => onChange([...items, emptyItem(defaultNeedDate, pcs)])}
          >
            <Plus className="mr-1.5 h-4 w-4" />
            {t('bpp.requests.addItem', 'Добавить позицию')}
          </Button>
          <Button
            type="button" variant="outline" size="sm" disabled={full}
            onClick={() => { setPasted(''); setPasteOpen(true); }}
          >
            <ClipboardPaste className="mr-1.5 h-4 w-4" />
            {t('bpp.requests.pasteItems', 'Вставить из Excel')}
          </Button>
        </div>
      )}

      <Dialog open={pasteOpen} onOpenChange={setPasteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('bpp.requests.pasteTitle', 'Вставить позиции из Excel')}</DialogTitle>
            <DialogDescription>
              {t('bpp.requests.pasteHint',
                'Скопируйте из таблицы колонки «Наименование», «Ед.», «Кол-во», «Цена» и вставьте сюда.')}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            rows={8}
            value={pasted}
            aria-label={t('bpp.requests.pasteTitle', 'Вставить позиции из Excel')}
            onChange={(event) => setPasted(event.target.value)}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPasteOpen(false)}>
              {t('bpp.document.cancel', 'Отмена')}
            </Button>
            <Button
              type="button"
              onClick={() => {
                const added = parsePastedItems(pasted, uoms, defaultNeedDate);
                onChange([...items, ...added].slice(0, MAX_ITEMS));
                setPasteOpen(false);
              }}
            >
              {t('bpp.requests.pasteApply', 'Добавить позиции')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
