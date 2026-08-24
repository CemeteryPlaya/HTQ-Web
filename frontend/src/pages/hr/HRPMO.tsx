import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ReactFlowProvider } from '@xyflow/react';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { OrgChart } from '@/components/hr/OrgChart';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';
import { translatedMap } from '@/lib/i18n/translatedMap';
import { useTranslation } from 'react-i18next';

interface PMO { id: number; name: string; code: string; description: string | null; head_employee_id: number | null; status: string }
interface PMOMember { id: number; employee_id: number; employee_name: string; employee_email: string; primary_position: string | null; position_in_pmo: string | null; membership_type: string; allocation_percent: number; is_primary: boolean; from_date: string | null; to_date: string | null }
interface Employee { id: number; full_name: string; email: string }

const STATUS_LABELS: Record<string, string> = translatedMap({
  active: 'hr.pmo.status.active',
  suspended: 'hr.pmo.status.suspended',
  closed: 'hr.pmo.status.closed',
});
const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  suspended: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  closed: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};
const MEMBER_TYPE_LABELS: Record<string, string> = translatedMap({
  permanent: 'hr.pmo.memberType.permanent',
  assigned: 'hr.pmo.memberType.assigned',
  consulting: 'hr.pmo.memberType.consulting',
});

function PMOCard({ pmo, onSelect, selected }: { pmo: PMO; onSelect: () => void; selected: boolean }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left rounded-xl border p-4 transition-colors hover:border-primary/60 ${selected ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-sm">{pmo.name}</p>
          <p className="text-xs text-muted-foreground font-mono mt-0.5">{pmo.code}</p>
        </div>
        <span className={`text-xs rounded-full px-2 py-0.5 font-medium ${STATUS_COLORS[pmo.status] ?? ''}`}>
          {STATUS_LABELS[pmo.status] ?? pmo.status}
        </span>
      </div>
      {pmo.description && (
        <p className="text-xs text-muted-foreground mt-2 line-clamp-2">{pmo.description}</p>
      )}
    </button>
  );
}

