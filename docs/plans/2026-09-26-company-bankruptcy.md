# Банкротство компании с преемником — план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** одна операция закрывает компанию с преемником: участники с действующей учёткой получают членство в преемнике, `successor` выставлен, компания уходит в архив «только чтение».

**Architecture:** сервис `lifecycle.bankrupt_company` (единственная точка логики) поверх `membership_service.grant_membership` и `archive_company`; над ним — команда `company_bankrupt`, платформенная ручка `POST companies/<slug>/bankrupt` и панель в реестре компаний. Техника, договоры и карточки `hr` не переносятся (решение заказчика).

**Tech Stack:** Django 5.2.7, `htqweb.http.api_view`, pytest-django на `:55432`, React + vitest.

**Spec:** [2026-09-26-company-bankruptcy-spec.md](2026-09-26-company-bankruptcy-spec.md).

## Global Constraints

- Зона второго разработчика не правится: `backend/apps/contracts/**`, `backend/apps/signoff/**`, `frontend/src/pages/{contracts,signoff}/**`.
- Ветки/worktree не создавать; работать в `sanzhar`; `git add` поимённо, никогда `-A`/`.`; `git stash`/`checkout`/`restore`/`reset` не использовать; не стейджить `.codebase-memory/`, `.cursor/`, `.zed/`, `.github/copilot-instructions.md`, `.github/instructions/`.
- pytest — только тестировщик, форграунд, Bash `timeout: 600000`, одна сессия за раз, ≤10 мин на команду; из `backend/`: `../.venv/Scripts/python.exe -m pytest … -q -p no:cacheprovider`.
- Межаппное — только через `apps.<x>.interface`.
- Коды ошибок: `SuccessorInvalid` — 422 `successor_invalid`; `SuccessorConflict` — 409 `successor_conflict`; неизвестная компания — 404 `not_found` (существующий `CompanyNotFound`).
- Тексты ошибок: «Компания не может быть собственным преемником»; «Преемник должен быть действующей компанией»; «У компании {slug} уже есть преемник {other}».
- Миграций БД нет: `Company.successor` уже в модели.
- Фронт: `t('<ключ>', '<русский текст>')`, ключи `companies.bankruptcy.*` в `frontend/public/locales/{ru,en}/translation.json`; `npx tsc --noEmit -p tsconfig.app.json` ≤ 148, `npx vitest run` ≤ 8 известных падений, `npm run lint` ≤ 376.
- Коммиты на русском, последняя строка `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; не пушить.

## Review Focus

- **Участник банкрота уже состоит в преемнике** — членство не задваивается, базовая роль ему не довыдаётся (снятая человеком роль не возвращается). Тест — задача 1, `test_existing_member_of_successor_is_not_touched`.
- **Учётка участника отключена** — членство в преемнике ему не выдаётся. Тест — задача 1, `test_inactive_account_is_not_carried_over`.
- **Повтор операции после сбоя на середине** (та же пара) — довыдаёт недостающее, 200, без ошибки «уже в архиве». Тест — задача 1, `test_repeat_with_same_successor_is_idempotent`.
- **Предпросмотр в реестре** — ничего не меняет в базе. Тест — задача 1, `test_dry_run_changes_nothing`; задача 3 — предпросмотр зовёт `dry_run: true`.
- **Банкрот восстановлен из архива** — преемник снят, выданные членства остаются. Тест — задача 1, `test_restore_clears_successor_and_keeps_memberships`.

## Порядок исполнения (параллельная схема)

| Волна | Разработчик A | Разработчик B |
|---|---|---|
| 1 | Задача 1 — сервис и команда | Задача 2 — HTTP и `successor_slug` |
| 2 | Задача 4 — документы | Задача 3 — фронт |

Файлы задач одной волны не пересекаются. Тесты задачи 2 зовут сервис задачи 1 — тестировщик гоняет их после коммита задачи 1.

---

### Task 1: Сервис `bankrupt_company` и команда `company_bankrupt`

**Files:**
- Modify: `backend/apps/companies/services/lifecycle.py` (новые ошибки, `BankruptcyResult`, `bankrupt_company`; `restore_company` снимает `successor`; докстринг модуля)
- Create: `backend/apps/companies/management/commands/company_bankrupt.py`
- Modify: докстринги `backend/apps/companies/management/commands/company_archive.py` (абзац «⚠️ Адаптация под подпроект 4») и `company_restore.py` (строка про «банкротство/преемник — см. докстринг»)
- Test: `backend/apps/companies/tests/test_bankruptcy.py`

**Interfaces:**
- Produces: `lifecycle.SuccessorInvalid` (status 422, code `"successor_invalid"`), `lifecycle.SuccessorConflict` (409, `"successor_conflict"`), `lifecycle.BankruptcyResult` (frozen dataclass: `company: Company`, `successor: Company`, `members_total: int`, `members_granted: int`, `members_already: int`, `archived: bool`, `dry_run: bool`), `lifecycle.bankrupt_company(slug: str, successor_slug: str, *, dry_run: bool = False) -> BankruptcyResult`.

- [ ] **Step 1: Падающие тесты** — `backend/apps/companies/tests/test_bankruptcy.py`:

```python
"""Банкротство с преемником (спека docs/plans/2026-09-26-company-bankruptcy-spec.md).

Поверх ``two_company_schemas``: архив пересобирает сводки холдинга, а им
нужны настоящие схемы. Схему ``holding`` фикстура из conftest.py не знает —
сносим её на выходе, как ``two_companies`` в test_company_archive.py.
"""

