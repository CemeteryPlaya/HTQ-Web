/** /requests/projects — admin CRUD over projects + per-project member mgmt. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { QK, useProjects } from '@/features/requests/hooks';
import type { Project, ProjectMember, ProjectMemberRole } from '@/features/requests/types';

function CreateProjectForm({ onCreated }: { onCreated: (p: Project) => void }) {
  const [name, setName] = useState('');
  const [budget, setBudget] = useState('');
  const [busy, setBusy] = useState(false);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Создать проект</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (!name.trim()) return;
            setBusy(true);
            try {
              const p = await requestsApi.projects.create({
                name: name.trim(),
                budget_limit: budget ? Number(budget) : null,
              });
              onCreated(p);
              setName('');
              setBudget('');
              toast.success(`Проект «${p.name}» создан`);
            } catch (e: any) {
              toast.error(e?.response?.data?.detail ?? 'Не удалось создать проект');
            } finally {
              setBusy(false);
            }
          }}
          className="grid gap-4 sm:grid-cols-[1fr_180px_auto] sm:items-end"
        >
          <div className="space-y-1.5">
            <Label htmlFor="proj-name">Название</Label>
            <Input id="proj-name" value={name} onChange={(e) => setName(e.target.value)} required placeholder="Q4 expansion" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="proj-budget">Бюджет (KZT)</Label>
            <Input
              id="proj-budget"
              type="number"
              min={0}
              step="0.01"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="1000000"
            />
          </div>
          <Button type="submit" disabled={busy || !name.trim()}>
            Создать проект
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function MembersPanel({ project }: { project: Project }) {
  const qc = useQueryClient();
  const membersKey = ['requests', 'projects', project.id, 'members'];
  const members = useQuery({
    queryKey: membersKey,
    queryFn: () => requestsApi.projects.listMembers(project.id),
  });
  const [userId, setUserId] = useState('');
  const [role, setRole] = useState<ProjectMemberRole>('member');

  const add = useMutation({
    mutationFn: () => requestsApi.projects.addMember(project.id, Number(userId), role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: membersKey });
      setUserId('');
      toast.success('Участник добавлен');
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Не удалось добавить'),
  });
  const remove = useMutation({
    mutationFn: (uid: number) => requestsApi.projects.removeMember(project.id, uid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: membersKey });
      toast.success('Удалено');
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? 'Не удалось удалить'),
  });

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[150px_160px_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label htmlFor={`uid-${project.id}`}>user_id</Label>
          <Input
            id={`uid-${project.id}`}
            type="number"
            min={1}
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="42"
          />
        </div>
        <div className="space-y-1.5">
          <Label>Роль</Label>
          <Select value={role} onValueChange={(v) => setRole(v as ProjectMemberRole)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="admin">admin</SelectItem>
              <SelectItem value="member">member</SelectItem>
              <SelectItem value="viewer">viewer</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button
          disabled={!userId || add.isPending}
          onClick={() => add.mutate()}
          className="bg-emerald-600 hover:bg-emerald-700"
        >
          Добавить
        </Button>
      </div>

      {members.isLoading && <Skeleton className="h-12" />}
      {members.data && members.data.length === 0 && (
        <p className="text-sm text-muted-foreground">Участников пока нет.</p>
      )}
      {members.data && members.data.length > 0 && (
        <ul className="divide-y rounded-md border">
          {members.data.map((m: ProjectMember) => (
            <li key={m.user_id} className="flex items-center justify-between px-3 py-2 text-sm">
              <span>
                user #{m.user_id} · <Badge variant="secondary">{m.role}</Badge>
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => remove.mutate(m.user_id)}
                className="text-destructive hover:text-destructive"
              >
                <X className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ProjectsPage() {
  const qc = useQueryClient();
  const projects = useProjects();
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <RequestsLayout title="Проекты" subtitle="Заглушка проектов для шаблонов и финансовой статистики">
      <CreateProjectForm onCreated={() => qc.invalidateQueries({ queryKey: QK.projects })} />

      <Card>
        <CardContent className="p-0">
          {projects.isLoading && (
            <div className="space-y-2 p-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          )}
          {projects.data && projects.data.length === 0 && (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              Проектов пока нет.
            </div>
          )}
          {projects.data?.map((p) => {
            const open = expanded === p.id;
            return (
              <div key={p.id} className="border-b last:border-b-0">
                <button
                  type="button"
                  onClick={() => setExpanded(open ? null : p.id)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-muted/40"
                >
                  <div>
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-muted-foreground">
                      <Badge variant="outline" className="mr-2">{p.status}</Badge>
                      бюджет {p.budget_limit ?? '—'} {p.currency}
                    </div>
                  </div>
                  {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                </button>
                {open && (
                  <div className="border-t bg-muted/30 px-4 py-4">
                    <MembersPanel project={p} />
                  </div>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>
    </RequestsLayout>
  );
}