const HRPMO = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [form, setForm] = useState({ name: '', code: '', description: '', status: 'active' });
  const [memberForm, setMemberForm] = useState({ employee_id: '', membership_type: 'permanent', position_in_pmo: '', allocation_percent: '100', is_primary: false });
  const [allocationWarning, setAllocationWarning] = useState<number | null>(null);

  const { data: pmos = [] } = useQuery<PMO[]>({
    queryKey: ['hr-pmos'],
    queryFn: async () => (await api.get('hr/v1/pmo/')).data,
  });

  const { data: members = [], isLoading: membersLoading } = useQuery<PMOMember[]>({
    queryKey: ['hr-pmo-members', selectedId],
    queryFn: async () => (await api.get(`hr/v1/pmo/${selectedId}/members`)).data,
    enabled: selectedId != null,
  });

  const { data: orgChart, isLoading: orgLoading } = useQuery({
    queryKey: ['hr-pmo-orgchart', selectedId],
    queryFn: async () => (await api.get(`hr/v1/pmo/${selectedId}/org-chart`)).data,
    enabled: selectedId != null,
  });

  const { data: employees = [] } = useQuery<Employee[]>({
    queryKey: ['hr-employees-list'],
    queryFn: async () => {
      const res = await api.get('hr/v1/employees/');
      return Array.isArray(res.data) ? res.data : res.data.results ?? [];
    },
  });

  const createMutation = useMutation({
    mutationFn: () => api.post('hr/v1/pmo/', form),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['hr-pmos'] }); setCreateOpen(false); setForm({ name: '', code: '', description: '', status: 'active' }); },
  });

  const addMemberMutation = useMutation({
    mutationFn: () => api.post(`hr/v1/pmo/${selectedId}/members`, {
      ...memberForm,
      employee_id: Number(memberForm.employee_id),
      allocation_percent: Number(memberForm.allocation_percent),
    }),
    onSuccess: (res) => {
      const warning = Number(res.headers?.['x-allocation-warning']);
      setAllocationWarning(Number.isFinite(warning) ? warning : null);
      queryClient.invalidateQueries({ queryKey: ['hr-pmo-members', selectedId] });
      queryClient.invalidateQueries({ queryKey: ['hr-pmo-orgchart', selectedId] });
      setAddMemberOpen(false);
      setMemberForm({ employee_id: '', membership_type: 'permanent', position_in_pmo: '', allocation_percent: '100', is_primary: false });
    },
  });

  const updateMemberMutation = useMutation({
    mutationFn: ({ memberId, patch }: { memberId: number; patch: Partial<PMOMember> }) => (
      api.patch(`hr/v1/pmo/${selectedId}/members/${memberId}`, patch)
    ),
    onSuccess: (res) => {
      const warning = Number(res.headers?.['x-allocation-warning']);
      setAllocationWarning(Number.isFinite(warning) ? warning : null);
      queryClient.invalidateQueries({ queryKey: ['hr-pmo-members', selectedId] });
      queryClient.invalidateQueries({ queryKey: ['hr-pmo-orgchart', selectedId] });
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: (memberId: number) => api.delete(`hr/v1/pmo/${selectedId}/members/${memberId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-pmo-members', selectedId] });
      queryClient.invalidateQueries({ queryKey: ['hr-pmo-orgchart', selectedId] });
    },
  });

  const selected = pmos.find((p) => p.id === selectedId);

  return (
    <HRLayout title={t('hr.pmo.title')} subtitle={t('hr.pmo.subtitle')}>
      <div className="flex gap-6 h-[calc(100vh-220px)] min-h-[600px]">
        {/* Left: PMO list */}
        <div className="w-72 flex-shrink-0 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">{t('hr.pmo.listCount', { count: pmos.length })}</span>
            {isSenior && (
              <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                <DialogTrigger asChild>
                  <Button size="sm">{t('hr.pmo.create')}</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader><DialogTitle>{t('hr.pmo.newTitle')}</DialogTitle></DialogHeader>
                  <div className="grid gap-3">
                    <label className="grid gap-1.5 text-sm">{t('hr.pmo.name')}<Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
                    <label className="grid gap-1.5 text-sm">{t('hr.pmo.code')}<Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="PMO-001" /></label>
                    <label className="grid gap-1.5 text-sm">{t('calendar.form.description')}<Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button>
                      <Button onClick={() => createMutation.mutate()} disabled={!form.name || !form.code || createMutation.isPending}>{t('common.create')}</Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
            )}
          </div>
          <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1">
            {pmos.map((p) => (
              <PMOCard key={p.id} pmo={p} selected={p.id === selectedId} onSelect={() => setSelectedId(p.id)} />
            ))}
            {pmos.length === 0 && (
              <div className="text-sm text-muted-foreground text-center py-8">{t('hr.pmo.empty')}</div>
            )}
          </div>
        </div>

        {/* Right: PMO details */}
        <div className="flex-1 min-w-0">
          {!selected ? (
            <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
              {t('hr.pmo.pickOne')}
            </div>
          ) : (
            <Tabs defaultValue="general" className="h-full flex flex-col">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-lg font-semibold">{selected.name}</h2>
                  <span className="text-xs font-mono text-muted-foreground">{selected.code}</span>
                </div>
                <TabsList>
                  <TabsTrigger value="general">{t('hr.pmo.tabGeneral')}</TabsTrigger>
                  <TabsTrigger value="members">{t('hr.pmo.tabMembers', { count: members.length })}</TabsTrigger>
                  <TabsTrigger value="chart">{t('hr.pmo.tabGraph')}</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="general" className="flex-1">
                <div className="rounded-xl border bg-card p-5 space-y-3">
                  <div><span className="text-sm text-muted-foreground">{t('hr.pmo.statusLabel')} </span>
                    <Badge className={`text-xs ${STATUS_COLORS[selected.status] ?? ''}`} variant="outline">
                      {STATUS_LABELS[selected.status] ?? selected.status}
                    </Badge>
                  </div>
                  {selected.description && <p className="text-sm">{selected.description}</p>}
                </div>
              </TabsContent>

              <TabsContent value="members" className="flex-1 overflow-y-auto">
                <div className="flex justify-end mb-3">
                  {isSenior && (
                    <Dialog open={addMemberOpen} onOpenChange={setAddMemberOpen}>
                      <DialogTrigger asChild>
                        <Button size="sm">{t('hr.pmo.addMemberShort')}</Button>
                      </DialogTrigger>
                      <DialogContent>
                        <DialogHeader><DialogTitle>{t('hr.pmo.addMember')}</DialogTitle></DialogHeader>
                        <div className="grid gap-3">
                          <label className="grid gap-1.5 text-sm">{t('hr.pmo.employee')}
                            <Select value={memberForm.employee_id} onValueChange={(v) => setMemberForm({ ...memberForm, employee_id: v })}>
                              <SelectTrigger><SelectValue placeholder={t('hr.pmo.pickEmployee')} /></SelectTrigger>
                              <SelectContent>
                                {employees.map((e: any) => <SelectItem key={e.id} value={String(e.id)}>{e.full_name ?? `${e.first_name} ${e.last_name}`}</SelectItem>)}
                              </SelectContent>
                            </Select>
                          </label>
                          <label className="grid gap-1.5 text-sm">{t('hr.pmo.membershipType')}
                            <Select value={memberForm.membership_type} onValueChange={(v) => setMemberForm({ ...memberForm, membership_type: v })}>
                              <SelectTrigger><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="permanent">{t('hr.pmo.memberType.permanent')}</SelectItem>
                                <SelectItem value="assigned">{t('hr.pmo.memberType.assigned')}</SelectItem>
                                <SelectItem value="consulting">{t('hr.pmo.memberType.consulting')}</SelectItem>
                              </SelectContent>
                            </Select>
                          </label>
                          <label className="grid gap-1.5 text-sm">{t('hr.pmo.roleInPmo')}<Input value={memberForm.position_in_pmo} onChange={(e) => setMemberForm({ ...memberForm, position_in_pmo: e.target.value })} placeholder={t('common.optional')} /></label>
                          <label className="grid gap-1.5 text-sm">{t('hr.pmo.allocationPercent')}
                            <Input
                              type="number"
                              min={0}
                              max={100}
                              value={memberForm.allocation_percent}
                              onChange={(e) => setMemberForm({ ...memberForm, allocation_percent: e.target.value })}
                            />
                          </label>
                          <label className="flex items-center gap-2 text-sm">
                            <Checkbox
                              checked={memberForm.is_primary}
                              onCheckedChange={(checked) => setMemberForm({ ...memberForm, is_primary: Boolean(checked) })}
                            />
                            {t('hr.pmo.makeLead')}
                          </label>
                          <div className="flex justify-end gap-2">
                            <Button variant="outline" onClick={() => setAddMemberOpen(false)}>{t('common.cancel')}</Button>
                            <Button onClick={() => addMemberMutation.mutate()} disabled={!memberForm.employee_id || addMemberMutation.isPending}>{t('common.add')}</Button>
                          </div>
                        </div>
                      </DialogContent>
                    </Dialog>
                  )}
                </div>
                {allocationWarning != null && allocationWarning > 100 && (
                  <Alert className="mb-3 border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
                    <AlertDescription>
                      {t('hr.pmo.allocationWarning', { percent: allocationWarning })}
                    </AlertDescription>
                  </Alert>
                )}
                {membersLoading ? (
                  <div className="text-sm text-muted-foreground text-center py-8">{t('signoff.loadingEllipsis')}</div>
                ) : members.length === 0 ? (
                  <div className="text-sm text-muted-foreground text-center py-8">{t('hr.pmo.noMembers')}</div>
                ) : (
                  <div className="space-y-2">
                    {members.map((m) => (
                      <div key={`${m.id}-${m.allocation_percent}-${m.is_primary}`} className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="font-medium text-sm truncate">{m.employee_name}</p>
                            {m.is_primary && <Badge className="text-xs" variant="outline">{t('profile.pmoLead')}</Badge>}
                          </div>
                          <p className="text-xs text-muted-foreground">{m.position_in_pmo || m.primary_position || '—'}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            min={0}
                            max={100}
                            defaultValue={m.allocation_percent}
                            className="h-8 w-20"
                            onBlur={(event) => {
                              const next = Number(event.currentTarget.value);
                              if (!Number.isNaN(next) && next !== m.allocation_percent) {
                                updateMemberMutation.mutate({ memberId: m.id, patch: { allocation_percent: next } });
                              }
                            }}
                            disabled={!isSenior || updateMemberMutation.isPending}
                          />
                          <span className="text-xs text-muted-foreground">%</span>
                        </div>
                        {isSenior && (
                          <label className="flex items-center gap-2 text-xs text-muted-foreground">
                            <Checkbox
                              checked={m.is_primary}
                              onCheckedChange={(checked) => updateMemberMutation.mutate({
                                memberId: m.id,
                                patch: { is_primary: Boolean(checked) },
                              })}
                              disabled={updateMemberMutation.isPending}
                            />
                            {t('profile.pmoLead')}
                          </label>
                        )}
                        <Badge variant="outline" className="text-xs shrink-0">{MEMBER_TYPE_LABELS[m.membership_type] ?? m.membership_type}</Badge>
                        {isSenior && (
                          <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive shrink-0" onClick={() => removeMemberMutation.mutate(m.id)}>×</Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="chart" className="flex-1">
                <div className="h-[calc(100%-40px)]">
                  <ReactFlowProvider>
                    <OrgChart
                      rawNodes={orgChart?.nodes ?? []}
                      rawEdges={orgChart?.edges ?? []}
                      isLoading={orgLoading}
                    />
                  </ReactFlowProvider>
                </div>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </div>
    </HRLayout>
  );
};

export default HRPMO;
