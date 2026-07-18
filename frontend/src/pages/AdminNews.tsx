import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Calendar, ImagePlus, Trash2, Eye, Plus } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import api from '@/api/client';
import { cmsApi } from '@/api/cms';
import { API_ENDPOINTS } from '@/api/endpoints';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { NewsEditor } from '@/components/news/NewsEditor';
import { TagsMultiSelect } from '@/components/news/TagsMultiSelect';
import type { NewsItem, NewsStatus, NewsWritePayload } from '@/types/news';

const STATUS_LABELS: Record<NewsStatus, { label: string; tone: string; ring: string }> = {
  draft: { label: 'Черновик', tone: 'bg-muted text-muted-foreground border-transparent', ring: 'focus-visible:ring-muted' },
  scheduled: { label: 'Запланировано', tone: 'bg-amber-500/10 text-amber-600 border-amber-500/20 dark:bg-amber-500/20 dark:text-amber-400', ring: 'focus-visible:ring-amber-500' },
  published: { label: 'Опубликовано', tone: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-400', ring: 'focus-visible:ring-emerald-500' },
  archived: { label: 'В архиве', tone: 'bg-zinc-500/10 text-zinc-600 border-zinc-500/20 dark:bg-zinc-500/20 dark:text-zinc-400', ring: 'focus-visible:ring-zinc-500' },
};

interface FormState {
  title: string;
  slug: string;
  excerpt: string;
  content: string;
  imageUrl: string | null;
  imageFile: File | null;
  category_id: number | null;
  tag_ids: number[];
  status: NewsStatus;
  scheduled_at: string;
}

const EMPTY_FORM: FormState = {
  title: '',
  slug: '',
  excerpt: '',
  content: '',
  imageUrl: null,
  imageFile: null,
  category_id: null,
  tag_ids: [],
  // Default to "publish immediately" so new entries appear on /news right
  // away. Authors can still pick "Черновик" / "Запланировать публикацию"
  // before saving if they don't want it live yet.
  status: 'published',
  scheduled_at: '',
};

function slugify(title: string): string {
  // Latin-only slug; users may override. For Cyrillic, the backend allows
  // anything ≤320 chars unique — the user can type a custom slug.
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const tzOffset = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - tzOffset).toISOString().slice(0, 16);
}

function fromLocalInput(local: string): string | null {
  if (!local) return null;
  return new Date(local).toISOString();
}

