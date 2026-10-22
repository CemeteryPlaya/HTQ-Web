/**
 * Позиции формы заявки на тендер: наименование, характеристики, единица,
 * количество, плановая цена, сумма (на лету), дата потребности и своя
 * статья позиции — по умолчанию позиция идёт по статье заявки.
 */
import { useTranslation } from 'react-i18next';
import { Copy, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { formatMoney } from '@/features/bpp/format';
import type { Uom } from '@/features/bpp/refdata/api';

import type { RequestArticle } from './api';
import {
  emptyItem, itemAmount, itemsTotal, MAX_ITEMS, nextItemKey, type EditItem,
} from './requestForm';

/** Radix Select не принимает пустое значение пункта — «по статье заявки» так. */
const BY_REQUEST = '__request__';

interface Props {
  items: EditItem[];
  onChange: (items: EditItem[]) => void;
  uoms: Uom[];
  articles: RequestArticle[];
  defaultNeedDate: string;
  errors: Record<string, string>;
}

export function ItemsTable({ items, onChange, uoms, articles, defaultNeedDate, errors }: Props) {
  const { t } = useTranslation();
  const pcs = uoms.find((uom) => uom.code === 'pcs' || uom.short_name === 'шт')?.id ?? '';
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
              <TableHead>{t('tender.requests.itemName', 'Наименование')}</TableHead>
              <TableHead>{t('tender.requests.itemSpecs', 'Характеристики')}</TableHead>
              <TableHead className="w-28">{t('tender.requests.itemUom', 'Ед.')}</TableHead>
              <TableHead className="w-28 text-right">{t('tender.requests.itemQty', 'Кол-во')}</TableHead>
              <TableHead className="w-36 text-right">{t('tender.requests.itemPrice', 'Плановая цена')}</TableHead>
              <TableHead className="w-36 text-right">{t('tender.requests.itemAmount', 'Сумма')}</TableHead>
              <TableHead className="w-40">{t('tender.requests.needDate', 'Потребность к дате')}</TableHead>
              <TableHead className="w-52">{t('tender.requests.itemArticle', 'Статья')}</TableHead>
              <TableHead className="w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 && (
              <TableRow>
                <TableCell colSpan={10} className="text-center text-muted-foreground">
                  {t('tender.requests.noItemsYet', 'Позиций нет — добавьте первую')}
                </TableCell>
              </TableRow>
            )}
            {items.map((item, index) => {
              const error = errors[`item:${item.key}`];
              const amount = itemAmount(item);
              return (
                <TableRow key={item.key} data-testid="tender-request-item">
                  <TableCell>{index + 1}</TableCell>
                  <TableCell className="min-w-56">
                    <Input
                      value={item.name}
                      maxLength={500}
                      aria-label={t('tender.requests.itemName', 'Наименование')}
                      onChange={(event) => patch(item.key, { name: event.target.value })}
                    />
                    {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                  </TableCell>
                  <TableCell className="min-w-48">
                    <Input
                      value={item.specs}
                      maxLength={2000}
                      aria-label={t('tender.requests.itemSpecs', 'Характеристики')}
                      onChange={(event) => patch(item.key, { specs: event.target.value })}
                    />
                  </TableCell>
                  <TableCell>
                    <Select value={item.uom_id || undefined} onValueChange={(value) => patch(item.key, { uom_id: value })}>
                      <SelectTrigger aria-label={t('tender.requests.itemUom', 'Ед.')}>
                        <SelectValue placeholder="—" />
                      </SelectTrigger>
                      <SelectContent>
                        {uoms.map((uom) => (
                          <SelectItem key={uom.id} value={uom.id}>{uom.short_name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Input
                      className="text-right"
                      inputMode="decimal"
                      value={item.qty}
                      aria-label={t('tender.requests.itemQty', 'Кол-во')}
                      onChange={(event) => patch(item.key, { qty: event.target.value })}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      className="text-right"
                      inputMode="decimal"
                      value={item.plan_price}
                      aria-label={t('tender.requests.itemPrice', 'Плановая цена')}
                      onChange={(event) => patch(item.key, { plan_price: event.target.value })}
                    />
                  </TableCell>
                  <TableCell className="text-right">{amount === null ? '—' : formatMoney(amount)}</TableCell>
                  <TableCell>
                    <DateInput
                      value={item.need_date}
                      aria-label={t('tender.requests.needDate', 'Потребность к дате')}
                      onChange={(value) => patch(item.key, { need_date: value })}
                    />
                  </TableCell>
                  <TableCell>
                    <Select
                      value={item.article_id || BY_REQUEST}
                      onValueChange={(value) => patch(item.key, { article_id: value === BY_REQUEST ? '' : value })}
                    >
                      <SelectTrigger aria-label={t('tender.requests.itemArticle', 'Статья')}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={BY_REQUEST}>
                          {t('tender.requests.byRequestArticle', 'по статье заявки')}
                        </SelectItem>
                        {articles.map((article) => (
                          <SelectItem key={article.id} value={article.id}>
                            {`${article.code} — ${article.name}`}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        type="button" size="icon" variant="ghost" disabled={full}
                        aria-label={t('tender.requests.copyItem', 'Копировать позицию')}
                        onClick={() => onChange([
                          ...items.slice(0, index + 1),
                          { ...item, key: nextItemKey(), id: null },
                          ...items.slice(index + 1),
                        ])}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button" size="icon" variant="ghost"
                        aria-label={t('tender.requests.removeItem', 'Удалить позицию')}
                        onClick={() => onChange(items.filter((other) => other.key !== item.key))}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={6}>{t('tender.requests.itemsTotal', 'Плановая сумма позиций')}</TableCell>
              <TableCell className="text-right" data-testid="tender-items-total">
                {formatMoney(itemsTotal(items), 'KZT')}
              </TableCell>
              <TableCell colSpan={3} />
            </TableRow>
          </TableFooter>
        </Table>
      </div>
      {errors.items && <p className="text-sm text-destructive">{errors.items}</p>}
      <Button
        type="button" variant="outline" size="sm" disabled={full}
        onClick={() => onChange([...items, emptyItem(defaultNeedDate, pcs)])}
      >
        <Plus className="mr-1.5 h-4 w-4" />
        {t('tender.requests.addItem', 'Добавить позицию')}
      </Button>
    </div>
  );
}
