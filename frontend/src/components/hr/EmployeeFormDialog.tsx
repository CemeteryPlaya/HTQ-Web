import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Briefcase, Building2, Check, ChevronDown, ChevronsUpDown, IdCard, Lock, Plus, Share2, UserPlus } from 'lucide-react';
import {
  createDepartment,
  createEmployeeUser,
  createEmployeeWithCard,
  createPosition,
  fetchCardT2,
  fetchDepartments,
  fetchEmployeeUsers,
  fetchPositions,
  updateEmployeeWithCard,
} from '@/api/hr';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { PhoneInput } from '@/components/ui/phone-input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { cn } from '@/lib/utils';
import { useHRLevel } from '@/hooks/useHRLevel';
import { Employee, relationId } from '@/components/hr/employeeCommon';
import {
  SECTION_FIELDS, SECTION_TITLE, T2_SECTIONS,
  buildCardT2Payload, emptyT2Form, isT2SectionDirty, t2FormFromServer, validateT2Money,
  type T2FormState,
} from '@/components/hr/cardT2Fields';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';

/**
 * Кнопка «Создать …» в комбобоксе — СРАЗУ под строкой поиска.
 *
 * Намеренно НЕ `CommandItem`: cmdk фильтрует элементы по введённому тексту, и
 * пункт создания исчезал бы ровно тогда, когда он нужен больше всего — когда
 * искомого в списке нет. Обычная кнопка вне `CommandList` не фильтруется и
 * остаётся на месте при любом запросе.
 */
const ComboboxCreateAction = ({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof Plus;
  label: string;
  onClick: () => void;
}) => (
  <div className="border-b p-1">
    <button
      type="button"
      onClick={onClick}
      className="flex w-full cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm font-medium text-primary outline-none hover:bg-accent focus-visible:bg-accent"
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  </div>
);

/** Frontend-friendly status values mapped to the backend's allowed pattern. */
const STATUS_TO_BACKEND: Record<string, 'active' | 'inactive' | 'terminated'> = {
  active: 'active',
  on_leave: 'inactive',
  inactive: 'inactive',
  dismissed: 'terminated',
  terminated: 'terminated',
};

interface Props {
  open: boolean;
  /** null — режим создания. */
  employee: Employee | null;
  onOpenChange: (open: boolean) => void;
}

