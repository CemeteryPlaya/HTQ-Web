/**
 * «Документы по заявке» — договоры и счета раздела «Договоры», заведённые по
 * этой заявке, и кнопки завести новые.
 *
 * Показывается только на ОДОБРЕННОЙ заявке со строкой бюджета: до
 * одобрения документ по ней бэкенд всё равно не примет (409 из
 * `contracts/services/request_link.py`), а без строки бюджета заявка к
 * договорному контуру не относится. Данные идут через прокси contracts
 * (`/api/contracts/v1/requests/:id/documents`), а не через approvals:
 * договоры — чужие строки, и знать их форму — дело раздела «Договоры».
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { FileText, Plus, Receipt } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { contractsApi } from '@/api/contracts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function LinkedDocuments({ requestId }: { requestId: number }) {
  const { t } = useTranslation();
  const docs = useQuery({
    queryKey: ['contracts', 'linked-request', requestId, 'documents'],
    queryFn: () => contractsApi.getLinkedRequestDocuments(requestId).then((r) => r.data),
    retry: false,
  });
  const agreements = docs.data?.agreements ?? [];
  const invoices = docs.data?.invoices ?? [];
  const empty = docs.isSuccess && agreements.length === 0 && invoices.length === 0;

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle>{t('contracts.linkedRequest.documents')}</CardTitle>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to={`/contracts/agreements/new?request_id=${requestId}`}>
              <Plus className="mr-1 h-4 w-4" />{t('contracts.linkedRequest.createAgreement')}
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link to={`/contracts/invoices/new?request_id=${requestId}`}>
              <Plus className="mr-1 h-4 w-4" />{t('contracts.linkedRequest.createInvoice')}
            </Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {docs.isError && <p className="text-muted-foreground">{t('contracts.linkedRequest.unavailable')}</p>}
        {empty && <p className="text-muted-foreground">{t('contracts.linkedRequest.noDocuments')}</p>}
        {agreements.map((row) => (
          <Link key={`a-${row.id}`} to={`/contracts/agreements/${row.id}`} className="flex items-center gap-2 rounded-md border px-3 py-2 hover:bg-accent/50">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">Договор {row.number} — {row.name}</span>
            <span className="shrink-0 text-muted-foreground">{row.amount} {row.currency}</span>
          </Link>
        ))}
        {invoices.map((row) => (
          <Link key={`i-${row.id}`} to={`/contracts/invoices/${row.id}`} className="flex items-center gap-2 rounded-md border px-3 py-2 hover:bg-accent/50">
            <Receipt className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">Счёт: {row.name}</span>
            <span className="shrink-0 text-muted-foreground">{row.amount} {row.currency}</span>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
