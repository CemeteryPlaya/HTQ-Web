import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Archive, ArchiveRestore, Building2, CornerDownRight, Handshake, Pencil, Terminal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { BackToProfile } from '@/components/BackToProfile';
import { CompanyFormDialog } from '@/components/companies/CompanyFormDialog';
import { CompanyMembersPanel } from '@/components/companies/CompanyMembersPanel';
import { CompanyModulesPanel } from '@/components/companies/CompanyModulesPanel';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';
import { isPlatformAdmin } from '@/lib/auth/roles';
import { COMPANY_KIND_LABELS, type BankruptResult, type Company, type CompanyTreeNode } from '@/types/companies';

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
  // На поддомене архива запись закрыта всем (403 company_archived), включая
  // платформенные операции — они идут по суперпользователю, не по уровню,
  // и сами не спрячутся (спека архива §7.2).
  const { companyArchived } = usePermissions();
  const canWrite = platformAdmin && !companyArchived;

  const [selected, setSelected] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'archive' | 'restore' | 'bankrupt' | null>(null);
  const [successor, setSuccessor] = useState('');
  const [preview, setPreview] = useState<BankruptResult | null>(null);
  const [editing, setEditing] = useState(false);
  const [panel, setPanel] = useState<'modules' | 'members'>('modules');

  const treeQuery = useQuery({ queryKey: ['companies', 'tree'], queryFn: async () => (await companiesApi.tree()).data });
  const listQuery = useQuery({ queryKey: ['companies', 'list'], queryFn: async () => (await companiesApi.list()).data });

  const bySlug = useMemo(() => new Map((listQuery.data ?? []).map((c) => [c.slug, c])), [listQuery.data]);
  const company: Company | undefined = selected ? bySlug.get(selected) : undefined;
  const archived = (listQuery.data ?? []).filter((c) => c.status === 'archived');

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['companies'] });
  // Ответ dry_run может прийти уже после смены преемника или компании —
  // устаревший предпросмотр не показываем и подтвердить по нему не даём:
  // выданные членства банкротство не отзывает.
  const currentPreview = preview && company
    && preview.company.slug === company.slug && preview.successor.slug === successor
    ? preview : null;

  // Смена выбранной компании сбрасывает начатое банкротство: преемник и
  // предпросмотр относятся к прежней компании.
  const select = (slug: string) => {
    setSelected(slug);
    setConfirm(null);
    setSuccessor('');
    setPreview(null);
  };

  // Реестр перезапрашивается и после ошибки: ответ 409 `holding_stale`
  // значит, что статус компании уже сменился и упала только пересборка
  // сводок. Обновление лишь в onSuccess оставило бы на экране прежний
  // статус и кнопки, которые к нему больше не относятся.
  const archiveMut = useMutation({
    mutationFn: (slug: string) => companiesApi.archive(slug),
    onSuccess: () => toast.success(t('companies.archived', 'Компания переведена в архив')),
    onError: (e) => reportApiError(e, t('companies.archiveFailed', 'Не удалось архивировать')),
    onSettled: () => { setConfirm(null); invalidate(); },
  });
  const restoreMut = useMutation({
    mutationFn: (slug: string) => companiesApi.restore(slug),
    onSuccess: () => toast.success(t('companies.restored', 'Компания возвращена из архива')),
    onError: (e) => reportApiError(e, t('companies.restoreFailed', 'Не удалось восстановить')),
    onSettled: () => { setConfirm(null); invalidate(); },
  });
  const previewMut = useMutation({
    mutationFn: (slug: string) => companiesApi.bankrupt(slug, { successor, dry_run: true }),
    onSuccess: (res) => setPreview(res.data),
    onError: (e) => reportApiError(e, t('companies.bankruptcy.previewFailed', 'Не удалось проверить')),
  });
  const bankruptMut = useMutation({
    mutationFn: (slug: string) => companiesApi.bankrupt(slug, { successor, dry_run: false }),
    onSuccess: () => toast.success(t('companies.bankruptcy.done', 'Компания закрыта, дела переданы преемнику')),
    onError: (e) => reportApiError(e, t('companies.bankruptcy.failed', 'Не удалось провести банкротство')),
    onSettled: () => { setConfirm(null); setPreview(null); setSuccessor(''); invalidate(); },
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
                <TreeBranch key={node.slug} node={node} depth={0} selected={selected} onSelect={select} />
              ))}
            </ul>
            {archived.length > 0 && (
              <div className="mt-3 border-t pt-3">
                <p className="px-2 text-xs uppercase text-muted-foreground">{t('companies.archivedHeading', 'В архиве')}</p>
                <ul className="space-y-0.5">
                  {archived.map((c) => (
                    <li key={c.slug}>
                      <button type="button" onClick={() => select(c.slug)}
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
                  {company.successor_slug && (<>
                    <dt className="text-muted-foreground">{t('companies.bankruptcy.successor', 'Преемник')}</dt>
                    <dd>{bySlug.get(company.successor_slug)?.name ?? company.successor_slug}</dd>
                  </>)}
                </dl>

                {canWrite && (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                      <Pencil className="mr-1 h-4 w-4" />{t('companies.edit', 'Изменить')}
                    </Button>
                    {company.status === 'active' ? (<>
                      <Button variant="destructive" size="sm" onClick={() => setConfirm('archive')}>
                        <Archive className="mr-1 h-4 w-4" />{t('companies.archive', 'В архив')}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => setConfirm('bankrupt')}>
                        <Handshake className="mr-1 h-4 w-4" />{t('companies.bankruptcy.button', 'Банкротство…')}
                      </Button>
                    </>) : (
                      <Button variant="outline" size="sm" onClick={() => setConfirm('restore')}>
                        <ArchiveRestore className="mr-1 h-4 w-4" />{t('companies.restore', 'Вернуть из архива')}
                      </Button>
                    )}
                  </div>
                )}

                {platformAdmin && companyArchived && (
                  <p className="text-sm text-muted-foreground">
                    {t('companies.archiveMode.restoreElsewhere', 'Восстановить компанию можно из реестра на поддомене действующей компании.')}
                  </p>
                )}

                {(confirm === 'archive' || confirm === 'restore') && (
                  <div role="alertdialog" className="rounded-lg border border-amber-300/70 bg-amber-50/70 p-3 text-sm dark:border-amber-800/70 dark:bg-amber-950/30">
                    <p>
                      {confirm === 'archive'
                        ? t('companies.confirmArchive', 'Архив закрывает компанию на запись: её поддомен откроется только администратору платформы и только на чтение. Данные остаются на месте.')
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

                {confirm === 'bankrupt' && (
                  <div role="alertdialog" className="space-y-2 rounded-lg border border-amber-300/70 bg-amber-50/70 p-3 text-sm dark:border-amber-800/70 dark:bg-amber-950/30">
                    <label className="flex items-center gap-2">
                      <span>{t('companies.bankruptcy.successor', 'Преемник')}</span>
                      <select className="rounded-md border px-2 py-1"
                        value={successor} onChange={(e) => { setSuccessor(e.target.value); setPreview(null); }}>
                        <option value="">—</option>
                        {(listQuery.data ?? []).filter((c) => c.status === 'active' && c.slug !== company.slug)
                          .map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
                      </select>
                    </label>
                    {currentPreview && (
                      <p>{t('companies.bankruptcy.preview',
                        '{{count}} сотрудник(ов) получат доступ к «{{name}}» (уже там: {{already}}); компания уйдёт в архив (только чтение). Карточки сотрудников, техника и договоры не переносятся.',
                        { count: currentPreview.members_granted, name: currentPreview.successor.name, already: currentPreview.members_already })}</p>
                    )}
                    <div className="flex gap-2">
                      {!currentPreview ? (
                        <Button size="sm" disabled={!successor || previewMut.isPending} onClick={() => previewMut.mutate(company.slug)}>
                          {t('companies.bankruptcy.check', 'Проверить')}
                        </Button>
                      ) : (
                        <Button size="sm" variant="destructive" disabled={bankruptMut.isPending} onClick={() => bankruptMut.mutate(company.slug)}>
                          {t('companies.bankruptcy.confirm', 'Подтвердить банкротство')}
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => { setConfirm(null); setPreview(null); setSuccessor(''); }}>
                        {t('common.cancel', 'Отмена')}
                      </Button>
                    </div>
                  </div>
                )}

                <div className="border-t pt-4">
                  <div className="mb-2 flex gap-2">
                    {(['modules', 'members'] as const).map((tab) => (
                      <Button key={tab} size="sm" variant={panel === tab ? 'default' : 'outline'} onClick={() => setPanel(tab)}>
                        {tab === 'modules' ? t('companies.tab.modules', 'Модули') : t('companies.tab.members', 'Участники')}
                      </Button>
                    ))}
                  </div>
                  {panel === 'modules'
                    ? <CompanyModulesPanel slug={company.slug} canEdit={canWrite} />
                    : <CompanyMembersPanel slug={company.slug} canEdit={canWrite} canRevoke={canWrite}
                        showExternalHolders={company.show_external_holders} />}
                </div>
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
