/**
 * ManageHomeSections — страница «Главная страница» в разделе «Контент».
 *
 * Управляет блоками лендинга: порядок, видимость, тексты на двух языках и
 * список элементов внутри блока (направления, услуги, цифры, карточки).
 *
 * ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Кнопки «создать блок»: у каждой секции свой
 * React-компонент со своей вёрсткой, и запись в БД без компонента ничего бы не
 * нарисовала. Новый блок — работа разработчика; кнопка обещала бы то, чего
 * система не умеет. Элементы ВНУТРИ блока добавлять можно — они рисуются
 * одинаковым циклом.
 *
 * Порядок меняется стрелками, а не перетаскиванием: блоков девять, список не
 * растёт, а стрелки работают с клавиатуры и не ломаются на тач-экранах.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ArrowDown, ArrowUp, Eye, EyeOff, Pencil, Plus, Trash2,
} from 'lucide-react';

import {
  homeAdminApi, type HomeItemAdmin, type HomeSectionAdmin,
} from '@/api/homeSections';
import { BackToProfile } from '@/components/BackToProfile';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { IconPicker, LucideIcon } from '@/components/ui/icon-picker';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

const QK = ['home-sections-admin'];

/** Человеческие имена блоков. Ключ приходит из БД и совпадает с компонентом;
 *  показывать редактору `hero` вместо «Первый экран» было бы недружелюбно. */
const SECTION_LABELS: Record<string, string> = {
  hero: 'Первый экран',
  directions: 'Направления деятельности',
  invest: 'Инвестиции (призыв)',
  projects: 'Портфолио проектов',
  services: 'Что мы делаем',
  stats: 'Наше влияние (цифры)',
  mission: 'Наша миссия',
  about: 'О компании',
  partners: 'Партнёры',
};

/** Подсказка, какие поля элемента реально видны в этом блоке. Поля модели
 *  общие для всех секций, но макеты разные — без подписи редактор гадал бы,
 *  почему «Значение» не появляется на лендинге. */
const ITEM_HINTS: Record<string, string> = {
  hero: 'Показываются: значение и описание',
  stats: 'Показываются: значение и подпись',
  directions: 'Показываются: заголовок, описание, иконка',
  services: 'Показываются: заголовок, описание',
  mission: 'Показываются: заголовок, описание, иконка',
  about: 'Показываются: заголовок, описание, иконка',
};

/** Готовые макеты. Значения совпадают с `HomeSection.Layout` на бэкенде. */
const LAYOUTS: { value: string; label: string; hint: string }[] = [
  { value: 'features_grid', label: 'Сетка карточек', hint: 'Иконка/картинка, заголовок, текст — как «Направления» или «Что мы делаем»' },
  { value: 'stats', label: 'Цифры', hint: 'Крупное значение и подпись — как «Наше влияние»' },
  { value: 'cta', label: 'Призыв к действию', hint: 'Заголовок, текст и кнопка — как блок «Инвестиции»' },
  { value: 'text_media', label: 'Текст с картинкой', hint: 'Картинка слева, текст и список справа — как «О компании»' },
];

type EditTarget =
  | { kind: 'section'; section: HomeSectionAdmin }
  | { kind: 'item'; section: HomeSectionAdmin; item: HomeItemAdmin | null };

