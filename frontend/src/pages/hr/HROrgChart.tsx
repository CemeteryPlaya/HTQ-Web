import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ReactFlowProvider } from '@xyflow/react';
import { Info, Pencil, Search, Share2, Sparkles } from 'lucide-react';
import { toast } from 'sonner';

import api from '@/api/client';
import { fetchOrgTree, type OrgTree, type RelationType } from '@/api/hr';
import HRLayout from '@/components/hr/HRLayout';
import { EmployeeDetailDrawer } from '@/components/hr/EmployeeDetailDrawer';
import { OrgChart, type OrgRawNode } from '@/components/hr/OrgChart';
import { ExternalHierarchy } from '@/components/hr/OrgChart/ExternalHierarchy';
import { HierarchySwitch, type HierarchyKind } from '@/components/hr/OrgChart/HierarchySwitch';
import { OrgEditPanel } from '@/components/hr/OrgChart/OrgEditPanel';
import { useOrgEditMutations } from '@/components/hr/OrgChart/useOrgEditMutations';
import { EntityCombobox, type EntityOption } from '@/components/hr/OrgChart/EntityCombobox';
import { ShareOrgDialog } from '@/components/hr/ShareOrgDialog';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { useHRLevel } from '@/hooks/useHRLevel';
import { useTranslation } from 'react-i18next';

type Mode = 'positions' | 'employees' | 'both';
type OrgLanguage = 'ru' | 'en';

interface Department { id: number; name: string }

