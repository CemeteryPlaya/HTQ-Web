/** /requests/templates/:id/editor — Lark-style 4-step template builder:
 *  1 Basic Info · 2 Form Design · 3 Process Design · 4 More, with Preview +
 *  Publish. Basic Info autosaves (debounced) to the template; Form/Process are
 *  published as an immutable version. */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, Eye, Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { BasicInfoStep, type BasicInfoValue } from '@/features/requests/components/BasicInfoStep';
import { FormBuilder } from '@/features/requests/components/FormBuilder';
import { MoreStep } from '@/features/requests/components/MoreStep';
import { FormRenderer } from '@/features/requests/components/FormRenderer';
import { WorkflowBuilder } from '@/features/requests/components/WorkflowBuilder';
import { QK, useTemplate, useTemplateVersion } from '@/features/requests/hooks';
import type { FormSchema, WorkflowGraph } from '@/features/requests/types';

const EMPTY_SCHEMA: FormSchema = { fields: [] };
const EMPTY_WF: WorkflowGraph = {
  nodes: [{ id: 'n_start', type: 'start' }, { id: 'n_end', type: 'end_approved' }],
  edges: [{ from: 'n_start', to: 'n_end' }],
};

const STEPS = [
  { key: 'basic', label: 'Основное' },
  { key: 'form', label: 'Дизайн формы' },
  { key: 'process', label: 'Процесс' },
  { key: 'more', label: 'Прочее' },
] as const;
type StepKey = (typeof STEPS)[number]['key'];

export default function TemplateEditorPage() {
  const { id } = useParams<{ id: string }>();
  const templateId = id ? parseInt(id, 10) : NaN;
  const tpl = useTemplate(Number.isNaN(templateId) ? null : templateId);
  const currentVersion = useTemplateVersion(
    Number.isNaN(templateId) ? null : templateId,
    tpl.data?.current_version_id ?? null,
  );

  const [step, setStep] = useState<StepKey>('basic');
  const [basic, setBasic] = useState<BasicInfoValue | null>(null);
  const [schema, setSchema] = useState<FormSchema>(EMPTY_SCHEMA);
  const [workflow, setWorkflow] = useState<WorkflowGraph>(EMPTY_WF);
  const [preview, setPreview] = useState(false);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle');

  const savedRef = useRef<string>('');

  // Hydrate Basic Info once the template loads.
  useEffect(() => {
    if (!tpl.data) return;
    const v: BasicInfoValue = {
      name: tpl.data.name,
      description: tpl.data.description,
      icon: tpl.data.icon || 'file',
      color: tpl.data.color || '#3b82f6',
      config: tpl.data.config_json ?? {},
    };
    setBasic(v);
    savedRef.current = JSON.stringify(v);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tpl.data?.id]);

  // Hydrate form + workflow from the published version.
  useEffect(() => {
    if (currentVersion.data) {
      setSchema(currentVersion.data.schema_json ?? EMPTY_SCHEMA);
      setWorkflow(currentVersion.data.workflow_json ?? EMPTY_WF);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentVersion.data?.id]);

  // Debounced autosave of Basic Info.
  useEffect(() => {
    if (!basic) return;
    const snap = JSON.stringify(basic);
    if (snap === savedRef.current) return;
    setSaveState('saving');
    const t = setTimeout(async () => {
      try {
        await requestsApi.templates.update(templateId, {
          name: basic.name,
          description: basic.description,
          icon: basic.icon,
          color: basic.color,
          config_json: basic.config,
        } as any);
        savedRef.current = snap;
        setSaveState('saved');
      } catch (e: any) {
        setSaveState('idle');
        toast.error(e?.response?.data?.detail ?? 'Не удалось сохранить');
      }
    }, 800);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basic]);

  const qc = useQueryClient();
  const publish = useMutation({
    mutationFn: () => requestsApi.templates.publishVersion(templateId, schema, workflow),
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: QK.template(templateId) });
      toast.success(`Опубликована версия #${v.version}`);
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail ?? e?.message ?? 'Не удалось опубликовать';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    },
  });

  if (Number.isNaN(templateId)) {
    return <RequestsLayout title="Шаблон не найден"><Card><CardContent className="py-6 text-sm text-destructive">Некорректный идентификатор.</CardContent></Card></RequestsLayout>;
  }
  if (tpl.isLoading || !basic) {
    return <RequestsLayout title="Загрузка…"><Skeleton className="h-32" /><Skeleton className="h-80" /></RequestsLayout>;
  }
  if (tpl.error || !tpl.data) {
    return <RequestsLayout title="Шаблон не найден"><Card><CardContent className="py-6 text-sm text-destructive">Шаблон не найден или нет доступа.</CardContent></Card></RequestsLayout>;
  }

  const patchBasic = (p: Partial<BasicInfoValue>) => setBasic((b) => (b ? { ...b, ...p } : b));

  return (
    <RequestsLayout
      title={basic.name || 'Конструктор шаблона'}
      subtitle={
        saveState === 'saving' ? 'Сохранение…'
        : saveState === 'saved' ? 'Сохранено'
        : `slug «${tpl.data.slug}»`
      }
      actions={
        <>
          {tpl.data.current_version_id == null && (
            <Badge variant="outline" className="bg-amber-100 text-amber-800 hover:bg-amber-100">черновик</Badge>
          )}
          <Button variant="outline" onClick={() => setPreview(true)}>
            <Eye className="mr-2 h-4 w-4" /> Превью
          </Button>
          <Button disabled={publish.isPending} onClick={() => publish.mutate()}>
            {publish.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Опубликовать
          </Button>
        </>
      }
    >
      {/* Step bar */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card/70 p-2">
        {STEPS.map((s, i) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setStep(s.key)}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${step === s.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
          >
            <span className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${step === s.key ? 'bg-primary-foreground/20' : 'bg-muted-foreground/20'}`}>{i + 1}</span>
            {s.label}
          </button>
        ))}
        {saveState === 'saved' && (
          <span className="ml-auto flex items-center gap-1 pr-2 text-xs text-emerald-600"><Check className="h-3.5 w-3.5" /> автосохранено</span>
        )}
      </div>

      <Card>
        <CardContent className="py-6">
          {step === 'basic' && <BasicInfoStep value={basic} onChange={patchBasic} createdBy={tpl.data.created_by} />}
          {step === 'form' && <FormBuilder schema={schema} onChange={setSchema} />}
          {step === 'process' && <WorkflowBuilder graph={workflow} onChange={setWorkflow} />}
          {step === 'more' && (
            <MoreStep
              value={basic.config.settings ?? {}}
              onChange={(patch) => patchBasic({ config: { ...basic.config, settings: { ...(basic.config.settings ?? {}), ...patch } } })}
            />
          )}
        </CardContent>
      </Card>

      <Dialog open={preview} onOpenChange={setPreview}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader><DialogTitle>Превью формы · {basic.name}</DialogTitle></DialogHeader>
          <FormRenderer schema={schema} values={{}} onChange={() => {}} readOnly />
        </DialogContent>
      </Dialog>
    </RequestsLayout>
  );
}
