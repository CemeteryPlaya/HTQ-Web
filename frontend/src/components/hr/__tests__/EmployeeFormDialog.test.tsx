/**
 * Форма сотрудника со встроенными секциями Т-2.
 *
 * Главное, что проверяем: секции гейтуются посекционным RBAC, а в payload
 * уходят ТОЛЬКО изменённые секции — иначе «открыл и сохранил» затирало бы
 * чужие данные.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { EmployeeFormDialog } from '@/components/hr/EmployeeFormDialog';

const hasPerm = vi.fn();

vi.mock('@/hooks/useHRLevel', () => ({
  useHRLevel: () => ({
    level: 'lead',
    hasHrAccess: true,
    canWriteBasic: true,
    canCreateEmployee: true,
    canTransferEmployee: true,
    canDeleteEmployee: true,
    canListUserOptions: true,
    canManageUserOptions: true,
    permissions: [],
    hasPerm,
    isLoading: false,
  }),
}));

vi.mock('@/api/hr', () => ({
  fetchDepartments: vi.fn(async () => [{ id: 1, name: 'ИТ' }]),
  fetchPositions: vi.fn(async () => [{ id: 2, title: 'Инженер', department_id: 1 }]),
  fetchEmployeeUsers: vi.fn(async () => [
    { id: 7, full_name: 'Иванов Иван', email: 'ivanov@htq.test', first_name: 'Иван', last_name: 'Иванов' },
  ]),
  fetchCardT2: vi.fn(async () => ({
    financial: { salary: '450000.00', bonus: null, bank_account: null },
    personal: { passport_data: null, inn: null, birth_date: null, birth_place: null, citizenship: 'KZ' },
    certs: { sro_permit_number: null, sro_permit_expiry: null, safety_cert_number: null, safety_cert_expiry: null },
  })),
  createEmployeeWithCard: vi.fn(async () => ({ id: 99 })),
  updateEmployeeWithCard: vi.fn(async () => ({ id: 42 })),
  createDepartment: vi.fn(),
  createPosition: vi.fn(),
  createEmployeeUser: vi.fn(),
  fetchUserPrefill: vi.fn(async () => ({
    id: 7, full_name: 'Иванов Иван', email: 'ivanov@htq.test',
    first_name: 'Иван', last_name: 'Иванов', patronymic: 'Петрович',
    phone: '+7 705 111-22-33', bio: 'Инженер ПТО', avatar_url: '',
  })),
}));

vi.mock('@/components/hr/ShareEmployeeDialog', () => ({
  ShareEmployeeDialog: () => null,
}));

import { createEmployeeWithCard, updateEmployeeWithCard } from '@/api/hr';

const mockCreate = vi.mocked(createEmployeeWithCard);
const mockUpdate = vi.mocked(updateEmployeeWithCard);

const EMPLOYEE = {
  id: 42,
  user_id: 7,
  first_name: 'Иван',
  last_name: 'Иванов',
  email: 'ivanov@htq.test',
  position_id: 2,
  department_id: 1,
  phone: '+77010000000',
  hire_date: '2024-01-09',
  status: 'active',
};

function renderDialog(employee: typeof EMPLOYEE | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <EmployeeFormDialog open employee={employee as never} onOpenChange={vi.fn()} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const save = () => act(() => {
  fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/ }));
});

beforeEach(() => {
  vi.clearAllMocks();
  hasPerm.mockImplementation(() => true);
});

describe('EmployeeFormDialog — секции Т-2', () => {
  it('не показывает секцию без права view', async () => {
    hasPerm.mockImplementation(
      (key: string) => key !== 'hr.card.financial.view' && key !== 'hr.card.financial.edit',
    );
    renderDialog(EMPLOYEE);

    await waitFor(() => expect(screen.getByText(/Личные данные/)).toBeInTheDocument());
    expect(screen.queryByText(/Финансовые данные/)).not.toBeInTheDocument();
  });

  it('скрывает секцию, на которую есть edit, но нет view — иначе сохранение затёрло бы её null-ами', async () => {
    // edit есть, view нет: показывать нечего, а показать пустую форму значит
    // предложить пользователю затереть данные, которых он не видит.
    hasPerm.mockImplementation((key: string) => key !== 'hr.card.financial.view');
    renderDialog(EMPLOYEE);

    await waitFor(() => expect(screen.getByText(/Личные данные/)).toBeInTheDocument());
    expect(screen.queryByText(/Финансовые данные/)).not.toBeInTheDocument();
  });

  it('делает поля read-only при view без edit', async () => {
    hasPerm.mockImplementation((key: string) => key !== 'hr.card.financial.edit');
    renderDialog(EMPLOYEE);

    fireEvent.click(await screen.findByText(/Финансовые данные/));
    expect(await screen.findByLabelText(/Оклад/)).toHaveAttribute('readonly');
  });

  it('шлёт только изменённые секции', async () => {
    renderDialog(EMPLOYEE);

    // Раскрываем «Финансовые данные» и ждём, пока в поле реально появится
    // значение с сервера (450000.00 из мока fetchCardT2) — иначе тест не
    // отличит корректно засеянный t2Initial от несеянного вообще: обе секции
    // «чистые» (financial) или «грязные» (personal) одинаково независимо от
    // того, дождались ли мы GET. Этот waitFor — как раз то ожидание.
    fireEvent.click(await screen.findByText(/Финансовые данные/));
    await screen.findByDisplayValue('450000.00');

    fireEvent.click(await screen.findByText(/Личные данные/));
    await act(async () => {
      fireEvent.change(await screen.findByLabelText(/Гражданство/), { target: { value: 'RU' } });
    });
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const [, payload] = mockUpdate.mock.calls[0]!;
    expect(Object.keys(payload.card_t2 as object)).toEqual(['personal']);
    expect((payload.card_t2 as Record<string, Record<string, unknown>>).personal!.citizenship).toBe('RU');
  });

  it('не кладёт card_t2 в тело, если Т-2 не трогали', async () => {
    renderDialog(EMPLOYEE);

    // Тот же якорь, что и выше: без него тест не заметил бы регрессию, где
    // секция редактируема ДО того, как загрузились её текущие значения.
    fireEvent.click(await screen.findByText(/Финансовые данные/));
    await screen.findByDisplayValue('450000.00');
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate.mock.calls[0]![1]).not.toHaveProperty('card_t2');
  });

  it('не отправляет запрос при нечисловом окладе', async () => {
    renderDialog(EMPLOYEE);

    fireEvent.click(await screen.findByText(/Финансовые данные/));
    await act(async () => {
      fireEvent.change(await screen.findByLabelText(/Оклад/), { target: { value: 'много' } });
    });
    save();

    expect(mockUpdate).not.toHaveBeenCalled();
    expect(screen.getByText(/Введите число/)).toBeInTheDocument();
  });

  it('секция без view никогда не уходит в payload, даже когда другая секция изменена', async () => {
    // Вторая половина инварианта editableSections ⊆ visibleSections: тест
    // «шлёт только изменённые секции» проверяет, что чистая секция не уходит,
    // но editableSections = T2_SECTIONS.filter(edit) (без фильтра по view)
    // прошёл бы его тоже — скрытая секция там не трогается и потому «чистая».
    // Явно проверяем, что financial без view не попадает в payload, даже
    // когда мы редактируем другую (personal) секцию.
    hasPerm.mockImplementation((key: string) => key !== 'hr.card.financial.view');
    renderDialog(EMPLOYEE);

    // financial здесь скрыта (нет view), так что якорить на её значении
    // нельзя — вместо этого ждём загруженное значение самой видимой секции
    // (citizenship: 'KZ' из мока fetchCardT2), прежде чем её трогать. Без
    // этого якоря editableSections = [] (данные ещё не пришли) сделал бы
    // personal.citizenship «недирти» по той же причине, по которой это
    // ловят два теста выше, — тест проходил бы, не проверяя ничего.
    fireEvent.click(await screen.findByText(/Личные данные/));
    await screen.findByDisplayValue('KZ');
    await act(async () => {
      fireEvent.change(await screen.findByLabelText(/Гражданство/), { target: { value: 'RU' } });
    });
    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const [, payload] = mockUpdate.mock.calls[0]!;
    expect(payload.card_t2 as object).not.toHaveProperty('financial');
    expect(Object.keys(payload.card_t2 as object)).toEqual(['personal']);
  });

  it('в режиме создания нет кнопок «Открыть карточку» и «Поделиться»', () => {
    renderDialog(null);

    expect(screen.queryByRole('button', { name: /Открыть карточку/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Поделиться/ })).not.toBeInTheDocument();
  });

  it('в режиме редактирования обе кнопки есть', async () => {
    renderDialog(EMPLOYEE);

    expect(await screen.findByRole('button', { name: /Открыть карточку/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Поделиться/ })).toBeInTheDocument();
  });

  it('создание уходит одним POST с вложенным card_t2', async () => {
    // Это и есть headline user story фичи — завести сотрудника вместе с Т-2
    // за один заход. Без этого теста регрессия, уронившая card_t2 из ветки
    // создания, осталась бы зелёной на фронте (её ловит только бэкенд).
    renderDialog(null);

    // В режиме создания role="combobox" получают 4 элемента: Пользователь,
    // Статус (это тоже Radix Select — он тоже рендерит role="combobox"),
    // Отдел, Должность — в этом порядке в DOM. Статус нам не нужен.
    await waitFor(() => expect(screen.getAllByRole('combobox')).toHaveLength(4));
    const [userCombo, , departmentCombo, positionCombo] = screen.getAllByRole('combobox');

    fireEvent.click(userCombo!);
    fireEvent.click(await screen.findByText(/Иванов Иван/));

    fireEvent.click(departmentCombo!);
    fireEvent.click(await screen.findByText('ИТ'));

    fireEvent.click(positionCombo!);
    fireEvent.click(await screen.findByText('Инженер'));

    // Dialog рендерится в портал document.body, а не в container render()-а —
    // ищем по всему документу.
    const dateInput = document.querySelector('input[type="date"]');
    expect(dateInput).toBeTruthy();
    fireEvent.change(dateInput!, { target: { value: '2024-05-01' } });

    // Заполняем Т-2 поле — секция открыта по умолчанию правами (hasPerm
    // мокнут в true), только раскрываем Collapsible.
    fireEvent.click(await screen.findByText(/Финансовые данные/));
    await act(async () => {
      fireEvent.change(await screen.findByLabelText(/Оклад/), { target: { value: '600000' } });
    });

    save();

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    const [payload] = mockCreate.mock.calls[0]!;
    expect(payload).toMatchObject({
      user_id: 7,
      department_id: 1,
      position_id: 2,
      hire_date: '2024-05-01',
    });
    expect(payload.card_t2).toEqual({
      financial: { salary: '600000', bonus: null, bank_account: null },
    });
  });

  it('403 "Missing permission: hr.card.<section>.edit" разворачивает секцию и подсвечивает ошибку в её заголовке', async () => {
    // Раньше 403 раскрывал секцию, но никогда не populate-ил t2Errors — бейдж
    // в заголовке (sectionHasError) не рисовался, и пользователь видел только
    // сырую английскую строку в общем баннере, не понимая, какая секция
    // виновата.
    mockUpdate.mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'Missing permission: hr.card.financial.edit' } },
    });
    renderDialog(EMPLOYEE);

    // Ждём, пока GET /card/t2 долетит и авторитетный посев (round 1/3
    // эффекта) уже случится, ПРЕЖДЕ чем сохранять — иначе тест ловил бы не
    // «403 не подсвечивает ошибку», а отдельную (не входящую в этот finding)
    // гонку между поздним GET и уже показанной ошибкой: посев сбрасывает
    // t2Errors/openSections на первый показ данных, и он может случиться уже
    // ПОСЛЕ того, как onError их выставил, если кликнуть «Сохранить» раньше,
    // чем прогрузится карточка.
    await waitFor(() => expect(screen.queryByText('Загрузка…')).not.toBeInTheDocument());
    // Секция «Финансовые данные» пока свёрнута — «Оклад» ещё не в DOM.
    expect(screen.queryByLabelText(/Оклад/)).not.toBeInTheDocument();

    save();

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    // Секция раскрылась — поле «Оклад» из CollapsibleContent теперь в DOM
    // (Radix Collapsible размонтирует закрытое содержимое).
    expect(await screen.findByLabelText(/Оклад/)).toBeInTheDocument();
    // И заголовок секции подсвечен бейджем ошибки.
    expect(await screen.findByText('Проверьте поля')).toBeInTheDocument();
  });
});

describe('EmployeeFormDialog — досев из аккаунта', () => {
  /** Открыть комбобокс пользователей и выбрать первого. */
  const pickUser = async () => {
    // Комбобоксов в форме несколько (пользователь, отдел, должность) —
    // пикер пользователя идёт первым.
    fireEvent.click(screen.getAllByRole('combobox')[0]);
    const option = await screen.findByText(/Иванов Иван/);
    await act(async () => {
      fireEvent.click(option);
    });
  };

  it('подставляет телефон и био выбранного аккаунта', async () => {
    renderDialog(null);
    await pickUser();

    await waitFor(() => {
      expect(screen.getAllByText(/Подставлено из аккаунта/).length).toBeGreaterThan(0);
    });
    expect(screen.getByDisplayValue('Инженер ПТО')).toBeInTheDocument();
  });

  it('не затирает то, что HR ввёл руками', async () => {
    // Смена выбранного пользователя не должна молча съедать набранный текст —
    // иначе HR потеряет правку, даже не заметив этого.
    renderDialog(null);
    const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Своя заметка' } });

    await pickUser();

    await waitFor(() => {
      expect(textarea.value).toBe('Своя заметка');
    });
  });
});
