/**
 * «Статьи бюджета» (ТЗ §18): группы статей и сами статьи.
 *
 * Группа несёт `node_key` — узел реестра прав, открывающий её статьи
 * (BR-010, роли `bpp-*`): от него зависит, кто какую статью видит в
 * бюджете и заявке, поэтому после создания он не правится (PATCH-схема
 * группы его не принимает), как и код. У статьи то же с группой и
 * родителем: перенос статьи между группами поменял бы круг ролей у уже
 * утверждённых бюджетов.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { refdataApi, refdataKeys, type Article, type ArticleGroup } from './api';
import { ArchivableTable } from './ArchivableTable';
import { optionalValue, type RefField } from './refFields';
import { useActiveRefdata, useRefdataList } from './useRefdataList';

export default function ArticlesTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const groups = useRefdataList('articleGroups');
  const articles = useRefdataList('articles');
  // Для НОВОЙ статьи — только действующие группа и родитель.
  const { data: activeGroups } = useActiveRefdata('articleGroups');
  const { data: activeArticles } = useActiveRefdata('articles');

  const groupName = new Map((groups.data ?? []).map((g) => [g.id, g.name]));
  const articleLabel = new Map((articles.data ?? []).map((a) => [a.id, `${a.code} ${a.name}`]));

  const groupFields: RefField<ArticleGroup>[] = [
    { key: 'code', label: t('bpp.refdata.articleGroups.code', 'Код'), editable: false, maxLength: 32 },
    { key: 'name', label: t('bpp.refdata.articleGroups.name', 'Наименование'), maxLength: 128 },
    {
      key: 'node_key', label: t('bpp.refdata.articleGroups.nodeKey', 'Узел прав'),
      editable: false, maxLength: 128,
      render: (row) => <code className="text-xs">{row.node_key}</code>,
    },
  ];

  const articleFields: RefField<Article>[] = [
    { key: 'code', label: t('bpp.refdata.articles.code', 'Код'), editable: false, maxLength: 32 },
    { key: 'name', label: t('bpp.refdata.articles.name', 'Наименование'), maxLength: 255 },
    {
      key: 'group_id', label: t('bpp.refdata.articles.group', 'Группа'), editable: false,
      options: (activeGroups ?? []).map((g) => ({ value: g.id, label: g.name })),
      render: (row) => groupName.get(row.group_id) ?? '—',
    },
    {
      key: 'parent_id', label: t('bpp.refdata.articles.parent', 'Родительская статья'),
      editable: false, optional: true,
      options: (activeArticles ?? []).map((a) => ({ value: a.id, label: `${a.code} ${a.name}` })),
      render: (row) => (row.parent_id ? articleLabel.get(row.parent_id) ?? '—' : '—'),
    },
    {
      key: 'ext_1c_ref', label: t('bpp.refdata.articles.ext1c', 'Код в 1С'),
      optional: true, maxLength: 64,
    },
  ];

  return (
    <div className="space-y-8">
      <ArchivableTable
        title={t('bpp.refdata.articleGroups.title', 'Группы статей')}
        rows={groups.data}
        isLoading={groups.isLoading}
        fields={groupFields}
        onCreate={(values) => refdataApi.articleGroups.create({
          code: values.code.trim(), name: values.name.trim(), node_key: values.node_key.trim(),
        })}
        onPatch={(id, values) => refdataApi.articleGroups.patch(id, { name: values.name.trim() })}
        onToggleActive={(row, is_active) => refdataApi.articleGroups.patch(row.id, { is_active })}
        onChanged={() => queryClient.invalidateQueries({
          queryKey: refdataKeys.collection('articleGroups'),
        })}
      />
      <ArchivableTable
        title={t('bpp.refdata.articles.title', 'Статьи')}
        rows={articles.data}
        isLoading={articles.isLoading}
        fields={articleFields}
        onCreate={(values) => refdataApi.articles.create({
          code: values.code.trim(),
          name: values.name.trim(),
          group_id: values.group_id,
          parent_id: optionalValue(values.parent_id),
          ext_1c_ref: optionalValue(values.ext_1c_ref) ?? '',
        })}
        onPatch={(id, values) => refdataApi.articles.patch(id, {
          name: values.name.trim(), ext_1c_ref: (values.ext_1c_ref ?? '').trim(),
        })}
        onToggleActive={(row, is_active) => refdataApi.articles.patch(row.id, { is_active })}
        onChanged={() => queryClient.invalidateQueries({ queryKey: refdataKeys.collection('articles') })}
      />
    </div>
  );
}