import io

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.access.models import RoleAssignment
from apps.companies.models import Company, CompanyMembership, CompanyStatus
from apps.companies.services import lifecycle
from apps.users.models import User, UserStatus


@pytest.fixture
def pair(two_company_schemas):
    try:
        yield list(two_company_schemas)  # [bankrupt, successor]
    finally:
        with connection.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _user(username, status=UserStatus.ACTIVE):
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status)


def _member(slug, user, *, is_default=False):
    return CompanyMembership.objects.create(
        company=Company.objects.get(slug=slug), user_id=user.id, is_default=is_default)


def _member_ids(slug):
    return set(CompanyMembership.objects.filter(company__slug=slug)
               .values_list("user_id", flat=True))


@pytest.mark.django_db
def test_members_move_to_successor_with_basic_role(pair):
    dead, heir = pair
    alice, bob = _user("alice"), _user("bob")
    _member(dead, alice)
    _member(dead, bob)

    result = lifecycle.bankrupt_company(dead, heir)

    assert _member_ids(heir) == {alice.id, bob.id}
    assert RoleAssignment.objects.filter(company_slug=heir, user_id=alice.id,
                                         role__code="employee-basic").exists()
    assert (result.members_total, result.members_granted, result.members_already) == (2, 2, 0)
    assert result.archived is True and result.dry_run is False
    company = Company.objects.get(slug=dead)
    assert company.status == CompanyStatus.ARCHIVED
    assert company.successor.slug == heir


@pytest.mark.django_db
def test_existing_member_of_successor_is_not_touched(pair):
    """Уже состоящий в преемнике: членство не задваивается, роль не
    довыдаётся — снятая человеком роль повторным grant'ом не возвращается."""
    dead, heir = pair
    carol = _user("carol")
    _member(dead, carol)
    _member(heir, carol)  # напрямую, без grant — роли у неё в heir нет

    result = lifecycle.bankrupt_company(dead, heir)

    assert CompanyMembership.objects.filter(company__slug=heir, user_id=carol.id).count() == 1
    assert not RoleAssignment.objects.filter(company_slug=heir, user_id=carol.id).exists()
    assert (result.members_granted, result.members_already) == (0, 1)


@pytest.mark.django_db
def test_inactive_account_is_not_carried_over(pair):
    dead, heir = pair
    gone = _user("gone", status=UserStatus.SUSPENDED)
    _member(dead, gone)

    result = lifecycle.bankrupt_company(dead, heir)

    assert gone.id not in _member_ids(heir)
    assert result.members_total == 0


@pytest.mark.django_db
def test_default_company_flag_moves_to_successor(pair):
    dead, heir = pair
    dora, eve = _user("dora"), _user("eve")
    _member(dead, dora, is_default=True)
    _member(dead, eve)

    lifecycle.bankrupt_company(dead, heir)

    assert CompanyMembership.objects.get(company__slug=heir, user_id=dora.id).is_default is True
    assert CompanyMembership.objects.get(company__slug=heir, user_id=eve.id).is_default is False


@pytest.mark.django_db
def test_dry_run_changes_nothing(pair):
    dead, heir = pair
    frank = _user("frank")
    _member(dead, frank)

    result = lifecycle.bankrupt_company(dead, heir, dry_run=True)

    assert result.dry_run is True
    assert (result.members_total, result.members_granted, result.members_already) == (1, 1, 0)
    assert result.archived is False
    assert _member_ids(heir) == set()
    company = Company.objects.get(slug=dead)
    assert company.status == CompanyStatus.ACTIVE and company.successor is None


@pytest.mark.django_db
def test_company_cannot_be_its_own_successor(pair):
    dead, _heir = pair
    with pytest.raises(lifecycle.SuccessorInvalid) as exc:
        lifecycle.bankrupt_company(dead, dead)
    assert (exc.value.status, exc.value.code) == (422, "successor_invalid")


