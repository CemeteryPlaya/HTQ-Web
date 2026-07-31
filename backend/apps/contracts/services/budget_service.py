"""CRUD бюджетов и их строк + сборка представления с остатком.

Арифметику не дублирует — «законтрактовано»/«остаток» приходят из
``budget_calc``, единственного места, где они считаются.

Две формы представления одних и тех же данных, и обе нужны:

- ``serialize_budget`` — бюджет ЦЕЛИКОМ, со вложенным списком строк и
  итогом. Это карточка и список бюджетов;
- ``serialize_line`` — одна строка ПЛОСКО, с развёрнутыми администратором,
  программой и годом. Это выпадающий список «источник денег» в форме
  договора: там выбирают программу, а не бюджет, и тащить ради этого
  вложенную структуру незачем.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404

from apps.contracts.models import (
    Administrator,
    Agreement,
    Budget,
    BudgetLine,
    BudgetStatus,
    Program,
)
from apps.contracts.services import budget_calc
from apps.contracts.services.reference_service import (
    ReferenceConflict,
    conflict_as,
    delete_protected,
    get_administrator_or_404,
    get_program_or_404,
    resolve_country_input,
)
from apps.signoff import interface as signoff

# Читающие пути обязаны тянуть эти связи: подписи собираются моделями
# (`Administrator.display_name` лезет в страну, `Program.display_name` — в
# саму программу), и без них каждая строка списка стоит лишних запросов.
_BUDGET_RELATED = ("administrator", "administrator__country")
_LINE_RELATED = ("program", "budget", "budget__administrator",
                 "budget__administrator__country")


# ── Чтение ──────────────────────────────────────────────────────────────

def list_budgets(*, administrator_id: int | None = None,
                 period_year: int | None = None, status: str | None = None,
                 approval_state: str | None = None) -> list[dict]:
    """Список бюджетов, каждый со своими строками и итогом.

    Занятость ВСЕХ строк всех бюджетов берётся ОДНИМ агрегирующим запросом
    (``budget_calc.committed_map``), а не по запросу на строку — иначе
    двадцать бюджетов по пять программ означали бы сто с лишним запросов.

    ``approval_state`` — фильтр, а не жёсткое условие: список показывает и
    несогласованные бюджеты, иначе автор не увидел бы собственную заявку,
    пока она идёт по маршруту.
    """
    query = (Budget.objects.select_related(*_BUDGET_RELATED)
             .prefetch_related("lines__program"))
    if administrator_id is not None:
        query = query.filter(administrator_id=administrator_id)
    if period_year is not None:
        query = query.filter(period_year=period_year)
    if status is not None:
        query = query.filter(status=status)
    if approval_state is not None:
        query = query.filter(approval_state=approval_state)

    budgets = list(query)
    committed = budget_calc.committed_map(
        [line.pk for budget in budgets for line in budget.lines.all()])
    return [serialize_budget(budget, committed=committed) for budget in budgets]


def get_budget_or_404(budget_id: int) -> Budget:
    budget = (Budget.objects.select_related(*_BUDGET_RELATED)
              .prefetch_related("lines__program")
              .filter(pk=budget_id).first())
    if budget is None:
        raise Http404("Бюджет не найден")
    return budget


def list_lines(*, administrator_id: int | None = None, program_id: int | None = None,
               period_year: int | None = None, budget_id: int | None = None,
               approval_state: str | None = None) -> list[dict]:
    """Плоский список строк — то, из чего форма договора собирает свои
    каскадные списки «администратор → программа → год».

    ``approval_state`` фильтрует по состоянию РОДИТЕЛЬСКОГО бюджета: у
    строки своего согласования нет. Форма договора запрашивает
    ``approval_state=approved`` — несогласованный бюджет источником денег не
    бывает (та же проверка на бэкенде: ``agreement_service._validate_context``).
    """
    query = BudgetLine.objects.select_related(*_LINE_RELATED)
    if budget_id is not None:
        query = query.filter(budget_id=budget_id)
    if administrator_id is not None:
        query = query.filter(budget__administrator_id=administrator_id)
    if program_id is not None:
        query = query.filter(program_id=program_id)
    if period_year is not None:
        query = query.filter(budget__period_year=period_year)
    if approval_state is not None:
        query = query.filter(budget__approval_state=approval_state)

    lines = list(query)
    committed = budget_calc.committed_map([line.pk for line in lines])
    return [serialize_line(line, committed=committed.get(line.pk, budget_calc.ZERO))
            for line in lines]


def get_line_or_404(line_id: int) -> BudgetLine:
    line = (BudgetLine.objects.select_related(*_LINE_RELATED)
            .filter(pk=line_id).first())
    if line is None:
        raise Http404("Строка бюджета не найдена")
    return line


# ── Сериализация ────────────────────────────────────────────────────────

def serialize_budget(budget: Budget, *, committed: dict | None = None) -> dict:
    """Бюджет со строками и итогом.

    ``committed`` — общий на весь список результат ``committed_map``;
    ``totals_for_budget`` и строки берут из него свои куски, так что на
    бюджет не приходится ни одного дополнительного запроса.
    """
    lines = list(budget.lines.all())
    if committed is None:
        committed = budget_calc.committed_map([line.pk for line in lines])
    totals = budget_calc.totals_for_budget(lines, committed=committed)

    return {
        "id": budget.pk,
        "administrator_id": budget.administrator_id,
        # Подпись администратора («проект страна») собирает сама модель —
        # см. Administrator.display_name.
        "administrator_name": budget.administrator.display_name,
        "period_year": budget.period_year,
        "currency": budget.currency,
        "status": budget.status,
        "approval_state": budget.approval_state,
        "note": budget.note,
        # «Выделено» — это СУММА строк, а не хранимая колонка.
        "allocated": totals["allocated"],
        "committed": totals["committed"],
        "remaining": totals["remaining"],
        "lines": [
            _serialize_line_inner(
                line, committed=committed.get(line.pk, budget_calc.ZERO))
            for line in lines
        ],
        "created_at": budget.created_at,
        "updated_at": budget.updated_at,
    }


def _serialize_line_inner(line: BudgetLine, *, committed) -> dict:
    """Строка внутри карточки бюджета: без администратора, года и валюты —
    они уже написаны на самом бюджете, и повторять их в каждой строке
    значило бы раздувать ответ ради данных, которые вызывающий уже держит."""
    totals = budget_calc.totals_for(line, committed=committed)
    return {
        "id": line.pk,
        "budget_id": line.budget_id,
        "program_id": line.program_id,
        # Подпись программы («код название») тоже собирает модель.
        "program_name": line.program.display_name,
        "expense_item": line.program.expense_item,
        "amount": line.amount,
        "note": line.note,
        "committed": totals["committed"],
        "remaining": totals["remaining"],
    }


def serialize_line(line: BudgetLine, *, committed=None) -> dict:
    """Строка ПЛОСКО — с развёрнутым контекстом бюджета.

    Нужна там, где строка показывается вне своей карточки и сама по себе:
    выпадающий список источников денег, карточка договора. Год, валюта,
    администратор и состояние согласования читаются с родителя — своих
    колонок под них у строки нет.
    """
    if committed is None:
        committed = budget_calc.committed_for(line.pk)
    budget = line.budget
    return {
        **_serialize_line_inner(line, committed=committed),
        "administrator_id": budget.administrator_id,
        "administrator_name": budget.administrator.display_name,
        "period_year": budget.period_year,
        "currency": budget.currency,
        "budget_status": budget.status,
        "approval_state": budget.approval_state,
    }


# ── Создание ────────────────────────────────────────────────────────────

@transaction.atomic
def create_budget_full(*, administrator, programs, period_year,
                       currency: str = "KZT", note: str = "") -> Budget:
    """Создать бюджет со строками и недостающими справочниками — одной транзакцией.

    ``administrator`` — это ``schemas.AdministratorInput``, ``programs`` —
    список ``schemas.BudgetProgramLine`` (программа + своя сумма + своё
    примечание). Ссылки на справочники в каждом из них задаются либо ``id``
    существующей записи, либо полями для её заведения. Так работает форма
    «заявка на бюджет»: заполняющий не должен сначала уходить в три
    отдельных справочника и возвращаться.

    Всё внутри одного ``atomic``, и это «всё или ничего» на весь бюджет:
    если не пройдёт хотя бы одна строка, откатятся и остальные, и
    заведённые по пути страна/администратор/программы. Иначе неудачная
    попытка оставляла бы полубюджет — часть программ профинансирована,
    часть нет, — и понять, чего в нём не хватает, можно было бы только
    сверяя с бумажной заявкой.

    Совпадения переиспользуются, а не дублируются (``get_or_create``): двое
    заполняющих, независимо вписавших «Казахстан», должны получить одну
    страну, а не две с одинаковым названием.
    """
    administrator_obj = _resolve_administrator(administrator)

    with conflict_as(f"У «{administrator_obj.display_name}» уже есть бюджет на "
                     f"{period_year} год в валюте {currency} — дополните его, "
                     f"а не заводите второй"):
        budget = Budget.objects.create(
            administrator=administrator_obj, period_year=period_year,
            currency=currency, note=note,
        )

    for line in programs:
        program_obj = _resolve_program(line.program)
        # Конфликтная строка называется поимённо: их в бюджете несколько, и
        # «программа уже есть» без имени не говорит, какую убирать из формы.
        with conflict_as(f"Программа «{program_obj.display_name}» уже есть "
                         f"в этом бюджете"):
            BudgetLine.objects.create(budget=budget, program=program_obj,
                                      amount=line.amount, note=line.note)

    # Заново — со строками в кэше prefetch'а, иначе сериализация карточки
    # сходит за ними в БД ещё раз.
    return get_budget_or_404(budget.pk)


def _resolve_administrator(data) -> Administrator:
    if data.id is not None:
        return get_administrator_or_404(data.id)
    country = resolve_country_input(data.country)
    # Ключ совпадения — проект + страна, и это ВСЯ идентичность записи после
    # снятия ФИО: один проект в одной стране — один администратор бюджета.
    # Тот же проект в другой стране — отдельная запись с отдельными
    # бюджетами, поэтому страна из ключа не убирается.
    administrator, _ = Administrator.objects.get_or_create(
        project_name=data.project_name.strip(),
        country=country,
    )
    return administrator


def _resolve_program(data) -> Program:
    if data.id is not None:
        return get_program_or_404(data.id)
    program, _ = Program.objects.get_or_create(
        name=data.name.strip(),
        expense_item=data.expense_item.strip(),
        defaults={"code": data.code},
    )
    return program


# ── Правка ──────────────────────────────────────────────────────────────

def update_budget(budget_id: int, **fields) -> Budget:
    """Правка шапки бюджета. Строки правятся своими операциями."""
    budget = get_budget_or_404(budget_id)
    budget.assert_editable()

    if fields.get("administrator_id") is not None:
        get_administrator_or_404(fields["administrator_id"])

    new_currency = fields.get("currency")
    if new_currency is not None and new_currency != budget.currency:
        if _has_agreements(budget):
            raise ReferenceConflict(
                "Нельзя сменить валюту бюджета, к строкам которого уже "
                "привязаны договоры"
            )

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(budget, key, fields[key])
    if changed:
        with conflict_as("У этого администратора уже есть бюджет на этот год "
                         "в этой валюте"):
            budget.save()
    return get_budget_or_404(budget.pk)


def _has_agreements(budget: Budget) -> bool:
    """Есть ли у бюджета хоть один договор — по любой из его строк."""
    return Agreement.objects.filter(budget_line__budget_id=budget.pk).exists()


def add_line(budget_id: int, *, program_id: int, amount, note: str = "") -> BudgetLine:
    """Добавить программу в существующий бюджет.

    Отдельная операция, а не правка всего бюджета целиком: дополнить
    утверждённый бюджет новой программой — обычное дело, и переотправлять
    ради этого форму со всеми уже существующими строками значило бы рисковать
    затереть чужие правки.
    """
    budget = get_budget_or_404(budget_id)
    budget.assert_editable()
    program = get_program_or_404(program_id)
    with conflict_as(f"Программа «{program.display_name}» уже есть в этом бюджете"):
        return BudgetLine.objects.create(budget=budget, program=program,
                                         amount=amount, note=note)


def _assert_line_editable(line: BudgetLine) -> None:
    """Строку запирает согласование РОДИТЕЛЬСКОГО бюджета.

    Сама ``BudgetLine`` не ``Approvable`` и своего ``approval_state`` не
    имеет: согласуют бюджет целиком, а строки — его содержимое. Поправить
    строку бюджета, который сейчас лежит у согласующих, — ровно та же
    подмена документа, что и правка его шапки.
    """
    line.budget.assert_editable()


def update_line(line_id: int, **fields) -> BudgetLine:
    line = get_line_or_404(line_id)
    _assert_line_editable(line)

    if fields.get("program_id") is not None:
        get_program_or_404(fields["program_id"])

    new_amount = fields.get("amount")
    if new_amount is not None:
        # Урезать строку ниже уже законтрактованного нельзя: остаток стал бы
        # отрицательным, и «свободно −300 000 ₸» — это не состояние, из
        # которого система умеет выходить. Расторгните лишние договоры
        # раньше, чем урезать строку.
        committed = budget_calc.committed_for(line.pk)
        if new_amount < committed:
            raise ReferenceConflict(
                f"Нельзя уменьшить строку до {new_amount}: "
                f"уже законтрактовано {committed}"
            )

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(line, key, fields[key])
    if changed:
        with conflict_as("Эта программа уже есть в бюджете"):
            line.save()
    return get_line_or_404(line.pk)


def delete_line(line_id: int) -> None:
    line = get_line_or_404(line_id)
    _assert_line_editable(line)
    delete_protected(line,
                     "К строке привязаны договоры — расторгните их или "
                     "уменьшите сумму вместо удаления")


# ── Согласование и удаление ─────────────────────────────────────────────

def submit_for_approval(budget_id: int, *, actor_id: int | None = None) -> dict:
    """Отправить бюджет на согласование — ЦЕЛИКОМ, со всеми строками.

    Отдельные строки на согласование не отправляются: согласовать половину
    бюджета нельзя, в этом и был смысл контейнера.

    Штатный путь отправки — общий ``POST /api/signoff/v1/processes`` админский
    и предметных проверок не делает. Здесь их две: закрытый бюджет
    согласовывать нечего (его жизненный цикл завершён), и пустой тоже —
    согласующему нечего утверждать, а «согласованный бюджет на 0 ₸» потом
    молча пропустит добавление любых сумм уже после утверждения.

    Повторная отправка уже идущего согласования отбивается самим движком
    (``AlreadyInApproval`` → 409): частичный уникальный индекс на
    ``(subject_type, subject_id)`` при ``state = pending``.
    """
    budget = get_budget_or_404(budget_id)
    if budget.status != BudgetStatus.ACTIVE:
        raise ReferenceConflict(
            "Закрытый бюджет на согласование не отправляется")
    if not budget.lines.all():
        raise ReferenceConflict(
            "В бюджете нет ни одной программы — согласовывать нечего")
    return signoff.start_process(subject_type=Budget.SIGNOFF_SUBJECT_TYPE,
                                 subject_id=budget.pk, initiator_id=actor_id,
                                 enrich=True)


def delete_budget(budget_id: int) -> None:
    """Удалить бюджет вместе со строками.

    Строки уходят каскадом, но строка с договорами держится ``PROTECT``'ом
    — Django поднимет ``ProtectedError`` на сборе каскада, и бюджет
    останется цел.
    """
    budget = get_budget_or_404(budget_id)
    budget.assert_editable()
    delete_protected(budget,
                     "К строкам бюджета привязаны договоры — закройте бюджет "
                     "(status=closed) вместо удаления")