const AdminNews = () => {
  const qc = useQueryClient();
  const { t } = useTranslation();

  const [statusFilter, setStatusFilter] = useState<'all' | NewsStatus>('all');
  const [search, setSearch] = useState('');
  const [page] = useState(1);

  const [editing, setEditing] = useState<NewsItem | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  // Fetch -----------------------------------------------------------------
  const { data: pageData, isLoading } = useQuery({
    queryKey: ['admin', 'news', { statusFilter, search, page }],
    queryFn: () =>
      cmsApi
        .listNews({
          page,
          page_size: 100,
          status: statusFilter === 'all' ? undefined : statusFilter,
          q: search.trim() || undefined,
        })
        .then((r) => r.data),
  });

  const { data: categories = [] } = useQuery({
    queryKey: ['cms', 'categories'],
    // Swallow 404 (taxonomy endpoint not deployed yet) so the form still
    // opens and the console isn't spammed by react-query retries.
    queryFn: () =>
      cmsApi.listCategories().then((r) => r.data).catch((err) => {
        if (err?.response?.status === 404) return [];
        throw err;
      }),
    staleTime: 60_000,
    retry: false,
  });

  const newsList = pageData?.items ?? [];
  const counts = useMemo(() => {
    const byStatus = { draft: 0, scheduled: 0, published: 0, archived: 0 } as Record<
      NewsStatus,
      number
    >;
    newsList.forEach((n) => {
      byStatus[n.status] = (byStatus[n.status] ?? 0) + 1;
    });
    return byStatus;
  }, [newsList]);

  // Mutations -------------------------------------------------------------
  const deleteMutation = useMutation({
    mutationFn: (id: number) => cmsApi.deleteNews(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'news'] });
      qc.invalidateQueries({ queryKey: ['news'] });
      toast.success('Новость удалена');
    },
    onError: () => toast.error('Не удалось удалить новость'),
  });

  // Form handlers ---------------------------------------------------------
  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (item: NewsItem) => {
    setEditing(item);
    setForm({
      title: item.title,
      slug: item.slug,
      excerpt: item.excerpt || '',
      content: item.content || '',
      imageUrl: item.image,
      imageFile: null,
      category_id: item.category_id,
      tag_ids: item.tags.map((t) => t.id),
      status: item.status,
      scheduled_at: toLocalInput(item.scheduled_at),
    });
    setDialogOpen(true);
  };

  const onTitleBlur = () => {
    if (!form.slug && form.title) setForm((f) => ({ ...f, slug: slugify(f.title) }));
  };

  // Live preview URL for the chosen file
  useEffect(() => {
    if (!form.imageFile) return;
    const url = URL.createObjectURL(form.imageFile);
    setForm((f) => ({ ...f, imageUrl: url }));
    return () => URL.revokeObjectURL(url);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.imageFile]);

  const save = async () => {
    if (!form.title || !form.slug) {
      toast.error('Укажите заголовок и slug');
      return;
    }
    if (form.status === 'scheduled' && !form.scheduled_at) {
      toast.error('Для статуса «Запланировано» укажите дату публикации');
      return;
    }
    setSaving(true);
    try {
      // Upload cover image if a new File was selected.
      let imageUrl: string | null | undefined = form.imageUrl;
      if (form.imageFile) {
        const fd = new FormData();
        fd.append('file', form.imageFile);
        // scope=news drives the media-service ScopePolicy: forces is_public=true
        // (so <img src> works without an Authorization header) and produces the
        // thumb_256 / preview_1024 variants. Without scope the file lands as
        // generic/private and the browser gets 401 on render.
        fd.append('scope', 'news');
        const upload = await api.post<{ url?: string; path?: string }>(
          `${API_ENDPOINTS.mediaFiles}/`,
          fd,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        );
        imageUrl = upload.data.url || upload.data.path || null;
      }

      const payload: NewsWritePayload = {
        title: form.title,
        slug: form.slug,
        excerpt: form.excerpt,
        content: form.content,
        image: imageUrl,
        category_id: form.category_id,
        tag_ids: form.tag_ids,
        status: form.status,
        scheduled_at:
          form.status === 'scheduled' ? fromLocalInput(form.scheduled_at) : null,
      };

      if (editing) {
        await cmsApi.updateNews(editing.id, payload);
        toast.success('Изменения сохранены');
      } else {
        await cmsApi.createNews(payload);
        toast.success('Новость создана');
      }
      qc.invalidateQueries({ queryKey: ['admin', 'news'] });
      qc.invalidateQueries({ queryKey: ['news'] });
      setDialogOpen(false);
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || err?.message;
      if (status === 401) toast.error('Неавторизован — выполните вход');
      else if (status === 403) toast.error('Нужны права администратора');
      else if (status === 409) toast.error(`Конфликт: ${detail}`);
      else toast.error(`Ошибка: ${detail || 'unknown'}`);
    } finally {
      setSaving(false);
    }
  };

  // Render ----------------------------------------------------------------
  return (
    <div className="min-h-screen flex flex-col bg-background relative overflow-hidden">
      {/* Decorative Background Elements */}
      <div className="pointer-events-none absolute left-0 top-0 -z-10 h-[600px] w-[600px] -translate-x-1/3 -translate-y-1/3 rounded-full bg-primary/5 blur-[120px] dark:bg-primary/10" />
      <div className="pointer-events-none absolute right-0 top-1/2 -z-10 h-[500px] w-[500px] translate-x-1/3 rounded-full bg-secondary/5 blur-[100px] dark:bg-secondary/10" />

      <Header />
      <main className="container-custom flex-1 py-10 pb-24 relative z-10">
        <Link
          to="/myprofile"
          className="group mb-8 inline-flex items-center gap-2 rounded-full bg-muted/50 px-4 py-2 text-sm font-medium text-muted-foreground backdrop-blur-sm transition-all hover:bg-primary/10 hover:text-primary animate-fade-in-up"
        >
          <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-1" />
          {t('hr.backToMain', 'Назад в профиль')}
        </Link>

        {/* Title row */}
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between animate-fade-in-up" style={{ animationDelay: '50ms' }}>
          <div>
            <div className="mb-2 inline-block rounded-full bg-primary/10 px-3 py-1 text-xs font-bold uppercase tracking-widest text-primary">
              C M S
            </div>
            <h1 className="font-display text-3xl font-extrabold tracking-tight text-foreground sm:text-4xl md:text-5xl">
              Управление новостями
            </h1>
            <p className="mt-3 text-sm font-medium text-muted-foreground/80 sm:text-base">
              CRUD, теги, категории, отложенная публикация.
            </p>
          </div>
          <Button onClick={openCreate} className="rounded-full shadow-lg shadow-primary/20 hover:scale-105 transition-transform" size="lg">
            <Plus className="mr-2 h-5 w-5" /> Новая новость
          </Button>
        </div>

        {/* Stat cards */}
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 animate-fade-in-up" style={{ animationDelay: '100ms' }}>
          {(['published', 'scheduled', 'draft', 'archived'] as NewsStatus[]).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded-3xl border p-6 text-left shadow-soft backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:shadow-elevated
                ${statusFilter === s
                  ? 'border-primary/50 bg-primary/5 ring-1 ring-primary/50 dark:bg-primary/10'
                  : 'border-border/50 bg-card/60 hover:bg-card/80'}
              `}
            >
              <div className="flex items-center justify-between">
                <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS_LABELS[s].tone}`}>
                  {STATUS_LABELS[s].label}
                </span>
              </div>
              <div className="mt-4 font-display text-4xl font-bold text-foreground">
                {counts[s] ?? 0}
              </div>
            </button>
          ))}
        </div>

        {/* Search + filter */}
        <div className="mt-8 flex flex-col gap-4 rounded-3xl border border-white/20 bg-white/40 p-5 shadow-soft backdrop-blur-xl dark:border-white/10 dark:bg-black/40 md:flex-row md:items-center animate-fade-in-up" style={{ animationDelay: '150ms' }}>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по заголовку или анонсу"
            className="h-11 rounded-xl bg-background/80 shadow-sm md:max-w-md"
          />
          <div className="flex flex-1 flex-wrap gap-2">
            <Button 
              variant={statusFilter === 'all' ? 'default' : 'outline'} 
              className={`h-11 rounded-xl px-5 transition-all ${statusFilter === 'all' ? 'shadow-md shadow-primary/20' : 'bg-background/50 hover:bg-background/80'}`}
              onClick={() => setStatusFilter('all')}
            >
              Все статусы
            </Button>
          </div>
          <div className="text-sm font-medium text-muted-foreground md:ml-auto">
            Показано: <span className="text-foreground">{newsList.length}</span> из {pageData?.total ?? '—'}
          </div>
        </div>

        {/* List */}
        <div className="mt-8 space-y-4">
          {isLoading && (
            <div className="flex h-32 items-center justify-center rounded-3xl border border-border/50 bg-card/40 backdrop-blur-sm">
              <div className="flex items-center gap-3 text-muted-foreground">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                Загрузка новостей...
              </div>
            </div>
          )}
          {!isLoading && newsList.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-border/60 bg-muted/10 p-16 text-center backdrop-blur-sm animate-fade-in-up">
              <div className="mb-4 rounded-full bg-muted/50 p-4">
                <Calendar className="h-8 w-8 text-muted-foreground" />
              </div>
              <div className="text-xl font-bold">Ничего не найдено</div>
              <p className="mt-2 text-muted-foreground">По вашему запросу не найдено ни одной новости.</p>
              <Button className="mt-6 rounded-full" onClick={openCreate}>
                <Plus className="mr-2 h-4 w-4" /> Создать первую новость
              </Button>
            </div>
          )}
          
          <div className="grid gap-4">
            {newsList.map((item, i) => {
              const tone = STATUS_LABELS[item.status];
              return (
                <div
                  key={item.id}
                  className="group relative flex flex-col gap-5 rounded-[1.5rem] border border-border/50 bg-card/70 p-5 shadow-sm backdrop-blur-sm transition-all duration-300 hover:-translate-y-1 hover:border-primary/30 hover:shadow-elevated md:flex-row md:items-center animate-fade-in-up"
                  style={{ animationDelay: `${(i % 10) * 50}ms` }}
                >
                  <div className="flex flex-1 items-start gap-5 overflow-hidden">
                    <div className="h-20 w-32 shrink-0 overflow-hidden rounded-xl bg-muted shadow-inner relative group-hover:shadow-md transition-shadow">
                      {item.image ? (
                        <img src={item.image} alt={item.title} className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center bg-muted/50 text-muted-foreground">
                          <ImagePlus className="h-6 w-6 opacity-20" />
                        </div>
                      )}
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col justify-center">
                      <div className="mb-1.5 flex flex-wrap items-center gap-2">
                        <h2 className="truncate text-lg font-bold text-foreground group-hover:text-primary transition-colors">{item.title}</h2>
                        <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${tone.tone}`}>
                          {tone.label}
                        </span>
                        {item.category && (
                          <Badge variant="outline" className="bg-background/50">{item.category.name}</Badge>
                        )}
                      </div>
                      <div className="mb-2 truncate text-xs font-medium text-muted-foreground">/{item.slug}</div>
                      
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                        {(item.scheduled_at || item.published_at) && (
                          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground/80">
                            <Calendar className="h-3.5 w-3.5 text-primary/70" />
                            {item.status === 'scheduled' && item.scheduled_at
                              ? `Публикация: ${new Date(item.scheduled_at).toLocaleString('ru-RU')}`
                              : item.published_at
                                ? new Date(item.published_at).toLocaleString('ru-RU')
                                : ''}
                          </div>
                        )}
                        {item.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {item.tags.map((t) => (
                              <span key={t.id} className="rounded-md bg-muted/60 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground">
                                #{t.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2 border-t pt-4 md:border-none md:pt-0">
                    <Button variant="secondary" size="sm" onClick={() => openEdit(item)} className="rounded-xl bg-secondary/10 text-secondary-foreground hover:bg-secondary/20">
                      Редактировать
                    </Button>
                    <Button variant="ghost" size="sm" asChild className="rounded-xl hover:bg-primary/5 hover:text-primary">
                      <a href={`/news/${item.slug}`} target="_blank" rel="noreferrer">
                        <Eye className="mr-1.5 h-4 w-4" /> Просмотр
                      </a>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="rounded-xl text-destructive hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => {
                        if (window.confirm(`Удалить «${item.title}»?`)) deleteMutation.mutate(item.id);
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Editor dialog */}
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen} modal={false}>
          <DialogContent
            aria-describedby={undefined}
            className="max-h-[92vh] w-[96vw] max-w-4xl overflow-y-auto rounded-[2rem] border-border/50 bg-background/95 p-6 shadow-elevated backdrop-blur-xl sm:p-8"
            onPointerDownOutside={(e) => {
              // Jodit renders popups (font/color/link/image/table dialogs) into
              // document.body. Without this, Radix sees clicks on those popups
              // as "outside" and closes the dialog or swallows the click.
              const t = e.target as HTMLElement | null;
              if (t?.closest('.jodit-popup, .jodit-dialog, .jodit-toolbar-popup, .jodit-ui-tooltip')) {
                e.preventDefault();
              }
            }}
            onInteractOutside={(e) => {
              const t = e.target as HTMLElement | null;
              if (t?.closest('.jodit-popup, .jodit-dialog, .jodit-toolbar-popup, .jodit-ui-tooltip')) {
                e.preventDefault();
              }
            }}
            onFocusOutside={(e) => {
              const t = e.target as HTMLElement | null;
              if (t?.closest('.jodit-popup, .jodit-dialog, .jodit-toolbar-popup')) {
                e.preventDefault();
              }
            }}
          >
            <DialogHeader className="mb-6 border-b border-border/50 pb-4">
              <div className="flex flex-wrap items-center justify-between gap-4 sm:pr-6">
                <DialogTitle className="font-display text-2xl font-bold sm:text-3xl">
                  {editing ? 'Редактирование новости' : 'Создание новости'}
                </DialogTitle>
                <span className={`rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wider ${STATUS_LABELS[form.status].tone}`}>
                  {STATUS_LABELS[form.status].label}
                </span>
              </div>
            </DialogHeader>

            <div className="grid gap-6">
              <div className="grid gap-2.5 text-sm font-medium">
                <label htmlFor="news-title">Заголовок</label>
                <Input
                  id="news-title"
                  value={form.title}
                  onBlur={onTitleBlur}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Введите броский заголовок..."
                  className="h-12 rounded-xl bg-muted/30 text-lg"
                />
              </div>

              <div className="grid gap-2.5 text-sm font-medium">
                <div className="flex items-center justify-between">
                  <label htmlFor="news-slug">Slug (URL-адрес)</label>
                  <button
                    type="button"
                    className="text-xs font-semibold text-primary transition-colors hover:text-primary/80"
                    onClick={() => setForm((f) => ({ ...f, slug: slugify(f.title) }))}
                  >
                    Сгенерировать из заголовка
                  </button>
                </div>
                <Input
                  id="news-slug"
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  placeholder="news-title-url"
                  className="h-11 rounded-xl bg-muted/30"
                />
              </div>

              <div className="grid gap-2.5 text-sm font-medium">
                <label htmlFor="news-excerpt">Краткое описание (Анонс)</label>
                <Textarea
                  id="news-excerpt"
                  value={form.excerpt}
                  onChange={(e) => setForm({ ...form, excerpt: e.target.value })}
                  placeholder="Текст, который будет виден на карточке новости..."
                  className="min-h-[100px] resize-y rounded-xl bg-muted/30 text-base"
                  maxLength={500}
                />
                <div className="text-right text-xs font-medium text-muted-foreground">
                  {form.excerpt.length} / 500
                </div>
              </div>

              <div className="grid gap-2.5 text-sm font-medium">
                <label>Основной контент</label>
                <div className="rounded-xl border border-border/50 bg-card/50 overflow-hidden">
                  <NewsEditor
                    value={form.content}
                    onChange={(content) => setForm((f) => ({ ...f, content }))}
                  />
                </div>
              </div>

              {/* Cover */}
              <div className="grid gap-3 text-sm font-medium">
                <div className="flex items-center justify-between">
                  <span>Обложка новости</span>
                  {form.imageUrl && (
                    <button
                      type="button"
                      className="text-xs font-semibold text-destructive transition-colors hover:text-destructive/80"
                      onClick={() => setForm((f) => ({ ...f, imageUrl: null, imageFile: null }))}
                    >
                      Удалить обложку
                    </button>
                  )}
                </div>
                {form.imageUrl ? (
                  <div className="group relative overflow-hidden rounded-2xl border border-border/50 bg-muted">
                    <img src={form.imageUrl} alt="Cover preview" className="aspect-[21/9] w-full object-cover transition-transform group-hover:scale-105" />
                    <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100">
                      <label className="cursor-pointer rounded-full bg-white/20 px-4 py-2 text-sm font-semibold text-white backdrop-blur-md transition-colors hover:bg-white/30">
                        Изменить изображение
                        <input
                          type="file"
                          accept="image/*"
                          hidden
                          onChange={(e) =>
                            setForm((f) => ({ ...f, imageFile: e.target.files?.[0] || null }))
                          }
                        />
                      </label>
                    </div>
                  </div>
                ) : (
                  <label className="flex h-40 cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-border/60 bg-muted/10 text-muted-foreground transition-colors hover:bg-muted/30 hover:text-foreground">
                    <div className="rounded-full bg-background p-3 shadow-sm">
                      <ImagePlus className="h-6 w-6 text-primary" />
                    </div>
                    <span className="font-medium">Нажмите, чтобы загрузить обложку</span>
                    <input
                      type="file"
                      accept="image/*"
                      hidden
                      onChange={(e) =>
                        setForm((f) => ({ ...f, imageFile: e.target.files?.[0] || null }))
                      }
                    />
                  </label>
                )}
                {form.imageUrl && !form.imageFile && (
                  <Input
                    value={form.imageUrl}
                    onChange={(e) => setForm({ ...form, imageUrl: e.target.value })}
                    placeholder="Или вставьте URL обложки"
                    className="mt-2 h-10 rounded-xl bg-muted/30"
                  />
                )}
              </div>

              {/* Category + Tags */}
              <div className="grid gap-6 rounded-2xl border border-border/50 bg-card/30 p-5 md:grid-cols-2">
                <div className="grid gap-2.5 text-sm font-medium">
                  <label>Категория</label>
                  <Select
                    value={form.category_id ? String(form.category_id) : 'none'}
                    onValueChange={(v) =>
                      setForm({ ...form, category_id: v === 'none' ? null : Number(v) })
                    }
                  >
                    <SelectTrigger className="h-11 rounded-xl bg-background/50">
                      <SelectValue placeholder="Без категории" />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl">
                      <SelectItem value="none">Без категории</SelectItem>
                      {categories.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2.5 text-sm font-medium">
                  <label>Теги</label>
                  <TagsMultiSelect
                    value={form.tag_ids}
                    onChange={(tag_ids) => setForm({ ...form, tag_ids })}
                  />
                </div>
              </div>

              {/* Status + scheduling */}
              <div className="grid gap-6 rounded-2xl border border-border/50 bg-card/50 p-5 shadow-sm md:grid-cols-2">
                <div className="grid gap-2.5 text-sm font-medium">
                  <label>Статус публикации</label>
                  <Select
                    value={form.status}
                    onValueChange={(v: NewsStatus) => setForm({ ...form, status: v })}
                  >
                    <SelectTrigger className="h-11 rounded-xl bg-background/80">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl">
                      <SelectItem value="draft">Черновик</SelectItem>
                      <SelectItem value="scheduled">Запланировать публикацию</SelectItem>
                      <SelectItem value="published">Опубликовать сразу</SelectItem>
                      <SelectItem value="archived">В архив</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {form.status === 'scheduled' && (
                  <div className="grid gap-2.5 text-sm font-medium animate-in fade-in slide-in-from-top-2">
                    <label>Дата и время публикации</label>
                    <Input
                      type="datetime-local"
                      value={form.scheduled_at}
                      onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })}
                      className="h-11 rounded-xl bg-background/80"
                    />
                  </div>
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-end gap-3 border-t border-border/50 pt-6">
                <Button variant="outline" size="lg" onClick={() => setDialogOpen(false)} disabled={saving} className="rounded-xl px-6">
                  Отмена
                </Button>
                <Button size="lg" onClick={save} disabled={saving || !form.title || !form.slug} className="rounded-xl px-8 font-bold shadow-md shadow-primary/20">
                  {saving ? (
                    <><div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> Сохранение...</>
                  ) : editing ? 'Сохранить изменения' : 'Создать новость'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </main>
    </div>
  );
};

export default AdminNews;