export function EmployeeFormDialog({ open, employee, onOpenChange }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const editing = employee;

  const {
    canWriteBasic,
    canCreateEmployee,
    canTransferEmployee,
    canListUserOptions,
    canManageUserOptions,
    hasPerm,
  } = useHRLevel();

  // Запросы включаются только когда диалог открыт, чтобы не дёргать API на
  // каждом рендере страницы-списка.
  const { data: departments } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
    enabled: open,
  });

  const { data: positions } = useQuery({
    queryKey: ['hr-positions'],
    queryFn: fetchPositions,
    enabled: open,
  });

  const { data: users } = useQuery({
    queryKey: ['hr-employee-users'],
    queryFn: () => fetchEmployeeUsers(),
    enabled: open && canListUserOptions,
  });

  const [form, setForm] = useState({
    user: 'none',
    position: 'none',
    department: 'none',
    phone: '',
    date_hired: '',
    date_dismissed: '',
    status: 'active',
    notes: '',
  });

  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const [t2Form, setT2Form] = useState<T2FormState>(emptyT2Form);
  const [t2Initial, setT2Initial] = useState<T2FormState>(emptyT2Form);
  const [t2Errors, setT2Errors] = useState<Record<string, string>>({});
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const [shareOpen, setShareOpen] = useState(false);

  // Последние значения t2Form/t2Initial без попадания в зависимости эффекта
  // ниже — иначе setT2Form/setT2Initial внутри самого эффекта переисполняли
  // бы его на каждый повторный «чистый» посев (новая ссылка объекта от
  // t2FormFromServer при том же cardT2) и зациклили бы рендер.
  const t2FormRef = useRef(t2Form);
  const t2InitialRef = useRef(t2Initial);
  t2FormRef.current = t2Form;
  t2InitialRef.current = t2Initial;

  /** Секции, которые вообще показываем: нужен view. */
  const visibleSections = useMemo(
    () => T2_SECTIONS.filter((s) => hasPerm(`hr.card.${s}.view`)),
    [hasPerm],
  );

  const { data: cardT2 } = useQuery({
    queryKey: ['hr-card-t2', employee?.id],
    queryFn: () => fetchCardT2(employee!.id),
    enabled: open && !!employee && visibleSections.length > 0,
  });

  /** Пока идёт (или упал) запрос текущих значений редактируемого сотрудника,
   *  секция рисуется пустой — но пустая НЕ значит «нет данных»: это может
   *  значить «ещё не загрузились». Создание не ждёт ничего (нечего грузить). */
  const t2Loaded = !employee || cardT2 !== undefined;

  /** Секции, которые уходят в payload: нужен и view, и edit, И текущие
   *  значения уже должны были загрузиться. Секцию с одним лишь edit мы не
   *  показываем — форма не знала бы текущих значений и сохранение затёрло бы
   *  их null-ами; то же самое верно, если view есть, но GET ещё не
   *  отработал (или упал) — иначе пользователь печатал бы поверх пустого
   *  снимка и стёр бы то, чего не видел. */
  const editableSections = useMemo(
    () => (t2Loaded ? visibleSections.filter((s) => hasPerm(`hr.card.${s}.edit`)) : []),
    [visibleSections, hasPerm, t2Loaded],
  );

  // Заполняем секции при открытии — и повторно, если пришли более свежие
  // данные, НО ТОЛЬКО пока форма чистая (пользователь ничего не тронул).
  //
  // Раньше (round 1) эффект сеял РОВНО ОДИН РАЗ на пару (open, employee.id) —
  // это защищало от позднего fetch/инвалидации, перезатирающих набранное
  // посреди печати, но переборщило: после сохранения `onSuccess` инвалидирует
  // `hr-card-t2`, react-query отдаёт на следующий mount старый кэш и
  // рефетчит в фоне — если пользователь переоткрыл тот же диалог до того, как
  // рефетч долетел, форма сеялась устаревшими (досохраненными) значениями и
  // больше НИКОГДА не обновлялась в рамках этой сессии диалога, даже когда
  // свежие данные приходили следом.
  //
  // Различаем два случая по фактической «грязности» формы: если пользователь
  // ничего не менял (форма == t2Initial по всем секциям), более свежий
  // cardT2 можно и нужно принять; если хоть одна секция дирти — не трогаем
  // ничего, ждём следующего изменения cardT2 или закрытия диалога (это и есть
  // защита round-1 от перезатирания набранного).
  //
  // round 3: компонент не размонтируется между открытиями (HREmployees
  // держит его смонтированным постоянно), поэтому t2Form переживает закрытие
  // диалога. Раньше первый посев ПРИ ХОЛОДНОМ КЭШЕ (cardT2 === undefined) не
  // трогал t2Form вообще (`return` до setT2Form) — и пока GET не долетел, на
  // экране оставались значения ПРЕДЫДУЩЕГО открытого сотрудника: правильный
  // заголовок, чужие оклад/паспорт/ИИН. Секцию нельзя было отправить
  // (editableSections пуст, пока t2Loaded === false), но показывать её было
  // нельзя тем более — это чужие конфиденциальные данные под чужим именем.
  // Теперь при первом посеве этого открытия, если данные ещё не готовы, сеем
  // пустую форму сразу — и НЕ трогаем t2SeedKeyRef, чтобы эффект посчитал
  // следующий свой запуск (когда придёт cardT2) тем же «первым посевом» и
  // выполнил уже авторитетный посев данными сервера.
  const t2SeedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!open) {
      t2SeedKeyRef.current = null;
      return;
    }
    const seedKey = String(employee?.id ?? 'new');
    const firstSeedForThisOpen = t2SeedKeyRef.current !== seedKey;
    if (!firstSeedForThisOpen) {
      // Читаем через ref, а не из замыкания/зависимостей — иначе setT2Form
      // ниже сам вызвал бы этот эффект по кругу (см. комментарий у объявления
      // t2FormRef).
      const clean = T2_SECTIONS.every(
        (s) => !isT2SectionDirty(t2FormRef.current, t2InitialRef.current, s),
      );
      if (!clean) return; // пользователь печатает — не перезатираем
    }
    const dataReady = !(employee && visibleSections.length > 0 && cardT2 === undefined);
    if (firstSeedForThisOpen && !dataReady) {
      // Холодный кэш: сеем пустую форму вместо того, что осталось от
      // предыдущего сотрудника, и ждём следующего запуска эффекта (придёт
      // cardT2 — сработает ветка ниже). t2SeedKeyRef НЕ обновляем.
      setT2Form(emptyT2Form());
      setT2Initial(emptyT2Form());
      setT2Errors({});
      setOpenSections({});
      return;
    }
    if (!dataReady) return; // ждём GET
    const next = employee ? t2FormFromServer(cardT2) : emptyT2Form();
    setT2Form(next);
    setT2Initial(next);
    if (firstSeedForThisOpen) {
      // Ошибки/раскрытые секции сбрасываем только на первый посев этого
      // открытия — повторный «тихий» посев свежими данными по чистой форме
      // не должен сворачивать секцию, которую пользователь как раз открыл
      // посмотреть.
      setT2Errors({});
      setOpenSections({});
    }
    t2SeedKeyRef.current = seedKey;
    // t2Form/t2Initial намеренно не в зависимостях — читаем их через ref
    // (см. выше), поэтому lint не требует их сюда (ref-чтения исключены из
    // exhaustive-deps): включи мы их напрямую, setT2Form/setT2Initial из
    // этого же эффекта зациклили бы его повторный запуск на каждый чистый
    // посев.
  }, [open, employee, cardT2, visibleSections.length]);

  // Заполнение формы переезжает из startCreate/startEdit в эффект — раньше
  // страница заполняла состояние в момент нажатия кнопки, теперь компонент
  // реагирует на props.
  useEffect(() => {
    if (!open) return;
    setFormError(null);
    setFieldErrors({});
    if (!employee) {
      setForm({
        user: 'none', position: 'none', department: 'none', phone: '',
        date_hired: '', date_dismissed: '', status: 'active', notes: '',
      });
      return;
    }
    // Backend EmployeeOut использует user_id / вложенные position+department /
    // hire_date / termination_date; старые эндпойнты — user / date_hired /
    // date_dismissed. Читаем обе формы.
    const userId = employee.user_id ?? (typeof employee.user === 'number' ? employee.user : null);
    const positionId = employee.position_id ?? relationId(employee.position);
    const departmentId = employee.department_id ?? relationId(employee.department);
    setForm({
      user: userId ? String(userId) : 'none',
      position: positionId ? String(positionId) : 'none',
      department: departmentId ? String(departmentId) : 'none',
      phone: employee.phone || '',
      date_hired: employee.hire_date || employee.date_hired || '',
      date_dismissed: employee.termination_date || employee.date_dismissed || '',
      status: employee.status || 'active',
      notes: employee.bio || employee.notes || '',
    });
  }, [open, employee]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const backendStatus = STATUS_TO_BACKEND[form.status] || 'active';
      const cardT2 = buildCardT2Payload(t2Form, t2Initial, editableSections);

      if (editing) {
        // EmployeeUpdate — every field optional. Only send what changed.
        const patch: Record<string, unknown> = {
          status: backendStatus,
          phone: form.phone || undefined,
          bio: form.notes || undefined,
        };
        if (form.position !== 'none') patch.position_id = Number(form.position);
        if (form.department !== 'none') patch.department_id = Number(form.department);
        if (form.date_dismissed) patch.termination_date = form.date_dismissed;
        if (cardT2) patch.card_t2 = cardT2;
        // card_t2 может нести зарплату/паспорт/ИИН — в консоль их не пишем,
        // только какие секции ушли (см. заголовок «Финансовые данные
        // (конфиденциально)» — печатать её содержимое противоречило бы этому).
        // eslint-disable-next-line no-console
        console.debug(
          '[hr.employees] update payload',
          editing.id,
          cardT2 ? { ...patch, card_t2: Object.keys(cardT2) } : patch,
        );
        return updateEmployeeWithCard(editing.id, patch);
      }

      // EmployeeCreate — first_name / last_name / email / department_id /
      // position_id / hire_date are all REQUIRED by the backend. We pull
      // name+email from the selected user record.
      const selected = users?.find((u) => String(u.id) === form.user);
      if (!selected) throw new Error('user_required');

      const [splitFirst = '', ...splitRest] = (selected.full_name || '').trim().split(/\s+/);
      const splitLast = splitRest.join(' ');

      const payload: Record<string, unknown> = {
        user_id: selected.id,
        first_name: selected.first_name || splitFirst || 'Unknown',
        last_name: selected.last_name || splitLast || '',
        email: selected.email,
        phone: form.phone || undefined,
        department_id: Number(form.department),
        position_id: Number(form.position),
        hire_date: form.date_hired,
        status: backendStatus,
        bio: form.notes || undefined,
      };
      if (cardT2) payload.card_t2 = cardT2;
      // eslint-disable-next-line no-console
      console.debug(
        '[hr.employees] create payload',
        cardT2 ? { ...payload, card_t2: Object.keys(cardT2) } : payload,
      );
      return createEmployeeWithCard(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
      if (editing) queryClient.invalidateQueries({ queryKey: ['hr-card-t2', editing.id] });
      onOpenChange(false);
      setFormError(null);
      setFieldErrors({});
      setForm({
        user: 'none', position: 'none', department: 'none', phone: '',
        date_hired: '', date_dismissed: '', status: 'active', notes: '',
      });
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      // eslint-disable-next-line no-console
      console.warn('[hr.employees] save error', err?.response?.status, data);

      const detail = typeof data?.detail === 'string' ? data.detail : null;

      // 403 из card_t2_svc.upsert приходит как ТОЧНАЯ строка
      // "Missing permission: hr.card.<section>.edit" — раскрываем виноватую
      // секцию И подсвечиваем её заголовок (t2Errors), а не только баннер:
      // без t2Errors sectionError всегда undefined, бейдж в заголовке не
      // рисуется, и пользователь видит только общую (сырую английскую) фразу
      // в баннере, не понимая, какая секция виновата.
      const missingPerm = detail ? /Missing permission: hr\.card\.(\w+)\.edit/.exec(detail) : null;
      const section = missingPerm ? T2_SECTIONS.find((s) => s === missingPerm[1]) : undefined;
      if (section) {
        const forbiddenMsg = t('hr.pages.employees.cardT2.forbidden', 'Недостаточно прав для правки этого раздела');
        setOpenSections((prev) => ({ ...prev, [section]: true }));
        setT2Errors((prev) => ({ ...prev, [`${section}.__server`]: forbiddenMsg }));
        setFieldErrors({});
        setFormError(forbiddenMsg);
        return;
      }

      // 422 из того же upsert — "Invalid decimal for <field>: <value>".
      // Клиентский MONEY_RE ловит мусор раньше, так что это почти
      // недостижимо, но если бэкенд всё же его вернул (например, кэш прав
      // устарел не в ту сторону и permission-проверка не сработала первой),
      // раскрываем секцию нужного поля и подсвечиваем именно его — как и
      // клиентская validateT2Money.
      const badDecimal = detail ? /Invalid decimal for (\w+)/.exec(detail) : null;
      const badField = badDecimal ? badDecimal[1]! : null;
      const badSection = badField
        ? T2_SECTIONS.find((s) => SECTION_FIELDS[s].some((f) => f.name === badField))
        : undefined;
      if (badSection && badField) {
        const badNumberMsg = t('hr.pages.employees.cardT2.badNumber', 'Введите число, например 450000 или 450000.50');
        setOpenSections((prev) => ({ ...prev, [badSection]: true }));
        setT2Errors((prev) => ({ ...prev, [`${badSection}.${badField}`]: badNumberMsg }));
        setFieldErrors({});
        setFormError(badNumberMsg);
        return;
      }

      // FastAPI 422 — { detail: [{ loc: ["body","field"], msg, type }, ...] }
      if (data && Array.isArray(data.detail)) {
        const fields: Record<string, string> = {};
        const summary: string[] = [];
        for (const item of data.detail) {
          const loc = Array.isArray(item.loc) ? item.loc : [];
          const field = loc.length ? String(loc[loc.length - 1]) : 'unknown';
          fields[field] = item.msg || String(item);
          summary.push(`${field}: ${item.msg || ''}`);
        }
        setFieldErrors(fields);
        setFormError(summary.join(' • '));
        return;
      }

      setFieldErrors({});
      setFormError(
        (typeof data?.detail === 'string' ? data.detail : null) ||
          err?.message ||
          'Не удалось сохранить сотрудника',
      );
    },
  });

  /** Front-side validation that mirrors the backend's required-field set
   * (first_name / last_name / email / department_id / position_id /
   * hire_date). We block the request before it hits the API so the user
   * gets a fast, field-pinned hint instead of a generic 422. */
  const handleSave = () => {
    const errs: Record<string, string> = {};
    if (!editing) {
      if (form.user === 'none' || !form.user) {
        errs.user = t('hr.pages.employees.errors.userRequired', 'Выберите пользователя');
      }
      if (form.department === 'none') {
        errs.department = t('hr.pages.employees.errors.departmentRequired', 'Выберите отдел');
      }
      if (form.position === 'none') {
        errs.position = t('hr.pages.employees.errors.positionRequired', 'Выберите должность');
      }
      if (!form.date_hired) {
        errs.date_hired = t('hr.pages.employees.errors.hireDateRequired', 'Укажите дату приёма');
      }
    }
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      setFormError(t('hr.pages.employees.errors.fillRequired', 'Заполните обязательные поля'));
      return;
    }
    setFieldErrors({});

    const moneyErrors = validateT2Money(t2Form, editableSections);
    if (Object.keys(moneyErrors).length > 0) {
      // validateT2Money возвращает i18n-КЛЮЧ (модуль cardT2Fields должен
      // оставаться чистым, без t()) — переводим здесь, у формы уже есть
      // useTranslation. Ключ общий с CardT2SectionDialog, поэтому один и тот
      // же текст (и его EN-перевод) показывается в обоих местах.
      const translated = Object.fromEntries(
        Object.entries(moneyErrors).map(([key, i18nKey]) => [
          key,
          t(i18nKey, 'Введите число, например 450000 или 450000.50'),
        ]),
      );
      setT2Errors(translated);
      // Раскрываем секции с ошибками — иначе подсказка не видна под свёрнутым
      // заголовком.
      setOpenSections((prev) => {
        const next = { ...prev };
        for (const key of Object.keys(translated)) next[key.split('.')[0]!] = true;
        return next;
      });
      setFormError(t('hr.pages.employees.errors.fillRequired', 'Заполните обязательные поля'));
      return;
    }
    setT2Errors({});

    setFormError(null);
    saveMutation.mutate();
  };

  const [userPopoverOpen, setUserPopoverOpen] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [newUserForm, setNewUserForm] = useState({ first_name: '', last_name: '', patronymic: '', email: '' });

  const [positionPopoverOpen, setPositionPopoverOpen] = useState(false);
  const [createPositionOpen, setCreatePositionOpen] = useState(false);
  const [newPositionForm, setNewPositionForm] = useState<{
    title: string;
    department_id: string;
    weight: string;
    grade: string;
    description: string;
    hr_level: '' | 'junior' | 'middle' | 'senior' | 'lead';
  }>({ title: '', department_id: '', weight: '100', grade: '1', description: '', hr_level: '' });
  const [newPositionError, setNewPositionError] = useState<string | null>(null);

  const createPositionMutation = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {
        title: newPositionForm.title.trim(),
        department_id: Number(newPositionForm.department_id),
        weight: Number(newPositionForm.weight) || 100,
        grade: Number(newPositionForm.grade) || 1,
        description: newPositionForm.description || undefined,
      };
      if (newPositionForm.hr_level) {
        payload.permissions = { hr_level: newPositionForm.hr_level, permissions: [] };
      }
      return createPosition(payload);
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['hr-positions'] });
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
      setForm((prev) => ({
        ...prev,
        position: String(created.id),
        // Если у новой должности задан отдел и в форме отдел ещё не выбран —
        // подставим его, чтобы создать сотрудника одним движением.
        department: prev.department && prev.department !== 'none'
          ? prev.department
          : (created.department_id ? String(created.department_id) : prev.department),
      }));
      setCreatePositionOpen(false);
      setNewPositionForm({ title: '', department_id: '', weight: '100', grade: '1', description: '', hr_level: '' });
      setNewPositionError(null);
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      setNewPositionError(
        (typeof data?.detail === 'string' ? data.detail : null)
        || (Array.isArray(data?.detail) ? data.detail.map((d: any) => d.msg).join(' • ') : null)
        || err?.message
        || 'Не удалось создать должность',
      );
    },
  });

  const startCreatePosition = () => {
    setPositionPopoverOpen(false);
    setNewPositionError(null);
    setNewPositionForm({
      title: '',
      // Preselect the department picked on the employee form, if any.
      department_id: form.department && form.department !== 'none' ? form.department : '',
      weight: '100',
      grade: '1',
      description: '',
      hr_level: '',
    });
    setCreatePositionOpen(true);
  };

  // ─── Отдел: комбобокс с поиском + создание на месте ───────────────────────
  // Раньше отдел был обычным <Select> без поиска и без возможности завести
  // новый — при том что должность рядом и искалась, и создавалась. Из-за этого
  // сотрудника нельзя было оформить «одним заходом», если отдела ещё нет.
  const [departmentPopoverOpen, setDepartmentPopoverOpen] = useState(false);
  const [createDepartmentOpen, setCreateDepartmentOpen] = useState(false);
  const [newDepartmentForm, setNewDepartmentForm] = useState({ name: '', description: '' });
  const [newDepartmentError, setNewDepartmentError] = useState<string | null>(null);

  const createDepartmentMutation = useMutation({
    mutationFn: () => createDepartment({
      name: newDepartmentForm.name.trim(),
      description: newDepartmentForm.description.trim() || undefined,
    }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['hr-departments'] });
      setForm((prev) => ({ ...prev, department: String(created.id) }));
      setCreateDepartmentOpen(false);
      setNewDepartmentForm({ name: '', description: '' });
      setNewDepartmentError(null);
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
      const detail = e?.response?.data?.detail;
      setNewDepartmentError(
        (typeof detail === 'string' ? detail : null)
        || (Array.isArray(detail)
          ? detail.map((d) => (d as { msg?: string })?.msg).filter(Boolean).join(' • ')
          : null)
        || e?.message
        || 'Не удалось создать отдел',
      );
    },
  });

  const startCreateDepartment = () => {
    setDepartmentPopoverOpen(false);
    setNewDepartmentError(null);
    setNewDepartmentForm({ name: '', description: '' });
    setCreateDepartmentOpen(true);
  };

  const createUserMutation = useMutation({
    mutationFn: async (data: typeof newUserForm) => {
      return createEmployeeUser(data);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['hr-employee-users'] });
      setForm((prev) => ({ ...prev, user: String(data.id) }));
      setCreateUserOpen(false);
      setNewUserForm({ first_name: '', last_name: '', patronymic: '', email: '' });
      setUserPopoverOpen(false);
    },
  });

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? t('hr.pages.employees.edit') : t('hr.pages.employees.new')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-4 md:grid-cols-2">
              {editing ? (
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.employees.fields.user')}
                  <Input
                    value={`${editing.full_name
                      || [editing.last_name, editing.first_name, editing.middle_name].filter(Boolean).join(' ')
                      || editing.email} (${editing.email})`}
                    readOnly
                  />
                </label>
              ) : (
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.employees.fields.user')}
                  <Popover open={userPopoverOpen} onOpenChange={setUserPopoverOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        variant="outline"
                        role="combobox"
                        aria-expanded={userPopoverOpen}
                        className="w-full justify-between font-normal"
                      >
                        {form.user && form.user !== 'none'
                          ? users?.find((u) => String(u.id) === form.user)?.full_name || t('hr.pages.employees.placeholders.selectUser')
                          : t('hr.pages.employees.placeholders.selectUser')}
                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-[400px] p-0" align="start">
                      <Command>
                        <CommandInput placeholder={t('hr.pages.employees.searchUser')} />
                        {canManageUserOptions && (
                          <ComboboxCreateAction
                            icon={UserPlus}
                            label={t('hr.pages.employees.createUser')}
                            onClick={() => {
                              setUserPopoverOpen(false);
                              setCreateUserOpen(true);
                            }}
                          />
                        )}
                        <CommandList>
                          <CommandEmpty>{t('hr.pages.employees.noUserFound')}</CommandEmpty>
                          <CommandGroup>
                            <CommandItem
                              value="none"
                              onSelect={() => {
                                setForm({ ...form, user: 'none' });
                                setUserPopoverOpen(false);
                              }}
                            >
                              <Check className={cn("mr-2 h-4 w-4", form.user === 'none' ? "opacity-100" : "opacity-0")} />
                              {t('hr.pages.employees.placeholders.selectUser')}
                            </CommandItem>
                            {users?.map((u) => (
                              <CommandItem
                                key={u.id}
                                value={`${u.full_name} ${u.email}`}
                                onSelect={() => {
                                  setForm({ ...form, user: String(u.id) });
                                  setUserPopoverOpen(false);
                                }}
                              >
                                <Check className={cn("mr-2 h-4 w-4", form.user === String(u.id) ? "opacity-100" : "opacity-0")} />
                                {u.full_name} ({u.email})
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                </label>
              )}
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.status')}
                <Select value={form.status} onValueChange={(value) => setForm({ ...form, status: value })} disabled={!canWriteBasic}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.employees.placeholders.selectStatus')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">{t('hr.pages.employees.status.active')}</SelectItem>
                    <SelectItem value="inactive">{t('hr.pages.employees.status.inactive', 'Неактивен')}</SelectItem>
                    <SelectItem value="terminated">{t('hr.pages.employees.status.terminated', 'Уволен')}</SelectItem>
                  </SelectContent>
                </Select>
              </label>
            </div>

            {/* Отдел идёт ПЕРЕД должностью: должность принадлежит отделу,
                и выбранный отдел подставляется в форму создания должности —
                обратный порядок заставлял бы возвращаться назад. */}
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.department')}
                <Popover open={departmentPopoverOpen} onOpenChange={setDepartmentPopoverOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      role="combobox"
                      aria-expanded={departmentPopoverOpen}
                      className="w-full justify-between font-normal"
                      disabled={editing ? !canTransferEmployee : !canCreateEmployee}
                    >
                      <span className="truncate">
                        {form.department && form.department !== 'none'
                          ? departments?.find((d) => String(d.id) === form.department)?.name
                            || t('hr.pages.employees.placeholders.selectDepartment')
                          : t('hr.pages.employees.placeholders.selectDepartment')}
                      </span>
                      <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[320px] p-0" align="start">
                    <Command>
                      <CommandInput placeholder={t('hr.pages.employees.searchDepartment', 'Поиск отдела…')} />
                      {(editing ? canTransferEmployee : canCreateEmployee) && (
                        <ComboboxCreateAction
                          icon={Plus}
                          label={t('hr.pages.employees.createDepartment', 'Создать новый отдел')}
                          onClick={startCreateDepartment}
                        />
                      )}
                      <CommandList>
                        <CommandEmpty>{t('hr.pages.employees.noDepartmentFound', 'Отдел не найден')}</CommandEmpty>
                        <CommandGroup>
                          <CommandItem
                            value="none"
                            onSelect={() => {
                              setForm({ ...form, department: 'none' });
                              setDepartmentPopoverOpen(false);
                            }}
                          >
                            <Check className={cn('mr-2 h-4 w-4', form.department === 'none' ? 'opacity-100' : 'opacity-0')} />
                            {t('hr.common.noDepartment')}
                          </CommandItem>
                          {departments?.map((dept) => (
                            <CommandItem
                              key={dept.id}
                              value={dept.name}
                              onSelect={() => {
                                setForm({ ...form, department: String(dept.id) });
                                setDepartmentPopoverOpen(false);
                              }}
                            >
                              <Check className={cn('mr-2 h-4 w-4', form.department === String(dept.id) ? 'opacity-100' : 'opacity-0')} />
                              <span className="flex-1 truncate">{dept.name}</span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
              </label>
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.position')}
                <Popover open={positionPopoverOpen} onOpenChange={setPositionPopoverOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      role="combobox"
                      aria-expanded={positionPopoverOpen}
                      className="w-full justify-between font-normal"
                      disabled={editing ? !canTransferEmployee : !canCreateEmployee}
                    >
                      <span className="flex items-center gap-2 truncate">
                        {form.position && form.position !== 'none' ? (
                          <>
                            <span className="truncate">
                              {positions?.find((p) => String(p.id) === form.position)?.title
                                || t('hr.pages.employees.placeholders.selectPosition')}
                            </span>
                            {positions?.find((p) => String(p.id) === form.position)?.is_system && (
                              <Lock className="h-3 w-3 shrink-0 text-muted-foreground" />
                            )}
                          </>
                        ) : (
                          t('hr.pages.employees.placeholders.selectPosition')
                        )}
                      </span>
                      <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[320px] p-0" align="start">
                    <Command>
                      <CommandInput placeholder={t('hr.pages.employees.searchPosition', 'Поиск должности…')} />
                      {(editing ? canTransferEmployee : canCreateEmployee) && (
                        <ComboboxCreateAction
                          icon={Plus}
                          label={t('hr.pages.employees.createPosition', 'Создать новую должность')}
                          onClick={startCreatePosition}
                        />
                      )}
                      <CommandList>
                        <CommandEmpty>{t('hr.pages.employees.noPositionFound', 'Должность не найдена')}</CommandEmpty>
                        <CommandGroup>
                          <CommandItem
                            value="none"
                            onSelect={() => {
                              setForm({ ...form, position: 'none' });
                              setPositionPopoverOpen(false);
                            }}
                          >
                            <Check className={cn('mr-2 h-4 w-4', form.position === 'none' ? 'opacity-100' : 'opacity-0')} />
                            {t('hr.common.noPosition')}
                          </CommandItem>
                          {positions?.map((pos) => (
                            <CommandItem
                              key={pos.id}
                              value={`${pos.title} ${pos.department_name ?? ''}`}
                              onSelect={() => {
                                setForm({ ...form, position: String(pos.id) });
                                setPositionPopoverOpen(false);
                              }}
                            >
                              <Check className={cn('mr-2 h-4 w-4', form.position === String(pos.id) ? 'opacity-100' : 'opacity-0')} />
                              <span className="flex-1 truncate">{pos.title}</span>
                              {pos.is_system && (
                                <span
                                  className="ml-2 inline-flex items-center gap-1 rounded border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                                  title="Системная должность — нельзя удалить или переименовать"
                                >
                                  <Lock className="h-3 w-3" /> сист.
                                </span>
                              )}
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.phone')}
                <PhoneInput value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} />
              </label>
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.dateHired')}
                <Input type="date" value={form.date_hired} onChange={(e) => setForm({ ...form, date_hired: e.target.value })} />
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.employees.fields.dateDismissed')}
                <Input type="date" value={form.date_dismissed} readOnly={!canTransferEmployee} onChange={(e) => setForm({ ...form, date_dismissed: e.target.value })} />
              </label>
            </div>

            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.notes')}
              <Textarea value={form.notes} readOnly={!canWriteBasic} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </label>

            {visibleSections.map((section) => {
              const canEdit = editableSections.includes(section);
              const title = SECTION_TITLE[section];
              const sectionError = Object.entries(t2Errors)
                .find(([key]) => key.startsWith(`${section}.`))?.[1];
              return (
                <Collapsible
                  key={section}
                  open={openSections[section] ?? false}
                  onOpenChange={(o) => setOpenSections((prev) => ({ ...prev, [section]: o }))}
                  className="rounded-lg border"
                >
                  <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 px-4 py-3 text-sm font-medium hover:bg-muted/40">
                    <span>{t(title.key, title.fallback)}</span>
                    <span className="flex items-center gap-2">
                      {!t2Loaded && (
                        <span className="text-xs font-normal text-muted-foreground">
                          {t('hr.pages.employees.cardT2.loading', 'Загрузка…')}
                        </span>
                      )}
                      {sectionError && (
                        <span className="text-xs font-normal text-destructive">
                          {t('hr.pages.employees.cardT2.sectionHasError', 'Проверьте поля')}
                        </span>
                      )}
                      <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
                    </span>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="grid gap-3 border-t p-4 md:grid-cols-2">
                    {SECTION_FIELDS[section].map((f) => {
                      const errorKey = `${section}.${f.name}`;
                      return (
                        <div key={f.name} className="grid gap-1.5">
                          <Label htmlFor={`t2-${section}-${f.name}`} className="text-sm">
                            {t(f.labelKey, f.labelFallback)}
                          </Label>
                          <Input
                            id={`t2-${section}-${f.name}`}
                            type={f.kind === 'date' ? 'date' : 'text'}
                            inputMode={f.kind === 'money' ? 'decimal' : undefined}
                            readOnly={!canEdit}
                            value={t2Form[section][f.name] ?? ''}
                            onChange={(e) =>
                              setT2Form((prev) => ({
                                ...prev,
                                [section]: { ...prev[section], [f.name]: e.target.value },
                              }))
                            }
                            aria-invalid={Boolean(t2Errors[errorKey])}
                          />
                          {t2Errors[errorKey] && (
                            <p className="text-xs text-destructive">{t2Errors[errorKey]}</p>
                          )}
                        </div>
                      );
                    })}
                  </CollapsibleContent>
                </Collapsible>
              );
            })}

            {formError && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {formError}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {editing && (
                <>
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => {
                      onOpenChange(false);
                      navigate(`/hr/employees/${editing.id}`);
                    }}
                    className="gap-1.5"
                  >
                    <IdCard className="h-4 w-4" />
                    {t('hr.pages.employees.openCard', 'Открыть карточку')}
                  </Button>
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => setShareOpen(true)}
                    className="gap-1.5"
                  >
                    <Share2 className="h-4 w-4" />
                    {t('hr.pages.employees.actions.share', 'Поделиться')}
                  </Button>
                </>
              )}
              <div className="ml-auto flex gap-2">
                <Button variant="outline" onClick={() => onOpenChange(false)}>
                  {t('hr.common.cancel', 'Отмена')}
                </Button>
                <Button onClick={handleSave} disabled={(!editing && form.user === 'none') || saveMutation.isPending}>
                  {saveMutation.isPending ? t('hr.common.saving', 'Сохранение...') : t('hr.common.save', 'Сохранить')}
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {editing && (
        <ShareEmployeeDialog
          open={shareOpen}
          employee={{
            id: editing.id,
            full_name: editing.full_name
              || [editing.last_name, editing.first_name, editing.middle_name].filter(Boolean).join(' ')
              || editing.email,
          }}
          onClose={() => setShareOpen(false)}
        />
      )}

      {/* Create Department Dialog */}
      {/* Создание отдела прямо из карточки сотрудника — чтобы не уходить на
          HR → Отделы и не терять заполненную форму. Полей ровно два: бэкенд
          требует только name, остальное (руководитель, родитель) настраивается
          на своей странице. */}
      <Dialog open={createDepartmentOpen} onOpenChange={setCreateDepartmentOpen}>
        <DialogContent className="max-w-lg" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Building2 className="h-4 w-4" />
              {t('hr.pages.employees.createDepartmentTitle', 'Новый отдел')}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.departments.fields.name', 'Название')}
              <Input
                autoFocus
                value={newDepartmentForm.name}
                onChange={(e) => setNewDepartmentForm({ ...newDepartmentForm, name: e.target.value })}
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.departments.fields.description', 'Описание')}
              <Textarea
                value={newDepartmentForm.description}
                onChange={(e) => setNewDepartmentForm({ ...newDepartmentForm, description: e.target.value })}
                rows={2}
              />
            </label>
            {newDepartmentError && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {newDepartmentError}
              </div>
            )}
            <div className="mt-2 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setCreateDepartmentOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => createDepartmentMutation.mutate()}
                disabled={!newDepartmentForm.name.trim() || createDepartmentMutation.isPending}
              >
                {createDepartmentMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Create Position Dialog */}
      <Dialog open={createPositionOpen} onOpenChange={setCreatePositionOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Briefcase className="h-4 w-4" />
              {t('hr.pages.employees.createPositionTitle', 'Новая должность')}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.positions.fields.title')}
              <Input
                value={newPositionForm.title}
                onChange={(e) => setNewPositionForm({ ...newPositionForm, title: e.target.value })}
                placeholder={t('hr.pages.employees.positionTitlePlaceholder', 'Например, Старший аналитик')}
                autoFocus
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.positions.fields.department')}
              <Select
                value={newPositionForm.department_id || 'none'}
                onValueChange={(v) => setNewPositionForm({ ...newPositionForm, department_id: v === 'none' ? '' : v })}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('hr.pages.positions.placeholders.selectDepartment')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {departments?.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1.5 text-sm">
                {t('hr.pages.employees.weight', 'Вес')}
                <Input
                  type="number"
                  min={0}
                  value={newPositionForm.weight}
                  onChange={(e) => setNewPositionForm({ ...newPositionForm, weight: e.target.value })}
                />
              </label>
              <label className="grid gap-1.5 text-sm">
                {t('hr.pages.employees.grade', 'Грейд')}
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={newPositionForm.grade}
                  onChange={(e) => setNewPositionForm({ ...newPositionForm, grade: e.target.value })}
                />
              </label>
            </div>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.employees.hrLevel', 'Уровень HR-доступа')}
              <Select
                value={newPositionForm.hr_level || 'none'}
                onValueChange={(v) =>
                  setNewPositionForm({
                    ...newPositionForm,
                    hr_level: v === 'none' ? '' : (v as typeof newPositionForm.hr_level),
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Без HR-доступа</SelectItem>
                  <SelectItem value="junior">Junior — базовый просмотр</SelectItem>
                  <SelectItem value="middle">Middle — редактирование своего отдела</SelectItem>
                  <SelectItem value="senior">Senior — полный просмотр + создание</SelectItem>
                  <SelectItem value="lead">Lead — полный доступ</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-1.5 text-sm">
              {t('hr.pages.employees.description', 'Описание')}
              <Textarea
                value={newPositionForm.description}
                onChange={(e) => setNewPositionForm({ ...newPositionForm, description: e.target.value })}
                rows={2}
              />
            </label>
            <p className="text-xs text-muted-foreground">
              Расширенную настройку прав можно сделать позже на странице <strong>HR → Должности</strong>.
            </p>
            {newPositionError && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {newPositionError}
              </div>
            )}
            <div className="flex justify-end gap-2 mt-2">
              <Button variant="outline" onClick={() => setCreatePositionOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => createPositionMutation.mutate()}
                disabled={
                  !newPositionForm.title.trim()
                  || !newPositionForm.department_id
                  || createPositionMutation.isPending
                }
              >
                {createPositionMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Create User Dialog */}
      <Dialog open={createUserOpen} onOpenChange={setCreateUserOpen}>
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('hr.pages.employees.createUserTitle')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.lastName')}
              <Input
                value={newUserForm.last_name}
                onChange={(e) => setNewUserForm({ ...newUserForm, last_name: e.target.value })}
              />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.firstName')}
              <Input
                value={newUserForm.first_name}
                onChange={(e) => setNewUserForm({ ...newUserForm, first_name: e.target.value })}
              />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.patronymic')}
              <Input
                value={newUserForm.patronymic}
                onChange={(e) => setNewUserForm({ ...newUserForm, patronymic: e.target.value })}
              />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.employees.fields.email')}
              <Input
                type="email"
                value={newUserForm.email}
                onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
              />
            </label>
            <div className="flex justify-end gap-2 mt-4">
              <Button variant="outline" onClick={() => setCreateUserOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => createUserMutation.mutate(newUserForm)}
                disabled={!newUserForm.last_name || !newUserForm.first_name || !newUserForm.email || createUserMutation.isPending}
              >
                {createUserMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
            {createUserMutation.isError && (
              <p className="text-red-500 text-sm mt-2">
                {(createUserMutation.error as any)?.response?.data?.detail || t('hr.common.unknownError')}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default EmployeeFormDialog;