@pytest.mark.django_db
def test_archived_successor_is_refused(pair):
    dead, heir = pair
    Company.objects.filter(slug=heir).update(status=CompanyStatus.ARCHIVED)
    with pytest.raises(lifecycle.SuccessorInvalid):
        lifecycle.bankrupt_company(dead, heir)


@pytest.mark.django_db
def test_unknown_company_or_successor_is_not_found(pair):
    dead, heir = pair
    with pytest.raises(lifecycle.CompanyNotFound):
        lifecycle.bankrupt_company("no-such", heir)
    with pytest.raises(lifecycle.CompanyNotFound):
        lifecycle.bankrupt_company(dead, "no-such")


@pytest.mark.django_db
def test_other_successor_is_a_conflict(pair):
    dead, heir = pair
    third = Company.objects.create(slug="t-third", name="t-third", kind="service")
    Company.objects.filter(slug=dead).update(successor=third)
    with pytest.raises(lifecycle.SuccessorConflict) as exc:
        lifecycle.bankrupt_company(dead, heir)
    assert (exc.value.status, exc.value.code) == (409, "successor_conflict")


@pytest.mark.django_db
def test_repeat_with_same_successor_is_idempotent(pair):
    """Повтор после сбоя на середине: та же пара довыдаёт недостающее."""
    dead, heir = pair
    gina, hank = _user("gina"), _user("hank")
    _member(dead, gina)
    lifecycle.bankrupt_company(dead, heir)
    _member(dead, hank)  # появился в архиве позже (например, перенос не дошёл)

    result = lifecycle.bankrupt_company(dead, heir)

    assert _member_ids(heir) == {gina.id, hank.id}
    assert (result.members_granted, result.members_already, result.archived) == (1, 1, False)


@pytest.mark.django_db
def test_already_archived_company_without_successor_can_be_closed(pair):
    dead, heir = pair
    lifecycle.archive_company(dead)

    result = lifecycle.bankrupt_company(dead, heir)

    assert result.archived is False
    assert Company.objects.get(slug=dead).successor.slug == heir


@pytest.mark.django_db
def test_restore_clears_successor_and_keeps_memberships(pair):
    dead, heir = pair
    ivan = _user("ivan")
    _member(dead, ivan)
    lifecycle.bankrupt_company(dead, heir)

    lifecycle.restore_company(dead)

    company = Company.objects.get(slug=dead)
    assert company.status == CompanyStatus.ACTIVE and company.successor is None
    assert ivan.id in _member_ids(heir)


@pytest.mark.django_db
def test_command_prints_summary_and_supports_dry_run(pair):
    dead, heir = pair
    _member(dead, _user("jane"))
    out = io.StringIO()

    call_command("company_bankrupt", "--company", dead, "--successor", heir,
                 "--dry-run", stdout=out)
    assert "получат доступ" in out.getvalue()
    assert Company.objects.get(slug=dead).status == CompanyStatus.ACTIVE

    out = io.StringIO()
    call_command("company_bankrupt", "--company", dead, "--successor", heir, stdout=out)
    assert Company.objects.get(slug=dead).status == CompanyStatus.ARCHIVED
    assert "в архив" in out.getvalue()


@pytest.mark.django_db
def test_command_error_is_a_command_error(pair):
    dead, _heir = pair
    with pytest.raises(CommandError, match="собственным преемником"):
        call_command("company_bankrupt", "--company", dead, "--successor", dead)
```

- [ ] **Step 2: Прогнать — падают** (тестировщик): `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_bankruptcy.py -q -p no:cacheprovider` → FAIL (нет `bankrupt_company`).

- [ ] **Step 3: Сервис** — в `backend/apps/companies/services/lifecycle.py`:

Импорты — добавить к существующим:

```python
import logging
from dataclasses import dataclass

from apps.companies.models import CompanyMembership  # к импорту моделей
from apps.companies.services import membership_service  # к импорту сервисов
```

(`membership_service` в том же пакете — не межаппный импорт.) `logger = logging.getLogger(__name__)` после импортов.

Ошибки — после `LastActiveCompany`:

```python
class SuccessorInvalid(LifecycleError):
    status = 422
    code = "successor_invalid"


class SuccessorConflict(LifecycleError):
    status = 409
    code = "successor_conflict"
```

После `restore_company`:

```python
@dataclass(frozen=True)
class BankruptcyResult:
    company: Company
    successor: Company
    members_total: int
    members_granted: int
    members_already: int
    archived: bool
    dry_run: bool