export default function ManageHomeSections() {
  useTranslation();
  const queryClient = useQueryClient();
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [createOpen, setCreateOpen] = useState(false);

  const { data: sections, isLoading, error } = useQuery({
    queryKey: QK,
    queryFn: homeAdminApi.list,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: QK });

  const toggleVisible = useMutation({
    mutationFn: (s: HomeSectionAdmin) =>
      homeAdminApi.updateSection(s.id, { is_visible: !s.is_visible }),
    onSuccess: (_d, s) => {
      invalidate();
      toast.success(s.is_visible ? 'Блок скрыт' : 'Блок показан');
    },
    onError: () => toast.error('Не удалось изменить видимость'),
  });

  const reorder = useMutation({
    mutationFn: (ids: number[]) => homeAdminApi.reorderSections(ids),
    onSuccess: invalidate,
    onError: () => toast.error('Не удалось изменить порядок'),
  });

  const createSection = useMutation({
    mutationFn: (data: { title_ru: string; layout: string }) =>
      homeAdminApi.createSection(data),
    onSuccess: () => { invalidate(); setCreateOpen(false); toast.success('Блок создан'); },
    onError: () => toast.error('Не удалось создать блок'),
  });

  const deleteSection = useMutation({
    mutationFn: (id: number) => homeAdminApi.deleteSection(id),
    onSuccess: () => { invalidate(); toast.success('Блок удалён'); },
    onError: (err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      toast.error(status === 409
        ? 'Системный блок нельзя удалить — его можно только скрыть'
        : 'Не удалось удалить блок');
    },
  });

  const deleteItem = useMutation({
    mutationFn: (itemId: number) => homeAdminApi.deleteItem(itemId),
    onSuccess: () => { invalidate(); toast.success('Элемент удалён'); },
    onError: () => toast.error('Не удалось удалить элемент'),
  });

  const toggleItemVisible = useMutation({
    mutationFn: (i: HomeItemAdmin) =>
      homeAdminApi.updateItem(i.id, { is_visible: !i.is_visible }),
    onSuccess: invalidate,
    onError: () => toast.error('Не удалось изменить видимость элемента'),
  });

  const ordered = useMemo(() => sections ?? [], [sections]);

  /** Двигает блок на одну позицию и отправляет ВЕСЬ новый порядок: сервер
   *  переписывает колонку order целиком, поэтому частичная отправка оставила
   *  бы список рассогласованным. */
  const move = (index: number, delta: number) => {
    const next = [...ordered];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next.map((s) => s.id));
  };

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container-custom py-8">
        <BackToProfile />
        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl font-bold">Главная страница</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Порядок, видимость и содержимое блоков лендинга. Изменения появляются
              на сайте сразу после сохранения.
            </p>
          </div>
          <Button className="gap-1.5" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> Создать блок
          </Button>
        </div>

        {isLoading && (
          <div className="rounded-2xl border bg-card/70 p-8 text-center">Загрузка…</div>
        )}
        {error && (
          <div className="rounded-2xl border bg-card/70 p-8 text-center text-destructive">
            Не удалось загрузить блоки.
          </div>
        )}

        <div className="grid gap-3">
          {ordered.map((section, index) => (
            <section
              key={section.id}
              className={`rounded-xl border bg-card p-4 ${section.is_visible ? '' : 'opacity-60'}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex flex-col">
                  <Button
                    variant="ghost" size="icon" className="h-6 w-6"
                    disabled={index === 0 || reorder.isPending}
                    onClick={() => move(index, -1)}
                    aria-label="Выше"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost" size="icon" className="h-6 w-6"
                    disabled={index === ordered.length - 1 || reorder.isPending}
                    onClick={() => move(index, 1)}
                    aria-label="Ниже"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </Button>
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">
                      {/* У системных — человеческое имя из словаря (их ключи
                          служебные), у созданных — собственный заголовок. */}
                      {SECTION_LABELS[section.key] ?? section.title_ru ?? section.key}
                    </span>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {section.key}
                    </Badge>
                    {!section.is_visible && <Badge variant="secondary">скрыт</Badge>}
                    {!section.is_system && (
                      <Badge variant="outline">
                        {LAYOUTS.find((l) => l.value === section.layout)?.label ?? section.layout}
                      </Badge>
                    )}
                  </div>
                  <div className="truncate text-sm text-muted-foreground">
                    {section.title_ru || '— без заголовка —'}
                  </div>
                </div>

                <Button
                  variant="ghost" size="sm"
                  onClick={() => toggleVisible.mutate(section)}
                  disabled={toggleVisible.isPending}
                  className="gap-1.5"
                >
                  {section.is_visible
                    ? <><Eye className="h-4 w-4" /> Показан</>
                    : <><EyeOff className="h-4 w-4" /> Скрыт</>}
                </Button>
                <Button
                  variant="outline" size="sm" className="gap-1.5"
                  onClick={() => setEditTarget({ kind: 'section', section })}
                >
                  <Pencil className="h-4 w-4" /> Тексты
                </Button>
                <Button
                  variant="ghost" size="sm"
                  onClick={() => setExpanded((p) => ({ ...p, [section.id]: !p[section.id] }))}
                >
                  Элементы ({section.items.length})
                </Button>
                {/* Системные блоки не удаляются: у них свой React-компонент,
                    и пересоздать такой из интерфейса нельзя — новый получил бы
                    generic-макет. Их прячут переключателем слева. */}
                <Button
                  variant="ghost" size="icon" className="h-8 w-8 text-destructive"
                  disabled={section.is_system || deleteSection.isPending}
                  title={section.is_system
                    ? 'Системный блок — его можно только скрыть'
                    : 'Удалить блок'}
                  onClick={() => {
                    if (window.confirm(`Удалить блок «${section.title_ru || section.key}» со всеми элементами? Действие необратимо.`)) {
                      deleteSection.mutate(section.id);
                    }
                  }}
                  aria-label="Удалить блок"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>

              {expanded[section.id] && (
                <div className="mt-3 border-t pt-3">
                  {ITEM_HINTS[section.key] && (
                    <p className="mb-2 text-xs text-muted-foreground">
                      {ITEM_HINTS[section.key]}
                    </p>
                  )}
                  <div className="grid gap-2">
                    {section.items.map((item) => (
                      <div
                        key={item.id}
                        className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm ${item.is_visible ? '' : 'opacity-60'}`}
                      >
                        <span className="min-w-0 flex-1 truncate">
                          {item.value && <strong className="mr-2">{item.value}</strong>}
                          {item.title_ru || item.description_ru || '—'}
                        </span>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => toggleItemVisible.mutate(item)}
                          aria-label={item.is_visible ? 'Скрыть' : 'Показать'}
                        >
                          {item.is_visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => setEditTarget({ kind: 'item', section, item })}
                          aria-label="Изменить"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost" size="icon"
                          className="h-7 w-7 text-destructive"
                          onClick={() => {
                            if (window.confirm('Удалить элемент? Действие необратимо.')) {
                              deleteItem.mutate(item.id);
                            }
                          }}
                          aria-label="Удалить"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                    <Button
                      variant="outline" size="sm" className="w-fit gap-1.5"
                      onClick={() => setEditTarget({ kind: 'item', section, item: null })}
                    >
                      <Plus className="h-4 w-4" /> Добавить элемент
                    </Button>
                  </div>
                </div>
              )}
            </section>
          ))}
        </div>
      </main>

      <EditDialog
        target={editTarget}
        onClose={() => setEditTarget(null)}
        onSaved={invalidate}
      />

      <CreateSectionDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={(data) => createSection.mutate(data)}
        pending={createSection.isPending}
      />
    </div>
  );
}