const HROrgChart = () => {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>('positions');
  const [rootId, setRootId] = useState<string>('all');
  const [depth, setDepth] = useState(5);
  const [language, setLanguage] = useState<OrgLanguage>('ru');
  const [selected, setSelected] = useState<OrgRawNode | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  // Правило 4 стадии 2: иерархий две. Внешняя вычисляется из дерева компаний
  // и потому только для чтения — правка в ней невозможна по построению.
  const [hierarchy, setHierarchy] = useState<HierarchyKind>('internal');

  const { isSeniorOrAbove, isLoading: levelLoading } = useHRLevel();
  const canEdit = isSeniorOrAbove && !levelLoading;
  const editable = editMode && canEdit && mode !== 'both' && hierarchy === 'internal';

  useEffect(() => {
    if (editMode && mode === 'both') {
      toast.info(t('hr.orgChartPage.editModeHint'));
    }
  }, [editMode, mode, t]);

  const queryClient = useQueryClient();

  const { data: departments } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: async () => {
      const res = await api.get<Department[]>('hr/v1/departments/');
      return Array.isArray(res.data) ? res.data : (res.data as any).results ?? [];
    },
  });

  const treeKey = useMemo(
    () => ['org-tree', mode, rootId, depth, language] as const,
    [mode, rootId, depth, language],
  );

  const { data: treeData, isLoading, error } = useQuery({
    queryKey: treeKey,
    queryFn: () => fetchOrgTree({ mode, depth, lang: language, rootId }),
  });

  const mutations = useOrgEditMutations(treeKey);

  const handleConnectNodes = (
    sourceId: string,
    targetId: string,
    relationType?: RelationType,
    note?: string,
  ) => {
    // When called from ConnectDialog, confirmation is already handled
    mutations.connectSuperior(sourceId, targetId, relationType || 'direct', note, true);
  };

  const currentTree = queryClient.getQueryData<OrgTree>(treeKey) ?? treeData;
  const selectedLive = selected
    ? (currentTree?.nodes.find((n) => n.id === selected.id) as OrgRawNode | undefined) ?? selected
    : null;

  // Search options for quick finder in toolbar
  const searchOptions: EntityOption[] = useMemo(() => {
    return (currentTree?.nodes ?? []).map((n) => {
      const numId = Number(n.id.split('_').pop()) || 0;
      return {
        id: numId,
        label: n.label,
        subLabel: (n.meta?.department_name as string) || (n.meta?.position_title as string) || undefined,
        departmentName: (n.meta?.department_name as string) || undefined,
        avatarUrl: (n.meta?.avatar_url as string) || (n.meta?.holder_avatar_url as string) || undefined,
        level: (n.level as number) || undefined,
        type: n.type === 'employee' ? 'employee' : 'position',
      };
    });
  }, [currentTree]);

  const handleQuickSelect = (idStr: string) => {
    if (!idStr) return;
    const targetNode = currentTree?.nodes.find(
      (n) => n.id.endsWith(`_${idStr}`) || n.id === idStr,
    );
    if (targetNode) {
      setSelected(targetNode);
    }
  };

  return (
    <HRLayout
      title={t('hr.orgChartPage.title')}
      subtitle={t('hr.orgChartPage.subtitle')}
    >
      {/* Edit mode active indicator banner */}
      {editable && (
        <div className="mb-3 flex items-center justify-between gap-2 rounded-xl border border-sky-300/80 bg-sky-50/80 px-4 py-2 text-xs text-sky-900 shadow-xs dark:border-sky-800/80 dark:bg-sky-950/40 dark:text-sky-200 animate-in fade-in">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-sky-600 dark:text-sky-400 shrink-0" />
            <span>
              <strong>{t('hr.orgChartPage.editModeOn')}</strong> {t('hr.orgChartPage.editModeHelp')}
            </span>
          </div>
          <Badge variant="outline" className="bg-white/80 dark:bg-neutral-900/80 text-[10px] shrink-0 font-medium">
            {t('hr.orgChartPage.rightsConfirmed')}
          </Badge>
        </div>
      )}

      {/* Filters & Actions bar */}
      <div className="flex flex-wrap items-center gap-2.5 mb-4">
        <div className="flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground text-xs font-medium">{t('hr.orgChartPage.departmentLabel')}</span>
          <Select value={rootId} onValueChange={setRootId}>
            <SelectTrigger className="h-8 w-40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('hr.orgChartPage.wholeCompany')}</SelectItem>
              {departments?.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground text-xs font-medium">{t('hr.orgChartPage.showLabel')}</span>
          <Select value={mode} onValueChange={(v) => setMode(v as Mode)}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="positions">{t('hr.orgChartPage.positions')}</SelectItem>
              <SelectItem value="employees">{t('hr.nav.employees')}</SelectItem>
              <SelectItem value="both">{t('hr.orgChartPage.both')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground text-xs font-medium">{t('hr.orgChartPage.levelsLabel')}</span>
          <Select value={String(depth)} onValueChange={(v) => setDepth(parseInt(v))}>
            <SelectTrigger className="h-8 w-20 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[2, 3, 4, 5, 7, 10].map((d) => (
                <SelectItem key={d} value={String(d)}>{d}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground text-xs font-medium">{t('hr.orgChartPage.languageLabel')}</span>
          <Select value={language} onValueChange={(v) => setLanguage(v as OrgLanguage)}>
            <SelectTrigger className="h-8 w-20 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ru">RU</SelectItem>
              <SelectItem value="en">EN</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Quick Node Finder in current tree */}
        <div className="w-52 hidden lg:block">
          <EntityCombobox
            mode="single"
            value=""
            onChange={handleQuickSelect}
            options={searchOptions}
            placeholder={t('hr.orgChartPage.findOnChart')}
            searchPlaceholder={t('hr.orgChartPage.searchNode')}
            className="h-8 text-xs bg-background/90"
          />
        </div>

        <HierarchySwitch value={hierarchy} onChange={setHierarchy} />

        {canEdit && hierarchy === 'internal' && (
          <div className="flex items-center gap-1.5 text-xs font-medium rounded-lg border bg-muted/30 px-2.5 py-1">
            <Pencil className="h-3.5 w-3.5 text-primary" />
            <span className="text-foreground">{t('hr.orgChartPage.editLabel')}</span>
            <Switch checked={editMode} onCheckedChange={setEditMode} className="scale-90" />
          </div>
        )}

        <Button
          size="sm"
          variant="default"
          className="ml-auto gap-1.5 h-8 text-xs shadow-xs"
          onClick={() => setShareOpen(true)}
        >
          <Share2 className="h-3.5 w-3.5" />
          {t('common.share')}
        </Button>
      </div>

      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-xs text-destructive mb-4">
          {t('hr.orgChartPage.loadError')}
        </div>
      )}

      {/* Самое вероятное расхождение ожиданий с заказчиком: связь на дереве
          читается как передача прав. Закрывается подписью в интерфейсе, а не
          абзацем в документации, и стоит в ОБОИХ режимах — с внешней
          иерархией ожидание сильнее, чем с внутренней. */}
      <p className="mb-2 text-xs text-muted-foreground">
        {t(
          'access.hierarchy.subordinationNote',
          'Связь на дереве означает подчинение, а не передачу прав: начальник не '
          + 'получает права подчинённого автоматически — они приходят ролями его '
          + 'должности.',
        )}
      </p>

      <div className="h-[calc(100vh-270px)] min-h-[500px]">
        {hierarchy === 'external' ? <ExternalHierarchy /> : (
        <ReactFlowProvider>
          <OrgChart
            rawNodes={treeData?.nodes ?? []}
            rawEdges={treeData?.edges ?? []}
            isLoading={isLoading}
            onNodeClick={setSelected}
            editable={editable}
            onConnectNodes={handleConnectNodes}
          />
        </ReactFlowProvider>
        )}
      </div>

      {editable ? (
        <OrgEditPanel
          node={selectedLive}
          tree={currentTree}
          onClose={() => setSelected(null)}
          onSelectNode={(nodeId) => {
            const found = currentTree?.nodes.find((n) => n.id === nodeId);
            if (found) setSelected(found);
          }}
          mutations={mutations}
        />
      ) : (
        <EmployeeDetailDrawer
          node={selected}
          mode="auth"
          onClose={() => setSelected(null)}
        />
      )}

      <ShareOrgDialog
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        defaultLanguage={language}
      />
    </HRLayout>
  );
};

export default HROrgChart;