def bankrupt_company(slug: str, successor_slug: str, *,
                     dry_run: bool = False) -> BankruptcyResult:
    """Закрыть компанию с преемником (спека docs/plans/2026-09-26-company-bankruptcy-spec.md).

    Переносится только членство (решение заказчика 26.09): каждый участник с
    ДЕЙСТВУЮЩЕЙ учёткой получает членство в преемнике через
    ``grant_membership`` — единственную точку логики членства, она же выдаёт
    новому членству ``employee-basic``. Карточки ``hr``, техника и договоры
    остаются в архиве банкрота. Флаг «по умолчанию» переезжает: иначе после
    входа человека вело бы по алфавиту.

    Идемпотентно для той же пары: повтор довыдаёт недостающие членства (сбой
    на середине не требует ручной уборки). Уже архивную компанию без
    преемника закрыть можно — архив мог случиться раньше решения о
    преемнике; с ДРУГИМ преемником — ``SuccessorConflict``.
    """
    from apps.companies.interface import active_member_ids

    company = get_company_or_raise(slug)
    successor = get_company_or_raise(successor_slug)
    if successor.pk == company.pk:
        raise SuccessorInvalid("Компания не может быть собственным преемником")
    if successor.status != CompanyStatus.ACTIVE:
        raise SuccessorInvalid("Преемник должен быть действующей компанией")
    if company.successor_id is not None and company.successor_id != successor.pk:
        raise SuccessorConflict(
            f"У компании {slug} уже есть преемник {company.successor.slug}")

    member_ids = active_member_ids(slug)
    already = set(CompanyMembership.objects
                  .filter(company=successor, user_id__in=member_ids)
                  .values_list("user_id", flat=True))
    to_grant = [uid for uid in member_ids if uid not in already]

    if dry_run:
        return BankruptcyResult(company, successor, len(member_ids), len(to_grant),
                                len(already), archived=False, dry_run=True)

    defaults = set(CompanyMembership.objects
                   .filter(company=company, user_id__in=to_grant, is_default=True)
                   .values_list("user_id", flat=True))
    with transaction.atomic():
        for uid in to_grant:
            membership_service.grant_membership(successor, uid,
                                                is_default=uid in defaults)
        if company.successor_id != successor.pk:
            company.successor = successor
            company.save(update_fields=["successor", "updated_at"])
    # Архив — после переноса и вне транзакции переноса: он пересобирает
    # сводки холдинга (DDL), и его сбой не должен откатывать уже выданные
    # доступы — повтор той же пары довершит работу. Гейт LastActiveCompany
    # не сработает: преемник действующий.
    company, archived = archive_company(slug)
    logger.info("company_bankrupt slug=%s successor=%s granted=%d already=%d",
                slug, successor.slug, len(to_grant), len(already))
    return BankruptcyResult(company, successor, len(member_ids), len(to_grant),
                            len(already), archived=archived, dry_run=False)
