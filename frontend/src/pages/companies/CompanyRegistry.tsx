import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { Archive, ArchiveRestore, Building2, CornerDownRight, Pencil, Terminal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { BackToProfile } from '@/components/BackToProfile';
import { CompanyFormDialog } from '@/components/companies/CompanyFormDialog';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { isPlatformAdmin } from '@/lib/auth/roles';
import { COMPANY_KIND_LABELS, type Company, type CompanyTreeNode } from '@/types/companies';

type ApiErr = AxiosError<{ detail?: string; code?: string }>;

const errorText = (e: unknown, fallback: string) =>
  (e as ApiErr)?.response?.data?.detail ?? fallback;

function TreeBranch({ node, depth, selected, onSelect }: {
  node: CompanyTreeNode; depth: number; selected: string | null; onSelect: (slug: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.slug)}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent ${selected === node.slug ? 'bg-accent font-medium' : ''}`}
        style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}
      >
        {depth > 0 ? <CornerDownRight className="h-4 w-4 text-muted-foreground" /> : <Building2 className="h-4 w-4 text-primary" />}
        <span>{node.name}</span>
        <Badge variant="outline" className="ml-auto">{COMPANY_KIND_LABELS[node.kind]}</Badge>
      </button>
      {node.children.length > 0 && (
        <ul>{node.children.map((c) => (
          <TreeBranch key={c.slug} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} />
        ))}</ul>
      )}
    </li>
  );
}

const CompanyRegistry = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile({ retry: false });
  const platformAdmin = isPlatformAdmin(activeProfile?.roles);

  const [selected, setSelected] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'archive' | 'restore' | null>(null);
  const [editing, setEditing] = useState(false);

  const treeQuery = useQuery({ queryKey: ['companies', 'tree'], queryFn: async () => (await companiesApi.tree()).data });
  const listQuery = useQuery({ queryKey: ['companies', 'list'], queryFn: async () => (await companiesApi.list()).data });

  const bySlug = useMemo(() => new Map((listQuery.data ?? []).map((c) => [c.slug, c])), [listQuery.data]);
  const company: Company | undefined = selected ? bySlug.get(selected) : undefined;
  const archived = (listQuery.data ?? []).filter((c) => c.status === 'archived');

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['companies'] });

  const archiveMut = useMutation({
    mutationFn: (slug: string) => companiesApi.archive(slug),
    onSuccess: () => { toast.success(t('companies.archived', 'Компания переведена в архив')); invalidate(); },
    onError: (e) => toast.error(errorText(e, t('companies.archiveFailed', 'Не удалось архивировать'))),
    onSettled: () => setConfirm(null),
  });
  const restoreMut = useMutation({
    mutationFn: (slug: string) => companiesApi.restore(slug),
    onSuccess: () => { toast.success(t('companies.restored', 'Компания возвращена из архива')); invalidate(); },
    onError: (e) => toast.error(errorText(e, t('companies.restoreFailed', 'Не удалось восстановить'))),
    onSettled: () => setConfirm(null),
  });

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main className="container mx-auto w-full max-w-6xl flex-1 space-y-4 px-4 py-8">
        <BackToProfile />
        <div>
          <h1 className="text-2xl font-bold">{t('companies.title', 'Компании группы')}</h1>
          <p className="text-sm text-muted-foreground">
            {t('companies.subtitle', 'Дерево владения: холдинг и дочерние общества. Каждая компания — своя схема данных.')}
          </p>
        </div>

        <div className="flex items-start gap-2 rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          <Terminal className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            {t('companies.createHint',
              'Заведение новой компании — командой оператора: manage.py company_create <slug> --name … --kind … --parent … '
              + '(миграции схемы идут около минуты и в HTTP-запрос не помещаются).')}
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-[minmax(16rem,1fr)_2fr]">
          <section className="rounded-xl border bg-card p-3">
            <ul data-testid="company-tree" className="space-y-0.5">
              {(treeQuery.data ?? []).map((node) => (
                <TreeBranch key={node.slug} node={node} depth={0} selected={selected} onSelect={setSelected} />
              ))}
            </ul>
            {archived.length > 0 && (
              <div className="mt-3 border-t pt-3">
                <p className="px-2 text-xs uppercase text-muted-foreground">{t('companies.archivedHeading', 'В архиве')}</p>
                <ul className="space-y-0.5">
                  {archived.map((c) => (
                    <li key={c.slug}>
                      <button type="button" onClick={() => setSelected(c.slug)}
                        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent ${selected === c.slug ? 'bg-accent' : ''}`}>
                        <Archive className="h-4 w-4" /><span>{c.name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section className="rounded-xl border bg-card p-4">
            {!company ? (
              <p className="text-sm text-muted-foreground">{t('companies.pick', 'Выберите компанию в дереве.')}</p>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold">{company.name}</h2>
                  <Badge variant="outline">{COMPANY_KIND_LABELS[company.kind]}</Badge>
                  <Badge variant={company.status === 'active' ? 'default' : 'secondary'}>
                    {company.status === 'active' ? t('companies.status.active', 'Действует') : t('companies.status.archived', 'В архиве')}
                  </Badge>
                </div>
                <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
                  <dt className="text-muted-foreground">slug</dt><dd className="font-mono">{company.slug}</dd>
                  <dt className="text-muted-foreground">{t('companies.field.country', 'Страна')}</dt><dd>{company.country || '—'}</dd>
                  <dt className="text-muted-foreground">{t('companies.field.parent', 'Вышестоящая')}</dt><dd>{company.parent_slug ?? '—'}</dd>
                </dl>

                {platformAdmin && (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                      <Pencil className="mr-1 h-4 w-4" />{t('companies.edit', 'Изменить')}
                    </Button>
                    {company.status === 'active' ? (
                      <Button variant="destructive" size="sm" onClick={() => setConfirm('archive')}>
                        <Archive className="mr-1 h-4 w-4" />{t('companies.archive', 'В архив')}
                      </Button>
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => setConfirm('restore')}>
                        <ArchiveRestore className="mr-1 h-4 w-4" />{t('companies.restore', 'Вернуть из архива')}
                      </Button>
                    )}
                  </div>
                )}

                {confirm && (
                  <div role="alertdialog" className="rounded-lg border border-amber-300/70 bg-amber-50/70 p-3 text-sm dark:border-amber-800/70 dark:bg-amber-950/30">
                    <p>
                      {confirm === 'archive'
                        ? t('companies.confirmArchive', 'Архив закрывает весь трафик компании: её поддомен ответит 404. Данные остаются на месте.')
                        : t('companies.confirmRestore', 'Компания снова станет доступна на своём поддомене и войдёт в сводки холдинга.')}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" onClick={() => (confirm === 'archive' ? archiveMut : restoreMut).mutate(company.slug)}
                        disabled={archiveMut.isPending || restoreMut.isPending}>
                        {t('common.confirm', 'Подтвердить')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>{t('common.cancel', 'Отмена')}</Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>

        {company && (
          <CompanyFormDialog company={company} candidates={listQuery.data ?? []} open={editing}
            onOpenChange={setEditing} onSaved={() => invalidate()} />
        )}
      </main>
      <Footer />
    </div>
  );
};

export default CompanyRegistry;