/** Одна форма на секцию и на элемент: поля почти совпадают, а две почти
 *  одинаковые формы разъехались бы при первой же правке. */
function EditDialog({
  target, onClose, onSaved,
}: {
  target: EditTarget | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isSection = target?.kind === 'section';
  const item = target?.kind === 'item' ? target.item : null;

  const [form, setForm] = useState<Record<string, string>>({});
  const [seededFor, setSeededFor] = useState<string | null>(null);

  // Ключ цели: пересеиваем форму при СМЕНЕ цели, а не на каждый рендер —
  // иначе набранное затиралось бы на первом же обновлении списка.
  const targetKey = target
    ? `${target.kind}:${isSection ? target.section.id : item?.id ?? 'new'}`
    : null;

  if (targetKey && targetKey !== seededFor) {
    if (isSection) {
      const s = target.section;
      setForm({
        tag_ru: s.tag_ru, tag_en: s.tag_en,
        title_ru: s.title_ru, title_en: s.title_en,
        description_ru: s.description_ru, description_en: s.description_en,
      });
    } else {
      setForm({
        title_ru: item?.title_ru ?? '', title_en: item?.title_en ?? '',
        description_ru: item?.description_ru ?? '', description_en: item?.description_en ?? '',
        value: item?.value ?? '', icon: item?.icon ?? '',
        image: item?.image ?? '', link: item?.link ?? '',
      });
    }
    setSeededFor(targetKey);
  }

  const save = useMutation({
    mutationFn: async () => {
      if (!target) return;
      if (target.kind === 'section') {
        return homeAdminApi.updateSection(target.section.id, form);
      }
      if (target.item) return homeAdminApi.updateItem(target.item.id, form);
      return homeAdminApi.createItem(target.section.id, form);
    },
    onSuccess: () => {
      onSaved();
      toast.success('Сохранено');
      onClose();
    },
    onError: () => toast.error('Не удалось сохранить'),
  });

  const set = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const langFields = (lang: 'ru' | 'en') => (
    <div className="grid gap-3">
      {isSection && (
        <div className="grid gap-1.5">
          <Label>Подпись над заголовком</Label>
          <Input value={form[`tag_${lang}`] ?? ''} onChange={(e) => set(`tag_${lang}`, e.target.value)} />
        </div>
      )}
      <div className="grid gap-1.5">
        <Label>Заголовок</Label>
        <Input value={form[`title_${lang}`] ?? ''} onChange={(e) => set(`title_${lang}`, e.target.value)} />
      </div>
      <div className="grid gap-1.5">
        <Label>Описание</Label>
        <Textarea
          rows={3}
          value={form[`description_${lang}`] ?? ''}
          onChange={(e) => set(`description_${lang}`, e.target.value)}
        />
      </div>
      {lang === 'en' && (
        <p className="text-xs text-muted-foreground">
          Пустое поле — на английской версии сайта покажется русский текст.
        </p>
      )}
    </div>
  );

  return (
    <Dialog open={Boolean(target)} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {isSection
              ? `Тексты блока: ${SECTION_LABELS[target.section.key] ?? target.section.title_ru ?? target.section.key}`
              : item ? 'Изменить элемент' : 'Новый элемент'}
          </DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="ru">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="ru">Русский</TabsTrigger>
            <TabsTrigger value="en">English</TabsTrigger>
          </TabsList>
          <TabsContent value="ru" className="pt-3">{langFields('ru')}</TabsContent>
          <TabsContent value="en" className="pt-3">{langFields('en')}</TabsContent>
        </Tabs>

        {!isSection && (
          <div className="grid gap-3 border-t pt-3">
            <p className="text-xs text-muted-foreground">Общее для обоих языков</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label>Значение</Label>
                <Input
                  value={form.value ?? ''}
                  onChange={(e) => set('value', e.target.value)}
                  placeholder="722, 10+, 90 МВт"
                />
              </div>
              <div className="grid gap-1.5">
                <Label>Иконка</Label>
                <IconPicker value={form.icon ?? ''} onChange={(name) => set('icon', name)} />
              </div>
              <div className="grid gap-1.5">
                <Label>Картинка</Label>
                <Input
                  value={form.image ?? ''}
                  onChange={(e) => set('image', e.target.value)}
                  placeholder="/images/panels1.webp"
                />
              </div>
              <div className="grid gap-1.5">
                <Label>Ссылка</Label>
                <Input value={form.link ?? ''} onChange={(e) => set('link', e.target.value)} />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Иконки — из набора lucide, того же, что использует весь интерфейс.
            </p>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>Отмена</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Сохранение…' : 'Сохранить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


/** Создание блока: заголовок + макет. Остальное правится потом обычной формой —
 *  просить всё сразу значит держать редактора в модалке дольше, чем нужно. */
function CreateSectionDialog({
  open, onClose, onCreate, pending,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (data: { title_ru: string; layout: string }) => void;
  pending: boolean;
}) {
  const [title, setTitle] = useState('');
  const [layout, setLayout] = useState('features_grid');

  // Чистим форму при открытии, а не при закрытии: отменённый ввод не должен
  // всплыть в следующий раз.
  const [seeded, setSeeded] = useState(false);
  if (open && !seeded) { setTitle(''); setLayout('features_grid'); setSeeded(true); }
  if (!open && seeded) setSeeded(false);

  const hint = LAYOUTS.find((l) => l.value === layout)?.hint;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Новый блок</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label>Заголовок (русский)</Label>
            <Input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Например: Наши преимущества"
            />
            <span className="text-xs text-muted-foreground">
              Служебный адрес блока сервер выведет сам — вводить его не нужно.
            </span>
          </div>
          <div className="grid gap-1.5">
            <Label>Макет</Label>
            <Select value={layout} onValueChange={setLayout}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {LAYOUTS.map((l) => (
                  <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
          </div>
          <p className="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            Блок появится в конце страницы и будет скрыт от посетителей, пока вы
            не наполните его и не включите показ.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>Отмена</Button>
          <Button
            onClick={() => onCreate({ title_ru: title.trim(), layout })}
            disabled={!title.trim() || pending}
          >
            {pending ? 'Создание…' : 'Создать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