```

(Проверь, что у `Company` есть поле `updated_at` — `archive_company` его уже пишет в `update_fields`; если нет — убери из `update_fields`.)

`restore_company` — в `save(update_fields=[...])` добавить `"successor"` и перед ним `company.successor = None` с комментарием: «Восстановленная компания живёт сама по себе — связь с преемником теряет смысл; выданные преемнику членства не отзываются (спека §3)». Докстринг модуля: дописать абзац про `bankrupt_company` (что переносится, что нет, ссылка на спеку).

- [ ] **Step 4: Команда** — `backend/apps/companies/management/commands/company_bankrupt.py`:

```python
"""Закрыть компанию с преемником: членства → преемник, компания → архив.

Тонкая обёртка над ``apps.companies.services.lifecycle.bankrupt_company`` —
та же операция, что кнопка «Банкротство…» в реестре компаний. Спека:
docs/plans/2026-09-26-company-bankruptcy-spec.md. Сначала ``--dry-run``:
сводка показывает, сколько людей получат доступ к преемнику.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.companies.services import lifecycle


class Command(BaseCommand):
    help = ("Банкротство компании: участники получают членство в преемнике, "
            "компания уходит в архив (только чтение).")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="slug закрываемой компании")
        parser.add_argument("--successor", required=True, help="slug компании-преемника")
        parser.add_argument("--dry-run", action="store_true",
                            help="только посчитать, ничего не менять")

    def handle(self, *args, **opts):
        try:
            result = lifecycle.bankrupt_company(
                opts["company"], opts["successor"], dry_run=opts["dry_run"])
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        summary = (f"Участников с действующей учёткой: {result.members_total}; "
                   f"получат доступ к {result.successor.slug}: {result.members_granted}; "
                   f"уже состоят: {result.members_already}.")
        if result.dry_run:
            self.stdout.write(f"Сухой прогон. {summary} Ничего не изменено.")
            return
        tail = ("Компания переведена в архив." if result.archived
                else "Компания уже была в архиве.")
        self.stdout.write(self.style.SUCCESS(
            f"{summary} Преемник {result.company.slug} → {result.successor.slug}. {tail}"))
```

Внимание: тест ищет в выводе «в архив» — «Компания переведена в архив.» его содержит.

- [ ] **Step 5: Докстринги** — `company_archive.py`, абзац «⚠️ **Адаптация под подпроект 4**…» → «Банкротство с преемником — отдельная команда ``company_bankrupt`` (``lifecycle.bankrupt_company``): переносит членства и тоже заканчивается архивом; эта команда только архивирует.» `company_restore.py` — строку про «банкротство/преемник — см. докстринг» → «восстановление снимает и преемника (``lifecycle.restore_company``)».

- [ ] **Step 6: Прогнать — проходят** (тестировщик): `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_bankruptcy.py apps/companies/tests/test_lifecycle.py apps/companies/tests/test_company_archive.py apps/core/tests/test_app_isolation.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 7: Коммит** (контроллер): `feat(companies): банкротство с преемником — сервис и команда company_bankrupt`.

---

### Task 2: HTTP `POST companies/<slug>/bankrupt` и `successor_slug`

**Files:**
- Modify: `backend/apps/companies/models.py` (свойство `successor_slug` рядом с `parent_slug`)
- Modify: `backend/apps/companies/schemas.py` (`CompanyRead.successor_slug`, `BankruptRequest`, `BankruptResponse`)
- Modify: `backend/apps/companies/views.py` (`CompanyBankruptView` после `CompanyRestoreView`)
- Modify: `backend/apps/companies/urls.py`
- Test: `backend/apps/companies/tests/test_api_write.py`, `backend/apps/companies/tests/test_api_read.py` (и другие точные сравнения тела `CompanyRead` — `grep -rn '"archived_at"' backend/apps/companies/tests`)

**Interfaces:**
- Consumes: задача 1 — `lifecycle.bankrupt_company(slug, successor_slug, *, dry_run) -> BankruptcyResult`, `lifecycle.LifecycleError` с `status`/`code`/`detail`.
- Produces: `POST /api/companies/v1/companies/<slug>/bankrupt` тело `{"successor": str, "dry_run": bool = false}` → 200 `{"company": CompanyRead, "successor": CompanyRead, "members_total": int, "members_granted": int, "members_already": int, "archived": bool, "dry_run": bool}`; поле `successor_slug: str | null` в каждом `CompanyRead`.

- [ ] **Step 1: Падающие тесты** — в конец `backend/apps/companies/tests/test_api_write.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_bankrupt_is_a_platform_operation(client, two_companies):
    dead, heir = two_companies
    body = {"successor": heir}
    assert post_json(client, f"{BASE}/companies/{dead}/bankrupt", body,
                     **auth(staff_token())).status_code == 403

    res = post_json(client, f"{BASE}/companies/{dead}/bankrupt",
                    {"successor": heir, "dry_run": True}, **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["dry_run"] is True
    assert Company.objects.get(slug=dead).status == CompanyStatus.ACTIVE

    res = post_json(client, f"{BASE}/companies/{dead}/bankrupt", body,
                    **auth(superuser_token()))
    assert res.status_code == 200
    data = res.json()
    assert data["company"]["status"] == "archived"
    assert data["company"]["successor_slug"] == heir
    assert data["successor"]["slug"] == heir
    assert {"members_total", "members_granted", "members_already", "archived"} <= data.keys()
    assert data["archived"] is True


@pytest.mark.django_db
def test_bankrupt_errors_keep_the_envelope(client, pair):
    holding, htq = pair
    res = post_json(client, f"{BASE}/companies/{htq.slug}/bankrupt",
                    {"successor": htq.slug}, **auth(superuser_token()))
    assert res.status_code == 422
    assert res.json()["code"] == "successor_invalid"

    res = post_json(client, f"{BASE}/companies/no-such/bankrupt",
                    {"successor": htq.slug}, **auth(superuser_token()))
    assert res.status_code == 404
```

(`post_json` — добавить в импорт из `apps.companies.tests.api_helpers`, он там есть.) В `test_api_read.py::test_superuser_lists_all_by_default_and_filters_by_status` ожидаемый словарь `htq` дополнить `"successor_slug": None`; то же — в других точных сравнениях тела `CompanyRead` (найти `grep`).

- [ ] **Step 2: Прогнать — падают** (тестировщик, после коммита задачи 1).

- [ ] **Step 3: Модель** — `backend/apps/companies/models.py`, после свойства `parent_slug`:

```python
    @property
    def successor_slug(self) -> str | None:
        """Slug компании-преемника — для схем ответа (``from_attributes``)."""
        return self.successor.slug if self.successor_id else None
```

- [ ] **Step 4: Схемы** — `backend/apps/companies/schemas.py`: в `CompanyRead` после `parent_slug` — `successor_slug: str | None = None`. После `CompanyRead`:

```python
class BankruptRequest(BaseModel):
    successor: str
    dry_run: bool = False


class BankruptResponse(BaseModel):
    company: CompanyRead
    successor: CompanyRead
    members_total: int
    members_granted: int
    members_already: int
    archived: bool
    dry_run: bool
```

- [ ] **Step 5: Вьюха и маршрут** — `backend/apps/companies/views.py` после `CompanyRestoreView`:

```python
class CompanyBankruptView(CompaniesView):
    """Банкротство с преемником — платформенная операция (спека
    docs/plans/2026-09-26-company-bankruptcy-spec.md). Фабрика ``@platform``
    стоит в реестре самообслуживания одной записью ``scoped`` — поэтому первой
    строкой ``deny_unless_platform_admin``, как у архива и восстановления."""

    @platform("POST", body=schemas.BankruptRequest)
    def post(self, request, slug: str, data: schemas.BankruptRequest):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            result = lifecycle.bankrupt_company(slug, data.successor,
                                                dry_run=data.dry_run)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.BankruptResponse(
            company=schemas.CompanyRead.model_validate(result.company),
            successor=schemas.CompanyRead.model_validate(result.successor),
            members_total=result.members_total,
            members_granted=result.members_granted,
            members_already=result.members_already,
            archived=result.archived,
            dry_run=result.dry_run,
        )
```

`backend/apps/companies/urls.py` — после маршрутов `restore`:

```python
    path("companies/<slug:slug>/bankrupt", views.CompanyBankruptView.as_view()),
    path("companies/<slug:slug>/bankrupt/", views.CompanyBankruptView.as_view()),
```

(Проверь, как `@platform` передаёт `data` — у `api_view(body=…)` вьюха получает `data` именованным аргументом; сверь с существующими `@platform(…, body=…)` / `@write(…, body=…)` в файле.)

- [ ] **Step 6: Прогнать — проходят** (тестировщик): `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_write.py apps/companies/tests/test_api_read.py apps/access/tests/test_gate.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 7: Коммит** (контроллер): `feat(companies): ручка банкротства и преемник в ответе реестра`.

---

### Task 3: Фронт — панель банкротства в реестре

**Files:**
- Modify: `frontend/src/types/companies.ts` (`Company.successor_slug`, `BankruptResult`)
- Modify: `frontend/src/api/companies.ts` (`bankrupt`)
- Modify: `frontend/src/pages/companies/CompanyRegistry.tsx`
- Modify: `frontend/public/locales/ru/translation.json`, `frontend/public/locales/en/translation.json`
- Test: `frontend/src/pages/companies/CompanyRegistry.test.tsx`

**Interfaces:**
- Consumes: задача 2 — `POST companies/<slug>/bankrupt` `{successor, dry_run}` → `{company, successor, members_total, members_granted, members_already, archived, dry_run}`; `Company.successor_slug`.

- [ ] **Step 1: Падающие тесты** — в `CompanyRegistry.test.tsx`: в мок `companiesApi` добавить `bankrupt: (slug: string, body: unknown) => bankrupt(slug, body)` и `const bankrupt = vi.fn();`; в `beforeEach` — `bankrupt.mockReset()`. Новые тесты в `describe`:

```tsx
  it('банкротство: предпросмотр с dry_run, затем подтверждение', async () => {
    roles.mockReturnValue(['admin']);
    bankrupt.mockImplementation((_slug: string, body: { dry_run?: boolean }) => Promise.resolve({ data: {
      company: { ...LIST[1], status: body.dry_run ? 'active' : 'archived', successor_slug: body.dry_run ? null : 'hi-tech-group' },
      successor: LIST[0], members_total: 3, members_granted: 2, members_already: 1,
      archived: !body.dry_run, dry_run: !!body.dry_run,
    } }));
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    await userEvent.click(screen.getByRole('button', { name: /Банкротство/ }));
    await userEvent.selectOptions(screen.getByLabelText(/Преемник/), 'hi-tech-group');
    await userEvent.click(screen.getByRole('button', { name: /Проверить/ }));
    expect(bankrupt).toHaveBeenCalledWith('hi-tech-qazaqstan', { successor: 'hi-tech-group', dry_run: true });
    expect(await screen.findByText(/2 сотрудник/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Подтвердить банкротство/ }));
    expect(bankrupt).toHaveBeenLastCalledWith('hi-tech-qazaqstan', { successor: 'hi-tech-group', dry_run: false });
  });

  it('показывает преемника у закрытой компании', async () => {
    roles.mockReturnValue(['admin']);
    list.mockResolvedValue({ data: [LIST[0], { ...LIST[1], status: 'archived', successor_slug: 'hi-tech-group' }] });
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    expect(screen.getByText(/Преемник/)).toBeInTheDocument();
  });
```

(Если в дереве архивная компания не рисуется и найти её по тексту из дерева нельзя — ищи в блоке «В архиве» реестра: он рисует архивные из `list`. Сверь существующие фикстуры `LIST`/`TREE` и подстрой второй тест под них, не меняя смысла: карточка компании с `successor_slug` показывает строку «Преемник: …».)

- [ ] **Step 2: Прогнать — падают**: `npx vitest run src/pages/companies/CompanyRegistry.test.tsx`.

- [ ] **Step 3: Типы и API** — `types/companies.ts`: в `Company` после `parent_slug` — `successor_slug?: string | null;`; новый тип:

```ts
export interface BankruptResult {
  company: Company;
  successor: Company;
  members_total: number;
  members_granted: number;
  members_already: number;
  archived: boolean;
  dry_run: boolean;
}
```

`api/companies.ts` рядом с `archive`/`restore`:

```ts
  bankrupt: (slug: string, body: { successor: string; dry_run: boolean }) =>
    api.post<BankruptResult>(path(`companies/${slug}/bankrupt`), body),
```

- [ ] **Step 4: Реестр** — `CompanyRegistry.tsx`:
- состояние: `confirm` расширить до `'archive' | 'restore' | 'bankrupt' | null`; `const [successor, setSuccessor] = useState('');`, `const [preview, setPreview] = useState<BankruptResult | null>(null);` — сбрасывать оба при смене выбранной компании и при отмене;
- мутации:

```tsx
  const previewMut = useMutation({
    mutationFn: (slug: string) => companiesApi.bankrupt(slug, { successor, dry_run: true }),
    onSuccess: (res) => setPreview(res.data),
    onError: (e) => reportApiError(e, t('companies.bankruptcy.previewFailed', 'Не удалось проверить')),
  });
  const bankruptMut = useMutation({
    mutationFn: (slug: string) => companiesApi.bankrupt(slug, { successor, dry_run: false }),
    onSuccess: () => { toast.success(t('companies.bankruptcy.done', 'Компания закрыта, дела переданы преемнику')); invalidate(); },
    onError: (e) => reportApiError(e, t('companies.bankruptcy.failed', 'Не удалось провести банкротство')),
    onSettled: () => { setConfirm(null); setPreview(null); setSuccessor(''); },
  });
```

- в блоке кнопок `canWrite` для `company.status === 'active'` — рядом с «В архив» кнопка:

```tsx
                      <Button variant="outline" size="sm" onClick={() => setConfirm('bankrupt')}>
                        <Handshake className="mr-1 h-4 w-4" />{t('companies.bankruptcy.button', 'Банкротство…')}
                      </Button>
```

(иконка `Handshake` из `lucide-react`; если её нет в установленной версии — `ArrowRightLeft`);
- в `dl` карточки после строки «Вышестоящая»:

```tsx
                  {company.successor_slug && (<>
                    <dt className="text-muted-foreground">{t('companies.bankruptcy.successor', 'Преемник')}</dt>
                    <dd>{bySlug.get(company.successor_slug)?.name ?? company.successor_slug}</dd>
                  </>)}
```

- панель при `confirm === 'bankrupt'` (в том же месте, где `alertdialog` архива; тот блок оставить для `archive`/`restore`):

```tsx
                {confirm === 'bankrupt' && (
                  <div role="alertdialog" className="space-y-2 rounded-lg border border-amber-300/70 bg-amber-50/70 p-3 text-sm dark:border-amber-800/70 dark:bg-amber-950/30">
                    <label className="flex items-center gap-2">
                      <span>{t('companies.bankruptcy.successor', 'Преемник')}</span>
                      <select className="rounded-md border px-2 py-1"
                        value={successor} onChange={(e) => { setSuccessor(e.target.value); setPreview(null); }}>
                        <option value="">—</option>
                        {(listQuery.data ?? []).filter((c) => c.status === 'active' && c.slug !== company.slug)
                          .map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
                      </select>
                    </label>
                    {preview && (
                      <p>{t('companies.bankruptcy.preview',
                        '{{count}} сотрудник(ов) получат доступ к «{{name}}» (уже там: {{already}}); компания уйдёт в архив (только чтение). Карточки сотрудников, техника и договоры не переносятся.',
                        { count: preview.members_granted, name: preview.successor.name, already: preview.members_already })}</p>
                    )}
                    <div className="flex gap-2">
                      {!preview ? (
                        <Button size="sm" disabled={!successor || previewMut.isPending} onClick={() => previewMut.mutate(company.slug)}>
                          {t('companies.bankruptcy.check', 'Проверить')}
                        </Button>
                      ) : (
                        <Button size="sm" variant="destructive" disabled={bankruptMut.isPending} onClick={() => bankruptMut.mutate(company.slug)}>
                          {t('companies.bankruptcy.confirm', 'Подтвердить банкротство')}
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => { setConfirm(null); setPreview(null); setSuccessor(''); }}>
                        {t('common.cancel', 'Отмена')}
                      </Button>
                    </div>
                  </div>
                )}
```

Существующий блок `{confirm && (…)}` для архива ограничить `(confirm === 'archive' || confirm === 'restore') && (…)`, а его кнопку подтверждения оставить как есть.

- [ ] **Step 5: Переводы** — в обе локали, раздел `companies`, точечно после `"archiveMode": {…},` (файлы не переформатировать):

ru:
```json
    "bankruptcy": {
      "button": "Банкротство…",
      "successor": "Преемник",
      "check": "Проверить",
      "confirm": "Подтвердить банкротство",
      "preview": "{{count}} сотрудник(ов) получат доступ к «{{name}}» (уже там: {{already}}); компания уйдёт в архив (только чтение). Карточки сотрудников, техника и договоры не переносятся.",
      "done": "Компания закрыта, дела переданы преемнику",
      "failed": "Не удалось провести банкротство",
      "previewFailed": "Не удалось проверить"
    },
```

en:
```json
    "bankruptcy": {
      "button": "Bankruptcy…",
      "successor": "Successor",
      "check": "Check",
      "confirm": "Confirm bankruptcy",
      "preview": "{{count}} employee(s) will get access to “{{name}}” (already there: {{already}}); the company will be archived (read only). Employee cards, equipment and contracts are not transferred.",
      "done": "Company closed, affairs handed to the successor",
      "failed": "Bankruptcy failed",
      "previewFailed": "Check failed"
    },
```

- [ ] **Step 6: Прогнать — проходят**: `npx vitest run src/pages/companies`, весь `npx vitest run` (≤ 8), `npx tsc --noEmit -p tsconfig.app.json` (≤ 148), `npm run lint` (≤ 376).

- [ ] **Step 7: Коммит** (контроллер): `feat(frontend): банкротство с преемником в реестре компаний`.

---

### Task 4: Документы

**Files:**
- Modify: `docs/multi-company-tenancy-design.md`, `CLAUDE.md`, `API.md`, `docs/plans/2026-09-14-group-structure-roadmap.md`, `docs/deploy/subdomains-runbook.md`, `STRUCTURE.md` (если там перечислены команды `companies`)

- [ ] **Step 1: Дизайн** — шапка «Состояние»: подпроект 4 — «создание, архив «только чтение», восстановление и банкротство с преемником есть ([спека](plans/2026-09-26-company-bankruptcy-spec.md)); переносится только членство — техника, договоры и карточки `hr` остаются в архиве (решение заказчика 26.09)». §4 строка 4 — «✅ выполнен» с той же оговоркой. §5 `successor` — «заполняется `lifecycle.bankrupt_company` (команда `company_bankrupt`, ручка `POST companies/<slug>/bankrupt`); восстановление снимает».
- [ ] **Step 2: `CLAUDE.md`** — в абзаце со списком команд `companies` (после `company_archive`/`company_restore`) добавить: «`company_bankrupt --company X --successor Y [--dry-run]` (банкротство с преемником: участники с действующей учёткой получают членство в Y, X — в архив «только чтение», `X.successor = Y`; техника, договоры и карточки `hr` не переносятся; то же — кнопкой «Банкротство…» в реестре, только суперпользователь)».
- [ ] **Step 3: `API.md`** — в разделе `companies` строка `POST companies/<slug>/bankrupt` (тело, ответ, коды 403/404/409/422, только суперпользователь) и `successor_slug` в описании `CompanyRead`.
- [ ] **Step 4: Roadmap** — §4 строка «Реестр компаний…»: «банкротство с преемником — **закрыто** ([спека](2026-09-26-company-bankruptcy-spec.md), [план](2026-09-26-company-bankruptcy.md))»; §10 абзац «Сознательно оставлено» — убрать «банкротство с переносом активов», дописать строку о закрытии.
- [ ] **Step 5: Runbook** — в конец раздел «Банкротство компании»: `manage.py company_bankrupt --company X --successor Y --dry-run` → прочитать сводку (сколько людей получат доступ) → без `--dry-run` → `manage.py tenancy_status`; кадровику преемника — завести карточки перенесённым людям.
- [ ] **Step 6: Коммит** (контроллер): `docs: банкротство с преемником — дизайн, CLAUDE.md, API.md, roadmap, чеклист`.

---

## Итоговая проверка (тестировщик)

Весь бэкенд частями ≤ 10 минут (как в плане архива), падают только 6 из `backend/ci-known-failures.txt`; `makemigrations --check --dry-run` — «No changes detected»; фронт — tsc ≤ 148, vitest ≤ 8 известных, lint ≤ 376.
