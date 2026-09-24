# Блок L — гейт модуля на шесть оставшихся аппок — план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ручки `media_files`, `conference`, `messenger`, `mail`, `cms`, `approvals` встают под `api_view(module=…, level=…)` или в реестр самообслуживания; `admin=True` в них снят; ни один сотрудник не теряет сегодняшнего доступа.

**Architecture:** `employee-basic` расширяется узлами под сегодняшний открытый доступ (миграция `access/0011`), новая системная роль `services-admin` (`access/0012`) заменяет `is_staff` на экранах шести аппок и выдаётся текущим администраторам командой `access_backfill_services_admin`. Гейт навешивается по аппке за задачу; сторож `test_gate.py` включает аппку в `TRANSLATED_APPS` в том же коммите. Инвариант L1 (базовая роль ниже любой бывшей админской ручки) закрепляется ast-сторожем по всем ручкам.

**Tech Stack:** Django 5.2.7, hand-rolled `htqweb.http.api_view`, `apps.access` (роли × узлы реестра), pytest-django на Postgres `:55432`, React + vitest.

**Spec:** [2026-09-24-block-l-gate-remaining-apps-spec.md](2026-09-24-block-l-gate-remaining-apps-spec.md). Решения §12 — рекомендованные: удаление контента `cms` под `write`; создание приглашения — как сегодня (любой сотрудник); `media.list_files` на признаке `delete` узла `media.files`.

**Поправка к спеке §9.1** (найдено при планировании): экраны заявок на фронте уже переведены на уровень модуля — `RequestsLayout.tsx:39`, `NewRequestPage.tsx:51`, `RequestDetailPage.tsx:67` зовут `permissions.atLeast('approvals', 'admin')`. Фронтовая часть блока — только пункты меню (задача 10).

## Global Constraints

- Зона второго разработчика не правится: `backend/apps/contracts/**`, `backend/apps/signoff/**`, `frontend/src/pages/{contracts,signoff}/**`.
- Ветки/worktree не создавать; работать в `sanzhar`; `git add` поимённо, никогда `-A`/`.`; `git stash` не использовать; не стейджить `.codebase-memory/`, `.cursor/`, `.zed/`, `.github/copilot-instructions.md`, `.github/instructions/`.
- pytest — форграунд, Bash `timeout: 600000`, одна сессия за раз, команды дольше 10 минут дробить; из `backend/`: `../.venv/Scripts/python.exe -m pytest … -q -p no:cacheprovider`; Postgres: `docker compose -f docker-compose.test-local.yml up -d db` из корня.
- Межаппное — только через `apps.<x>.interface` (сторож `apps/core/tests/test_app_isolation.py`; каталоги `tests` из-под правила выведены).
- Имя модуля у `media_files` — **`media`**: `module="media_files"` молча даёт `none` всем.
- `core` не трогать: не модуль прав, его `admin=True` остаются.
- `auth=None`-ручки не трогать и в реестр не вносить.
- Итоговые уровни `employee-basic`: `media` — `write`, `conference` — `read`, `messenger` — `write`, `mail` — `read`, `cms` — `read`, `approvals` — `write`; `employee-basic` не несёт `delete` ни в одном из шести модулей.
- Код роли администратора — `services-admin`, название «Администратор сервисов».
- Уровень в `api_view` всегда явный литерал рядом с `module=` (`read|write|admin`).
- Коммиты на русском, последняя строка `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; не пушить.
- Фронт: `npx tsc --noEmit -p tsconfig.json` — 0 ошибок (база 24.09), `npx vitest run` — не больше 8 известных падений, `npm run lint` — не больше 376 проблем.

## Review Focus

- **Сотрудник с одной `employee-basic` не теряет ни одной сегодняшней ручки** — ожидание: каждая гейтированная ручка шести аппок, не бывшая `admin=True`, требует уровень не выше уровня `employee-basic` в своём модуле. Тест — задача 3, `test_employee_basic_passes_every_non_admin_handle` (ast по всем ручкам, не выборка).
- **Бывшая админская ручка открылась рядовому** (агрегат базовой роли дотянулся) — ожидание: каждая бывшая `admin=True` требует уровень строго выше базового. Тест — задача 3, `test_no_former_admin_handle_is_open_to_employee_basic`.
- **transaction=True-тест стёр строки базовой роли из `0011`** — ожидание: после такого теста `employee-basic` снова несёт узлы `0004` И `0011`. Тест — задача 1, `test_reseed_restores_block_l_nodes`.
- **Приглашение, когда модуль `tasks` выключен у компании** — `get_conference_event_for_room` поднимает `ServiceDisabled`; ожидание: проверка организатора не падает 500, работают «автор ссылки» и `cms:admin`. Тест — задача 8, `test_invite_check_survives_disabled_tasks`.
- **`is_staff` без роли на бывшей админской ручке** — ожидание 403 (решение заказчика 2), держатель `services-admin` — 200. Тесты — задачи 4–9, в файле `test_gate_roles.py` каждой аппки.

---

### Task 1: Роли — расширение `employee-basic` и `services-admin`

**Files:**
- Create: `backend/apps/access/migrations/0011_employee_basic_block_l.py`
- Create: `backend/apps/access/migrations/0012_seed_services_admin_role.py`
- Modify: `backend/conftest.py` (фикстура `reseed_basic_role_for_transactional_tests`, строки ~76–107)
- Test: `backend/apps/access/tests/test_block_l_roles.py`

**Interfaces:**
- Produces: роль `services-admin` (`Role.code`), константы `apps/access/migrations/0012_seed_services_admin_role.py::ROLE_CODE = "services-admin"`; функции `seed(apps, schema_editor)` в обеих миграциях (их зовёт фикстура `conftest.py`).

- [ ] **Step 1: Падающий тест** — `backend/apps/access/tests/test_block_l_roles.py`:

```python
"""Роли блока L: уровни employee-basic и services-admin по шести модулям.

Числа выписаны руками из спеки (§4), а не вычислены тем же кодом: тест
обязан поймать узел, который дотянул базовую роль до чужого уровня.
"""
from types import SimpleNamespace

import pytest

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.services import resolve

MODULES = ("media", "conference", "messenger", "mail", "cms", "approvals")

EMPLOYEE_BASIC = {
    "media": "write", "conference": "read", "messenger": "write",
    "mail": "read", "cms": "read", "approvals": "write",
}


def _levels(role_code: str, company: str) -> dict:
    user = SimpleNamespace(user_id=4242, is_superuser=False, email=None)
    RoleAssignment.objects.create(
        company_slug=company, user_id=user.user_id,
        role=Role.objects.get(code=role_code),
        scope_kind=ScopeKind.COMPANY, scope_id=None)
    perms = resolve.permissions_for(user, company)
    return {m: (perms.get(m) or {}).get("level", "none") for m in MODULES}


def test_employee_basic_levels_match_the_spec(company_row):
    assert _levels("employee-basic", company_row) == EMPLOYEE_BASIC


def test_services_admin_is_admin_everywhere(company_row):
    assert _levels("services-admin", company_row) == {m: "admin" for m in MODULES}


@pytest.mark.django_db
def test_employee_basic_never_deletes_in_block_l_modules():
    role = Role.objects.get(code="employee-basic")
    deleting = [p.node for p in role.permissions.all()
                if p.can_delete and p.node.split(".")[0] in MODULES]
    assert deleting == []


@pytest.mark.django_db
def test_services_admin_is_a_shared_system_role():
    role = Role.objects.get(code="services-admin")
    assert role.is_system is True
    assert (role.company_slug or "") == ""
    assert role.title == "Администратор сервисов"


@pytest.mark.django_db(transaction=True)
def test_reseed_restores_block_l_nodes():
    role = Role.objects.get(code="employee-basic")
    nodes = set(role.permissions.values_list("node", flat=True))
    assert {"media.files", "messenger.rooms", "conference.history",
            "approvals.templates"} <= nodes
    assert Role.objects.filter(code="services-admin").exists()
```

(Сверить имя обратной связи `RolePermission` → `Role`: `role.permissions` — если в модели другое `related_name`, взять его из `apps/access/models.py`; если у `Role` нет `title`-поля с таким именем — взять фактическое.)

- [ ] **Step 2: Прогнать — падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_block_l_roles.py -q -p no:cacheprovider`
Expected: FAIL — `Role.DoesNotExist: services-admin`, уровни `media`/`messenger`… не совпадают.

- [ ] **Step 3: Миграция `0011_employee_basic_block_l.py`**

```python
"""Блок L: добавить employee-basic узлы под сегодняшний открытый доступ.

До гейта модуля ручки media/conference/messenger/approvals пускали любого
вошедшего; «перенести как есть» (решение заказчика 24.09.2026) значит выдать
это базовой роли, а не отнять. Только ДОБАВЛЕНИЕ строк: существующие
(access/0004) не трогаются. Ни одного can_delete — иначе агрегат модуля
станет admin и откроет всем бывшие admin=True ручки (инвариант L1 спеки).

Пути и признаки заморожены литералами, как в 0004.
"""

from django.db import migrations

ROLE_CODE = "employee-basic"

VIEW = ("can_view",)
CREATE = ("can_view", "can_create")
EDIT = ("can_view", "can_create", "can_edit")

NODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("media.files", CREATE),
    ("messenger.rooms", EDIT),
    ("conference.history", VIEW),
    ("conference.transcripts", VIEW),
    ("approvals.projects", VIEW),
    ("approvals.templates", VIEW),
    ("approvals.reference", VIEW),
)

_ALL = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role = Role.objects.filter(code=ROLE_CODE).first()
    if role is None:
        return
    for node, flags in NODES:
        RolePermission.objects.get_or_create(
            role=role, node=node,
            defaults={flag: flag in flags for flag in _ALL},
        )


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")
    RolePermission.objects.filter(
        role__code=ROLE_CODE, node__in=[node for node, _ in NODES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0010_backfill_role_company_slug"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
```

- [ ] **Step 4: Миграция `0012_seed_services_admin_role.py`**

```python
"""Блок L: системная роль «Администратор сервисов».

Заменяет is_staff на экранах шести аппок (admin=True снимается, решение
заказчика 24.09.2026): admin по media, conference, messenger, mail, cms,
approvals. Текущим is_staff её выдаёт manage.py access_backfill_services_admin,
новым — редактор ролей. Общая для группы (company_slug пуст), системная.

Узлы и признаки — литералами по access_functions.py шести аппок на 24.09.2026.
"""

from django.db import migrations

ROLE_CODE = "services-admin"
TITLE = "Администратор сервисов"

V = ("can_view",)
VD = ("can_view", "can_delete")
VCD = ("can_view", "can_create", "can_delete")
VE = ("can_view", "can_edit")
FULL = ("can_view", "can_create", "can_edit", "can_delete")

NODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("media.files", VCD),
    ("media.avatars", VCD),
    ("conference.join", V),
    ("conference.history", VD),
    ("conference.recordings", VD),
    ("conference.transcripts", VD),
    ("conference.invites", VCD),
    ("messenger.chats", V),
    ("messenger.rooms", FULL),
    ("messenger.moderation", VD),
    ("mail.messages", V),
    ("mail.mailboxes", FULL),
    ("mail.server", VE),
    ("cms.news", FULL),
    ("cms.home_sections", FULL),
    ("cms.contact_requests", FULL),
    ("cms.conference", FULL),
    ("approvals.requests", FULL),
    ("approvals.templates", FULL),
    ("approvals.projects", FULL),
    ("approvals.reference", FULL),
    ("approvals.stats", FULL),
    ("approvals.decisions", V),
)

_ALL = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role, _ = Role.objects.get_or_create(
        code=ROLE_CODE, defaults={"title": TITLE, "is_system": True})
    for node, flags in NODES:
        RolePermission.objects.update_or_create(
            role=role, node=node,
            defaults={flag: flag in flags for flag in _ALL},
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Role.objects.filter(code=ROLE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0011_employee_basic_block_l"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
```

Перед записью сверить наборы признаков с `apps/<app>/access_functions.py` каждого модуля (третий элемент кортежа ограничивает применимые признаки): строка роли с неприменимым признаком — ошибка. Если у узла нет ограничения — `FULL`.

- [ ] **Step 5: Пересев в `conftest.py`** — в `reseed_basic_role_for_transactional_tests` после вызова `…0004_seed_employee_role").seed(django_apps, None)` добавить:

```python
        importlib.import_module(
            "apps.access.migrations.0011_employee_basic_block_l").seed(django_apps, None)
        importlib.import_module(
            "apps.access.migrations.0012_seed_services_admin_role").seed(django_apps, None)
```

и в докстринг фикстуры одну фразу: «С блока L пересеваются и `0011` (узлы базовой роли под гейт шести аппок), и `0012` (`services-admin`).»

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/access -q -p no:cacheprovider`
Expected: PASS. Затем `DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` — «No changes detected».

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/access/migrations/0011_employee_basic_block_l.py backend/apps/access/migrations/0012_seed_services_admin_role.py backend/conftest.py backend/apps/access/tests/test_block_l_roles.py
git commit -m "feat(access): блок L — узлы employee-basic под гейт шести аппок и роль services-admin"
```

---

### Task 2: Перенос администраторов — `access_backfill_services_admin`

**Files:**
- Create: `backend/apps/access/management/commands/access_backfill_services_admin.py`
- Test: `backend/apps/access/tests/test_backfill_services_admin.py`

**Interfaces:**
- Consumes: роль `services-admin` (задача 1); `apps.companies.interface.user_company_slugs(user_id) -> list[str]`, `apps.companies.interface.get_company(slug)`; `apps.users` — активные пользователи с `is_staff=True, is_superuser=False` читать через `apps.users.interface` (сверить имя функции; если подходящей нет — добавить в `apps/users/interface.py` `staff_user_ids() -> list[int]`: `User.objects.filter(is_staff=True, is_superuser=False, status=UserStatus.ACTIVE).values_list("id", flat=True)`, первой строкой `require_service("users")`).
- Produces: `manage.py access_backfill_services_admin [--dry-run] [--company SLUG]`.

- [ ] **Step 1: Падающие тесты** — `backend/apps/access/tests/test_backfill_services_admin.py`:

```python
"""access_backfill_services_admin — роль services-admin текущим is_staff."""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.access.models import Role, RoleAssignment
from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus


def _user(name, *, staff=False, superuser=False, status=UserStatus.ACTIVE):
    return User.objects.create(username=name, email=f"{name}@htq.test", password="x",
                               status=status, is_staff=staff, is_superuser=superuser)


@pytest.fixture
def company(db):
    return Company.objects.create(slug="t-sa", name="SA", kind=CompanyKind.SERVICE)


def _run(*args):
    out = StringIO()
    call_command("access_backfill_services_admin", *args, stdout=out)
    return out.getvalue()


def _holders(company_slug):
    role = Role.objects.get(code="services-admin")
    return set(RoleAssignment.objects.filter(company_slug=company_slug, role=role)
               .values_list("user_id", flat=True))


def test_staff_member_gets_the_role_in_his_company(company):
    staff = _user("staff", staff=True)
    CompanyMembership.objects.create(company=company, user_id=staff.id)
    _run()
    assert _holders(company.slug) == {staff.id}


def test_superuser_plain_inactive_and_nonmember_are_skipped(company):
    su = _user("su", staff=True, superuser=True)
    plain = _user("plain")
    gone = _user("gone", staff=True, status=UserStatus.SUSPENDED)
    lonely = _user("lonely", staff=True)
    for u in (su, plain, gone):
        CompanyMembership.objects.create(company=company, user_id=u.id)
    out = _run()
    assert _holders(company.slug) == set()
    assert "lonely" in out or str(lonely.id) in out   # без членства — в сводке


def test_dry_run_writes_nothing_and_rerun_is_idempotent(company):
    staff = _user("staff", staff=True)
    CompanyMembership.objects.create(company=company, user_id=staff.id)
    _run("--dry-run")
    assert _holders(company.slug) == set()
    _run()
    _run()
    assert RoleAssignment.objects.filter(
        company_slug=company.slug, user_id=staff.id,
        role__code="services-admin").count() == 1
```

(`CompanyMembership.objects.create` напрямую — чтобы не зависеть от выдачи базовой роли; если модель требует другие поля — взять из `apps/companies/models.py`.)

- [ ] **Step 2: Прогнать — падает** (`Unknown command: 'access_backfill_services_admin'`).

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_backfill_services_admin.py -q -p no:cacheprovider`

- [ ] **Step 3: Реализация** — `backend/apps/access/management/commands/access_backfill_services_admin.py`:

```python
"""Перенос администраторов сервисов: роль services-admin текущим is_staff.

Блок L. До него экраны media/conference/messenger/mail/cms/approvals пускали
по admin=True, то есть по is_staff. Гейт модуля флаги токена не читает
(как в блоке I для кадров), поэтому «перенести как есть» — выдать каждому
действующему is_staff (не суперпользователю: тот проходит гейт сам) роль
services-admin в каждой компании, где у него есть членство.

Без членства выдавать некуда — такой пользователь печатается в сводке:
токена на поддомен у него всё равно нет. Идемпотентна (get_or_create),
--dry-run ничего не пишет. RoleAssignment и CompanyMembership лежат в
public — use_company не нужен.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.access.models import Role, RoleAssignment, ScopeKind

ROLE_CODE = "services-admin"


class Command(BaseCommand):
    help = ("Выдать роль services-admin действующим is_staff (кроме "
            "суперпользователей) во всех их компаниях. Идемпотентно.")

    def add_arguments(self, parser):
        parser.add_argument("--company", dest="company", default=None,
                            help="slug одной компании.")
        parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                            help="Ничего не писать — только сводка.")

    def handle(self, *args, **options):
        from apps.companies import interface as companies
        from apps.users import interface as users

        dry_run: bool = options["dry_run"]
        only: str | None = options["company"]

        role = Role.objects.filter(code=ROLE_CODE).first()
        if role is None:
            raise CommandError(
                f"Роль {ROLE_CODE} не найдена (миграция access.0012 не применена?).")
        if only and companies.get_company(only) is None:
            raise CommandError(f"Компания {only!r} не найдена в реестре.")

        prefix = "[dry-run] " if dry_run else ""
        created = already = 0
        for user_id in users.staff_user_ids():
            slugs = companies.user_company_slugs(user_id)
            if only:
                slugs = [s for s in slugs if s == only]
            if not slugs:
                self.stdout.write(self.style.WARNING(
                    f"{prefix}пользователь {user_id}: нет членства — роль выдавать некуда"))
                continue
            for slug in slugs:
                exists = RoleAssignment.objects.filter(
                    company_slug=slug, user_id=user_id, role=role,
                    scope_kind=ScopeKind.COMPANY, scope_id=None).exists()
                if exists:
                    already += 1
                    continue
                created += 1
                if not dry_run:
                    RoleAssignment.objects.get_or_create(
                        company_slug=slug, user_id=user_id, role=role,
                        scope_kind=ScopeKind.COMPANY, scope_id=None)
                self.stdout.write(f"{prefix}пользователь {user_id} → {slug}")
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Роль {ROLE_CODE}: выдано сейчас {created}, уже было {already}."))
```

Если `apps.users.interface.staff_user_ids` не существует — добавить её (см. Interfaces) с тестом в `backend/apps/users/tests/` на три случая (staff — да; superuser — нет; неактивный — нет). Если сообщение про «нет членства» печатает id, а тест ищет имя — тест принимает любое из двух (как написано выше).

- [ ] **Step 4: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_backfill_services_admin.py apps/core/tests/test_app_isolation.py apps/users -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/access/management/commands/access_backfill_services_admin.py backend/apps/access/tests/test_backfill_services_admin.py <apps/users/interface.py и его тест, если правились>
git commit -m "feat(access): перенос администраторов сервисов — access_backfill_services_admin"
```

---

### Task 3: Сторожа блока L — имя модуля и инвариант L1

**Files:**
- Modify: `backend/apps/access/tests/test_gate.py` (новые тесты в конец файла)

**Interfaces:**
- Consumes: `_iter_api_view_calls`, `_qualified_name`, `_gate_of`, `_Ref`, `_app_modules` (уже в `test_gate.py`), `htqweb.middleware.service_gate.APP_LABEL_TO_SERVICE`, `apps.access.self_service.TRANSLATED_APPS`.
- Produces: `BLOCK_L_APPS`, `EMPLOYEE_BASIC_LEVEL`, `FORMER_ADMIN_HANDLES` — константы в `test_gate.py`; задачи 4–9 не правят их, а включают аппку в `TRANSLATED_APPS`, после чего сторожа начинают её проверять.

- [ ] **Step 1: Тесты** — в конец `backend/apps/access/tests/test_gate.py`:

```python
# ── Блок L: имя модуля и инвариант L1 ──────────────────────────────────────

from htqweb.middleware.service_gate import APP_LABEL_TO_SERVICE

#: Аппки блока L (каталог аппки → модуль прав). Проверяются, как только
#: аппка попала в TRANSLATED_APPS (задачи 4–9 плана блока L).
BLOCK_L_APPS = ("media_files", "conference", "messenger", "mail", "cms", "approvals")

#: Уровень employee-basic в модуле (спека блока L §4) — выписан руками.
EMPLOYEE_BASIC_LEVEL = {
    "media": "write", "conference": "read", "messenger": "write",
    "mail": "read", "cms": "read", "approvals": "write",
}

#: Ручки, бывшие admin=True до блока L (спека §6). Их уровень обязан быть
#: строго выше уровня employee-basic в модуле — иначе агрегат базовой роли
#: открыл бы их всем.
FORMER_ADMIN_HANDLES = {
    "media_files": {"list_files"},
    "messenger": {"admin_list_rooms", "admin_list_room_messages",
                  "admin_trigger_history_archive"},
    "mail": {"_list_mailboxes", "_create_mailbox", "_get_mailbox", "_update_mailbox",
             "_delete_mailbox", "reset_mailbox_password", "archive_mailbox",
             "restore_mailbox", "mailbox_status", "mailbox_lookup",
             "_get_mail_settings", "_put_mail_settings", "test_mail_connection",
             "mailbox_coverage", "_reconcile_report", "_reconcile_apply",
             "_list_aliases", "_create_alias", "delete_alias", "set_forwarding"},
    "cms": {"_list_contact_requests", "contact_request_stats", "_get_contact_request",
            "_update_contact_request", "_delete_contact_request", "reply_contact_request",
            "_create_news", "_update_news", "_delete_news", "translate_news",
            "_create_category", "_update_category", "_delete_category",
            "_create_tag", "_update_tag", "_delete_tag",
            "_list_home_sections_admin", "_create_home_section", "_delete_home_section",
            "_update_home_section", "home_sections_reorder", "home_items_collection",
            "home_items_reorder", "_update_home_item", "_delete_home_item"},
    "approvals": {"_create_project", "_delete_project", "create_source",
                  "update_source", "delete_source", "add_row", "delete_row"},
}

_LEVEL_RANK = {"none": 0, "read": 1, "write": 2, "admin": 3}


def _module_of(app: str) -> str:
    return APP_LABEL_TO_SERVICE.get(app, app)


def _string_constants(text: str) -> dict[str, str]:
    tree = ast.parse(text)
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets if isinstance(target, ast.Name)
    }


def _gates(text: str):
    """(lineno, имя ручки, module, level) для каждого api_view с module=.

    module/level — литералы; имя-ссылка разрешается через строковые
    константы модуля, иначе остаётся ``None`` (сторож уровня выше это уже
    ловит)."""
    lines = text.splitlines()
    constants = _string_constants(text)
    for start, end, block in _iter_api_view_calls(text):
        gate = _gate_of(block)
        if "module" not in gate:
            continue
        module, level = gate["module"], gate.get("level")
        if isinstance(module, _Ref):
            module = constants.get(module)
        if isinstance(level, _Ref):
            level = constants.get(level)
        yield start, _qualified_name(lines, start, end) or "?", module, level


def _translated_block_l_apps():
    return [app for app in BLOCK_L_APPS if app in self_service.TRANSLATED_APPS]


def test_module_name_matches_the_app():
    """module= в аппке равен имени её модуля прав: у media_files это media,
    и module="media_files" молча дал бы уровень none всем."""
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        expected = _module_of(app)
        for path in _app_modules(app):
            for lineno, name, module, _level in _gates(path.read_text(encoding="utf-8")):
                if module is not None and module != expected:
                    offenders.append(f"{path.name}:{lineno} {name}: module={module!r}, "
                                     f"ожидался {expected!r}")
    assert offenders == [], offenders


def test_employee_basic_passes_every_non_admin_handle():
    """Перенести как есть: ручка, не бывшая admin=True, пускает держателя
    одной employee-basic."""
    offenders = []
    for app in _translated_block_l_apps():
        basic = _LEVEL_RANK[EMPLOYEE_BASIC_LEVEL[_module_of(app)]]
        for path in _app_modules(app):
            for lineno, name, _module, level in _gates(path.read_text(encoding="utf-8")):
                if name in FORMER_ADMIN_HANDLES.get(app, set()) or level is None:
                    continue
                if _LEVEL_RANK[level] > basic:
                    offenders.append(f"{app}:{path.name}:{lineno} {name}: level={level}")
    assert offenders == [], offenders


def test_no_former_admin_handle_is_open_to_employee_basic():
    """Инвариант L1: бывшая admin=True требует уровень выше базовой роли."""
    offenders = []
    for app in _translated_block_l_apps():
        basic = _LEVEL_RANK[EMPLOYEE_BASIC_LEVEL[_module_of(app)]]
        seen = set()
        for path in _app_modules(app):
            for lineno, name, _module, level in _gates(path.read_text(encoding="utf-8")):
                if name not in FORMER_ADMIN_HANDLES.get(app, set()):
                    continue
                seen.add(name)
                if level is None or _LEVEL_RANK[level] <= basic:
                    offenders.append(f"{app}:{lineno} {name}: level={level}")
        missing = FORMER_ADMIN_HANDLES.get(app, set()) - seen
        offenders += [f"{app}: {name} — бывшая admin=True без гейта" for name in sorted(missing)]
    assert offenders == [], offenders


_WRONG_MODULE_SAMPLE = '''
@api_view(methods=("GET",), module="media_files", level="read")
def some_handle(request):
    return {}
'''


def test_guard_reads_the_module_of_a_gate():
    assert [(name, module) for _l, name, module, _lv in _gates(_WRONG_MODULE_SAMPLE)] \
        == [("some_handle", "media_files")]
```

- [ ] **Step 2: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q -p no:cacheprovider`
Expected: PASS (блок-L-аппок в `TRANSLATED_APPS` ещё нет — два последних сторожа ничего не проверяют; `test_module_name_matches_the_app` проходит на пяти переведённых). Если `test_module_name_matches_the_app` краснеет на существующей аппке (`hr`, `access`, …) — это находка: имя модуля не совпало; разобрать, не ослаблять тест.

- [ ] **Step 3: Коммит**

```bash
git add backend/apps/access/tests/test_gate.py
git commit -m "test(access): сторожа блока L — имя модуля и базовая роль ниже бывших админских ручек"
```

---

### Шаблон для задач 4–9 (читать вместе с задачей)

Каждая аппка переводится одним коммитом; повторяющиеся шаги расписаны в каждой задаче полностью, здесь — общие правила.

**Правка декоратора.** Ручка сотрудника: добавить `module=` и `level=` к существующему вызову, ничего больше не менять:

```python
# было
@api_view(methods=("GET",))
def _list_rooms(request):
# стало
@api_view(methods=("GET",), module="messenger", level="read")
def _list_rooms(request):
```

Бывшая админская: `admin=True` заменить на `module=…, level=…`:

```python
# было
@api_view(methods=("GET",), admin=True)
def admin_list_rooms(request):
# стало
@api_view(methods=("GET",), module="messenger", level="admin")
def admin_list_rooms(request):
```

`auth=None` — не трогать. Собственные проверки в теле и сервисах — не трогать.

**Тестовые помощники.** Ручки под гейтом требуют заголовок `X-HTQ-Company`, claim `company` в токене, совпадающий с ним, действующую строку `Company` и роль. В `backend/apps/access/tests/helpers.py` (задача 4 добавляет, остальные используют) — функция:

```python
def gate_company(slug: str, grants: dict[int, dict[str, str]]) -> str:
    """Компания и роли для тестов ручек под гейтом модуля.

    ``grants``: user_id -> {модуль: уровень|пресет} (см. ``assign``; узлом
    служит корень модуля, уровень модуля — агрегат по поддереву). Зовётся
    лениво, из ``auth()`` тестов аппки, а не автофикстурой: действующая
    компания в реестре мешала бы тестам веера по компаниям (см. докстринг
    ``apps/tasks/tests/helpers.py``). Идемпотентна.
    """
    from apps.companies.models import Company, CompanyKind

    Company.objects.get_or_create(
        slug=slug, defaults={"name": slug, "kind": CompanyKind.SERVICE})
    for user_id, modules in grants.items():
        for module, level in modules.items():
            assign(slug, user_id, module, level)
    return slug
```

В каждой аппке: константа `COMPANY = "t-<аппка>-gate"`, токены тестов несут `company=COMPANY`, `auth()`/`auth_header()` зовёт `gate_company(COMPANY, {...})` и кладёт `HTTP_X_HTQ_COMPANY=COMPANY`. Уровни: рядовой вызывающий — уровень `employee-basic` модуля (таблица Global Constraints), `admin_token()`/администратор — `"full"`. **Каждый id «постороннего» пользователя, на котором тест проверяет собственную проверку** (не участник, не автор, не согласующий), получает тот же уровень, что рядовой: иначе 403 даст гейт, а не проверка, которую тест заявляет (прецедент — пользователь 555 в `apps/tasks/tests/helpers.py`).

**Реестр.** В `backend/apps/access/self_service.py`: аппка — в `TRANSLATED_APPS`; в `SELF_SERVICE` — ключ аппки (пустой словарь, если записей нет) и записи `self` с комментарием-доказательством строкой сервиса (стиль существующих записей).

**Файл ролей аппки** `backend/apps/<аппка>/tests/test_gate_roles.py` — поведение с НАСТОЯЩИМИ ролями (`employee-basic`, `services-admin` из миграций), не синтетическими:

```python
def _as(role_code: str, user_id: int) -> dict:
    """Заголовки вызывающего с одной настоящей ролью в компании теста."""
    from apps.access.models import Role, RoleAssignment, ScopeKind
    from apps.companies.models import Company, CompanyKind

    Company.objects.get_or_create(slug=COMPANY, defaults={
        "name": COMPANY, "kind": CompanyKind.SERVICE})
    RoleAssignment.objects.get_or_create(
        company_slug=COMPANY, user_id=user_id, role=Role.objects.get(code=role_code),
        scope_kind=ScopeKind.COMPANY, scope_id=None)
    return {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=user_id, sub=str(user_id), company=COMPANY)}",
            "HTTP_X_HTQ_COMPANY": COMPANY}
```

(`token` — помощник токенов аппки; если у аппки его нет — `apps.access.tests.helpers.token`.) Минимум три теста: `employee-basic` — не 403 на типовую ручку сотрудника; `employee-basic` — 403 на бывшую админскую; `is_staff` без роли — 403 на неё же; `services-admin` — не 403 на неё же. Проверять «не 403» (`status_code != 403`), а не 200: предметный ответ зависит от данных.

**Прогон.** Весь набор тестов аппки + `apps/access/tests/test_gate.py`. Каждое новое падение 403 чинится помощником/ролью в тесте, **не ослаблением гейта и не понижением уровня**; тест, падающий по другой причине, — находка в отчёт.

---

### Task 4: `media_files` — модуль `media`

**Files:**
- Modify: `backend/apps/media_files/views.py` (`upload_file` :71, `list_files` :166, `issue_signed_url` :404)
- Modify: `backend/apps/access/tests/helpers.py` (функция `gate_company` из шаблона)
- Modify: `backend/apps/access/self_service.py` (`TRANSLATED_APPS` += `"media_files"`, `SELF_SERVICE["media_files"] = {}`)
- Modify: тесты `backend/apps/media_files/tests/**` (заголовок компании, роли)
- Create: `backend/apps/media_files/tests/test_gate_roles.py`

**Interfaces:**
- Produces: `apps.access.tests.helpers.gate_company(slug, grants) -> str` — используют задачи 5–9.

- [ ] **Step 1: Падающий тест ролей** — `backend/apps/media_files/tests/test_gate_roles.py` (заголовок `_as` — из шаблона выше, `COMPANY = "t-media-gate"`, `token` — `apps.access.tests.helpers.token`):

```python
import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-media-gate"
BASE = "/api/media/v1"

# _as(role_code, user_id) — как в шаблоне задач 4–9 плана блока L


@pytest.mark.django_db
def test_employee_basic_may_not_list_every_file():
    assert Client().get(f"{BASE}/files/", **_as("employee-basic", 301)).status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_list_every_file():
    headers = _as("employee-basic", 302)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=302, sub="302", company=COMPANY, is_staff=True, is_admin=True)
    assert Client().get(f"{BASE}/files/", **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_lists_files():
    assert Client().get(f"{BASE}/files/", **_as("services-admin", 303)).status_code != 403


@pytest.mark.django_db
def test_employee_basic_passes_the_upload_gate():
    resp = Client().post(f"{BASE}/files/", data={}, **_as("employee-basic", 304))
    assert resp.status_code != 403   # 422 без файла — это уже сама ручка
```

- [ ] **Step 2: Прогнать — падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/media_files/tests/test_gate_roles.py -q -p no:cacheprovider`
Expected: FAIL двух тестов: `test_staff_without_a_role_may_not_list_every_file` (сегодня `admin=True` пускает `is_staff`, ответ не 403) и `test_services_admin_lists_files` (держатель роли без `is_staff` получает 403 от `admin=True`). Два других проходят и сегодня — они закрепляют, что сотрудник не получил лишнего.

- [ ] **Step 3: Гейт** — в `backend/apps/media_files/views.py`: `upload_file` → `module="media", level="write"`; `issue_signed_url` → `module="media", level="write"`; `list_files` — `admin=True` заменить на `module="media", level="admin"`. `download_file`, `download_variant`, `serve_raw_key` (`auth=None`) не трогать.

- [ ] **Step 4: Помощник и реестр** — добавить `gate_company` в `backend/apps/access/tests/helpers.py` (код — в шаблоне); в `self_service.py` `TRANSLATED_APPS` дополнить `"media_files"`, в `SELF_SERVICE` — `"media_files": {}` с комментарием «строго своих ручек нет: загрузка и подпись — под `media:write`, чтение — `auth=None` с подписью».

- [ ] **Step 5: Тесты аппки** — прогнать `apps/media_files`; каждое 403 от гейта чинить заголовком компании и ролью: рядовой — `{"media": "write"}`, администратор — `{"media": "full"}` (правила шаблона).

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/media_files apps/access/tests/test_gate.py apps/access/tests/test_block_l_roles.py -q -p no:cacheprovider`
Expected: PASS; сторожа блока L теперь проверяют `media_files` (`module="media"`, `list_files` выше `write`).

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/media_files/views.py backend/apps/access/tests/helpers.py backend/apps/access/self_service.py backend/apps/media_files/tests/<правленные файлы поимённо> backend/apps/media_files/tests/test_gate_roles.py
git commit -m "feat(media): гейт модуля media на ручках файлов, admin=True снят"
```

---

### Task 5: `conference`

**Files:**
- Modify: `backend/apps/conference/views.py` (`overview` :83, `sessions` :90, `session_detail` :110, `session_events` :117, `session_transcript` :125)
- Modify: `backend/apps/conference/tests/conftest.py` (`auth_header` — компания и роль)
- Modify: `backend/apps/access/self_service.py` (`TRANSLATED_APPS` += `"conference"`, `SELF_SERVICE["conference"] = {}`)
- Create: `backend/apps/conference/tests/test_gate_roles.py`

**Interfaces:**
- Consumes: `apps.access.tests.helpers.gate_company` (задача 4).

- [ ] **Step 1: Падающий тест ролей** — `backend/apps/conference/tests/test_gate_roles.py` (`_as` — из шаблона, `COMPANY = "t-conference-gate"`, `token` — `apps.access.tests.helpers.token`):

```python
import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-conference-gate"
BASE = "/api/conference/v1"

# _as(role_code, user_id) — как в шаблоне задач 4–9 плана блока L


@pytest.mark.django_db
def test_employee_basic_reads_his_history():
    assert Client().get(f"{BASE}/sessions", **_as("employee-basic", 311)).status_code != 403


@pytest.mark.django_db
def test_no_role_no_history():
    headers = {"HTTP_AUTHORIZATION": "Bearer " + token(user_id=312, sub="312", company=COMPANY),
               "HTTP_X_HTQ_COMPANY": COMPANY}
    from apps.companies.models import Company, CompanyKind
    Company.objects.get_or_create(slug=COMPANY, defaults={"name": COMPANY,
                                                          "kind": CompanyKind.SERVICE})
    assert Client().get(f"{BASE}/sessions", **headers).status_code == 403
```

(Бывших `admin=True` в аппке нет — тестов staff/services-admin на админскую ручку здесь нет.)

- [ ] **Step 2: Прогнать — падает** `test_no_role_no_history` (сегодня гейта нет, ответ 200).

Run: `../.venv/Scripts/python.exe -m pytest apps/conference/tests/test_gate_roles.py -q -p no:cacheprovider`

- [ ] **Step 3: Гейт** — пять ручек чтения → `module="conference", level="read"`. `session_recording`, `session_poster`, пять `internal_*` (`auth=None`) не трогать. `may_view` и отказ 404 — не трогать.

- [ ] **Step 4: Реестр** — `TRANSLATED_APPS` += `"conference"`; `SELF_SERVICE["conference"] = {}` с комментарием «чтение своих встреч — под `conference:read`, видимость режет `services/access.may_view`».

- [ ] **Step 5: Тесты аппки** — `auth_header(user)` в `backend/apps/conference/tests/conftest.py`:

```python
COMPANY = "t-conference-gate"


def auth_header(user: User) -> dict:
    from apps.access.tests.helpers import gate_company

    level = "full" if user.is_staff else "read"
    gate_company(COMPANY, {user.id: {"conference": level}})
    access = issue_token_pair(user, company_slug=COMPANY)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {access}", "HTTP_X_HTQ_COMPANY": COMPANY}
```

(Сверить сигнатуру `htqweb/authn/jwt.py::issue_token_pair` — имя параметра компании; если выпуск токена с компанией требует членства — завести `CompanyMembership` в `gate_company`-вызове этой аппки или собрать токен через `apps.access.tests.helpers.token(user_id=user.id, sub=str(user.id), company=COMPANY, is_staff=user.is_staff, is_admin=user.is_staff)`.) Прогнать `apps/conference`, чинить 403 по правилам шаблона.

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/conference apps/access/tests/test_gate.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/conference/views.py backend/apps/conference/tests/conftest.py backend/apps/access/self_service.py backend/apps/conference/tests/test_gate_roles.py <прочие правленные тесты поимённо>
git commit -m "feat(conference): гейт модуля conference на чтении встреч"
```

---

### Task 6: `messenger`

**Files:**
- Modify: `backend/apps/messenger/views.py` (26 ручек, строки по спеке §6.3)
- Modify: `backend/apps/access/self_service.py` (`TRANSLATED_APPS` += `"messenger"`, `SELF_SERVICE["messenger"]`)
- Modify: тесты `backend/apps/messenger/tests/**`
- Create: `backend/apps/messenger/tests/test_gate_roles.py`

**Interfaces:**
- Consumes: `gate_company` (задача 4).

- [ ] **Step 1: Падающий тест ролей** — `backend/apps/messenger/tests/test_gate_roles.py` (`_as` — из шаблона, `COMPANY = "t-messenger-gate"`):

```python
import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-messenger-gate"
BASE = "/api/messenger/v1"

# _as(role_code, user_id) — как в шаблоне задач 4–9 плана блока L


@pytest.mark.django_db
def test_employee_basic_lists_his_rooms():
    assert Client().get(f"{BASE}/rooms", **_as("employee-basic", 321)).status_code != 403


@pytest.mark.django_db
def test_employee_basic_may_not_moderate():
    assert Client().get(f"{BASE}/admin/rooms", **_as("employee-basic", 322)).status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_moderate():
    headers = _as("employee-basic", 323)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=323, sub="323", company=COMPANY, is_staff=True, is_admin=True)
    assert Client().get(f"{BASE}/admin/rooms", **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_moderates():
    assert Client().get(f"{BASE}/admin/rooms", **_as("services-admin", 324)).status_code != 403
```

- [ ] **Step 2: Прогнать — падают** `test_staff_without_a_role_may_not_moderate` (сегодня `admin=True` пускает staff) и `test_services_admin_moderates`.

- [ ] **Step 3: Гейт** — в `backend/apps/messenger/views.py`:
  - `module="messenger", level="read"`: `_list_rooms`, `_get_room`, `users_presence`, `send_message`, `list_messages`, `mark_message_read`, `publish_typing`, `upload_attachment`, `get_user_keys`, `search_users`;
  - `module="messenger", level="write"`: `_create_room`, `_update_room`, `_delete_room`, `add_participants`, `_remove_participant`, `_set_participant_role`, `_edit_message`, `_delete_message`;
  - `admin=True` → `module="messenger", level="admin"`: `admin_list_rooms`, `admin_list_room_messages`, `admin_trigger_history_archive`;
  - не трогать: `unread_count`, `upload_keys`, `me` (в реестр), `serve_attachment`, `serve_attachment_thumb` (`auth=None`).

- [ ] **Step 4: Реестр** — `TRANSLATED_APPS` += `"messenger"`;

```python
    "messenger": {
        # бейдж шапки: msg_svc.unread_total(request.token.user_id) — свой
        # счётчик, без параметра; зовётся и с голого домена (Header), где
        # гейта модуля быть не может — компании нет.
        "unread_count": "self",
        # свои E2EE-ключи: device_id и ключ пишутся под request.token.user_id.
        "upload_keys": "self",
        # users/me — свой профиль в мессенджере по request.token.user_id.
        "me": "self",
    },
```

(Перед записью сверить каждое утверждение строкой сервиса; если параметр указывает на чужой объект — не `self`, а `read`, и отметить в отчёте.)

- [ ] **Step 5: Тесты аппки** — рядовой вызывающий `{"messenger": "write"}`, администратор `{"messenger": "full"}`; прогнать `apps/messenger`, чинить 403 по правилам шаблона. Socket.IO (`apps/messenger/socket.py`) и его тесты — вне блока, не трогать.

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/messenger apps/access/tests/test_gate.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/messenger/views.py backend/apps/access/self_service.py backend/apps/messenger/tests/test_gate_roles.py <правленные тесты поимённо>
git commit -m "feat(messenger): гейт модуля messenger, модерация — по роли вместо admin=True"
```

---

### Task 7: `mail`

**Files:**
- Modify: `backend/apps/mail/views.py` (21 ручка под гейт, 20 — в реестр)
- Modify: `backend/apps/access/self_service.py`
- Modify: тесты `backend/apps/mail/tests/**` (в первую очередь `test_mailboxes_api.py`, `test_mail_settings_api.py`, `test_mailbox_*`, `test_reconcile.py` — они ходят в админские ручки)
- Create: `backend/apps/mail/tests/test_gate_roles.py`

- [ ] **Step 1: Падающий тест ролей** — `backend/apps/mail/tests/test_gate_roles.py` (`_as` — из шаблона, `COMPANY = "t-mail-gate"`):

```python
import pytest
from django.test import Client

from apps.access.tests.helpers import token

COMPANY = "t-mail-gate"
BASE = "/api/email/v1"

# _as(role_code, user_id) — как в шаблоне задач 4–9 плана блока L


@pytest.mark.django_db
def test_employee_basic_may_not_manage_mailboxes():
    assert Client().get(f"{BASE}/mailboxes/", **_as("employee-basic", 331)).status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_manage_mailboxes():
    headers = _as("employee-basic", 332)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=332, sub="332", company=COMPANY, is_staff=True, is_admin=True)
    assert Client().get(f"{BASE}/mailboxes/", **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_manages_mailboxes():
    assert Client().get(f"{BASE}/mailboxes/", **_as("services-admin", 333)).status_code != 403


@pytest.mark.django_db
def test_own_mail_stays_self_service():
    assert Client().get(f"{BASE}/accounts/", **_as("employee-basic", 334)).status_code != 403
```

- [ ] **Step 2: Прогнать — падают** `…staff…` и `test_services_admin_manages_mailboxes`.

- [ ] **Step 3: Гейт** — в `backend/apps/mail/views.py`:
  - `module="mail", level="read"`: `_imap_connect_hint`;
  - `admin=True` → `module="mail", level="admin"`: `_list_mailboxes`, `_create_mailbox`, `_get_mailbox`, `_update_mailbox`, `_delete_mailbox`, `reset_mailbox_password`, `archive_mailbox`, `restore_mailbox`, `mailbox_status`, `mailbox_lookup`, `_get_mail_settings`, `_put_mail_settings`, `test_mail_connection`, `mailbox_coverage`, `_reconcile_report`, `_reconcile_apply`, `_list_aliases`, `_create_alias`, `delete_alias`, `set_forwarding`;
  - не трогать: `oauth_callback` (`auth=None`), `apps/mail/webhooks.py`, и 20 ручек реестра ниже.

- [ ] **Step 4: Реестр** — `TRANSLATED_APPS` += `"mail"`; `SELF_SERVICE["mail"]` — 20 записей `"self"`: `accounts_collection`, `account_set_default`, `account_sync`, `account_signature`, `account_detail`, `corporate_connect_info`, `_corporate_connect`, `_corporate_disconnect`, `_imap_connect`, `imap_account_password`, `oauth_status`, `oauth_accounts`, `oauth_connect`, `oauth_disconnect`, `list_emails`, `unread_counts`, `get_email`, `send_email`, `mark_as_read`, `save_draft`. Над блоком — общий комментарий: «личная почта — аккаунт, OAuth и письма привязаны к `request.token.user_id`, сервис отвечает 404 (`AccountNotFound`/`EmailNotFound`) на чужой id (докстринг `apps/mail/views.py`)». Для каждой записи проверить строку сервиса; ручку, где параметр не пересекается с фильтром `user_id`, — не в реестр, а под `module="mail", level="read"` (чтение) или `"read"` (запись своего — узел `mail.messages` только `view`), с отметкой в отчёте.

- [ ] **Step 5: Тесты аппки** — рядовой `{"mail": "read"}`, администратор `{"mail": "full"}`; прогнать `apps/mail`, чинить 403 по правилам шаблона.

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/mail apps/access/tests/test_gate.py -q -p no:cacheprovider` (если дольше 10 минут — `apps/mail/tests/test_[a-l]*.py` и `test_[m-z]*.py` отдельно)
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/mail/views.py backend/apps/access/self_service.py backend/apps/mail/tests/test_gate_roles.py <правленные тесты поимённо>
git commit -m "feat(mail): гейт модуля mail на ящиках, личная почта — самообслуживание"
```

---

### Task 8: `cms` и проверка организатора приглашений

**Files:**
- Modify: `backend/apps/cms/views.py` (30 ручек под гейт; приглашения :691–:797)
- Modify: `backend/apps/cms/services/conference_invite_service.py` (новая `may_manage_invites`, `revoke` с проверкой)
- Modify: `backend/apps/access/self_service.py`
- Modify: тесты `backend/apps/cms/tests/**` (`test_news_api.py`, `test_contact_requests_api.py`, `test_home_sections_api.py`, `test_taxonomy_api.py`, `test_conference_invites.py`, `test_conference_config.py`)
- Create: `backend/apps/cms/tests/test_gate_roles.py`

**Interfaces:**
- Consumes: `apps.tasks.interface.get_conference_event_for_room(room_id) -> dict | None` (ключ `creator_id`), `apps.access.interface.permission_level(token, module, company) -> str`, `htqweb.tenancy.context.current_company_or_none()`, `apps.core.services.ServiceDisabled` (сверить модуль исключения).
- Produces: `conference_invite_service.may_manage_invites(token, room_id: str, invite: ConferenceInvite | None = None) -> bool`.

- [ ] **Step 1: Падающие тесты** — `backend/apps/cms/tests/test_gate_roles.py` (`_as` — из шаблона, `COMPANY = "t-cms-gate"`):

```python
import pytest
from django.test import Client

from apps.access.tests.helpers import post_json, token
from apps.cms.models import ConferenceInvite

COMPANY = "t-cms-gate"
BASE = "/api/cms/v1"

# _as(role_code, user_id) — как в шаблоне задач 4–9 плана блока L


@pytest.mark.django_db
def test_employee_basic_may_not_edit_news():
    resp = post_json(Client(), f"{BASE}/news/", {"title": "x"}, **_as("employee-basic", 341))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_edit_news():
    headers = _as("employee-basic", 342)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=342, sub="342", company=COMPANY, is_staff=True, is_admin=True)
    assert post_json(Client(), f"{BASE}/news/", {"title": "x"}, **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_edits_news():
    resp = post_json(Client(), f"{BASE}/news/", {"title": "x"}, **_as("services-admin", 343))
    assert resp.status_code != 403


@pytest.mark.django_db
def test_employee_basic_reads_conference_config():
    assert Client().get(f"{BASE}/conference/config",
                        **_as("employee-basic", 344)).status_code != 403


def _invite(room_id="room-x", author=350):
    return ConferenceInvite.objects.create(room_id=room_id, created_by_id=author, title="t")


@pytest.mark.django_db
def test_stranger_cannot_revoke_or_see_someone_elses_invite():
    invite = _invite()
    stranger = _as("employee-basic", 351)
    assert Client().delete(f"{BASE}/conference/invites/{invite.id}", **stranger).status_code == 404
    listed = Client().get(f"{BASE}/conference/invites?room_id=room-x", **stranger).json()
    assert listed == []


@pytest.mark.django_db
def test_author_revokes_his_invite():
    invite = _invite(author=352)
    resp = Client().delete(f"{BASE}/conference/invites/{invite.id}", **_as("employee-basic", 352))
    assert resp.status_code == 204


@pytest.mark.django_db
def test_services_admin_sees_every_invite():
    _invite()
    listed = Client().get(f"{BASE}/conference/invites?room_id=room-x",
                          **_as("services-admin", 353)).json()
    assert len(listed) == 1


@pytest.mark.django_db
def test_invite_check_survives_disabled_tasks(monkeypatch):
    from apps.cms.services import conference_invite_service as svc
    from apps.core.services import ServiceDisabled

    def disabled(room_id):
        raise ServiceDisabled("tasks")

    monkeypatch.setattr(svc.tasks_interface, "get_conference_event_for_room", disabled)
    invite = _invite(author=354)
    resp = Client().delete(f"{BASE}/conference/invites/{invite.id}", **_as("employee-basic", 354))
    assert resp.status_code == 204
```

(Сверить обязательные поля `ConferenceInvite` в `apps/cms/models.py` — токен/срок могут требоваться; если так — создать через `conference_invite_service.create_invite(room_id=…, created_by_id=…)`. Сверить конструктор `ServiceDisabled`.) Плюс тест организатора: событие календаря — в `apps/cms/tests/test_conference_invites.py`, если там уже есть фабрика события `tasks` (`CalendarEvent` с `event_type="conference"`, `conference_room_id`), — организатор события (`creator_id`) видит и отзывает чужую ссылку своей встречи; если фабрики нет — `monkeypatch` `svc.tasks_interface.get_conference_event_for_room` → `{"creator_id": 355, …}` и проверка 204 для 355.

- [ ] **Step 2: Прогнать — падают** staff/services-admin на новостях, стороннее чтение и отзыв приглашения (сегодня 200/204).

- [ ] **Step 3: Проверка организатора** — в `backend/apps/cms/services/conference_invite_service.py`:

```python
from apps.tasks import interface as tasks_interface


def may_manage_invites(token, room_id: str, invite: ConferenceInvite | None = None) -> bool:
    """Управлять ссылками встречи: организатор события, автор ссылки или cms:admin.

    Блок L, спека §7. До этой проверки список ссылок комнаты (с токенами
    входа), отзыв и рассылка были доступны любому вошедшему. Организатор —
    creator_id календарного события комнаты; комнаты без события (кнопка
    «Создать комнату») обслуживает автор ссылки. Выключенный у компании
    tasks не роняет проверку: условие организатора просто ложно.
    """
    from apps.access import interface as access
    from apps.core.services import ServiceDisabled
    from htqweb.tenancy.context import current_company_or_none

    if token.is_superuser:
        return True
    if access.permission_level(token, "cms", current_company_or_none()) == "admin":
        return True
    if invite is not None and invite.created_by_id == token.user_id:
        return True
    try:
        event = tasks_interface.get_conference_event_for_room(room_id)
    except ServiceDisabled:
        event = None
    return bool(event) and event.get("creator_id") == token.user_id
```

`revoke(invite_id)` — сигнатура остаётся; проверка — во вьюхе (ниже), чтобы сервис не знал токена там, где его зовут без запроса.

- [ ] **Step 4: Ручки приглашений** — в `backend/apps/cms/views.py`:

```python
@api_view(methods=("POST",), body=schemas.ConferenceInviteCreate, status=201,
          module="cms", level="read")
def _create_conference_invite(request, data: schemas.ConferenceInviteCreate):
    # тело без изменений


@api_view(methods=("GET",), module="cms", level="read")
def _list_conference_invites(request):
    room_id = request.GET.get("room_id", "")
    if not room_id:
        return json_error("room_id is required", 422)
    return [
        schemas.ConferenceInviteRead.model_validate(
            conference_invite_service.serialize(inv, base_url=_origin(request)))
        for inv in conference_invite_service.list_for_room(room_id)
        if conference_invite_service.may_manage_invites(request.token, room_id, inv)
    ]


@api_view(methods=("DELETE",), status=204, module="cms", level="read")
def conference_invite_revoke(request, invite_id: int):
    invite = ConferenceInvite.objects.filter(pk=invite_id).first()
    if invite is None or not conference_invite_service.may_manage_invites(
            request.token, invite.room_id, invite):
        return json_error("Приглашение не найдено", 404)
    try:
        conference_invite_service.revoke(invite_id)
    except conference_invite_service.InviteInvalid as exc:
        return json_error(exc.detail, 404)
    return HttpResponse(status=204)


@api_view(methods=("POST",), body=schemas.ConferenceInviteSend,
          module="cms", level="read")
def conference_invite_send(request, invite_id: int, data: schemas.ConferenceInviteSend):
    """Отправить ссылку почтой и/или уведомлением в мессенджер."""
    invite = ConferenceInvite.objects.filter(pk=invite_id).first()
    if invite is None or not conference_invite_service.may_manage_invites(
            request.token, invite.room_id, invite):
        return json_error("Приглашение не найдено", 404)
    # дальше — тело без изменений
```

Уровень `read` у четырёх ручек приглашений — инвариант L1 (`write` в `cms` занят контентом), защищает их `may_manage_invites`.

- [ ] **Step 5: Остальной гейт** — `conference_config` → `module="cms", level="read"`; 25 бывших `admin=True` (список `FORMER_ADMIN_HANDLES["cms"]` в `test_gate.py`) → `admin=True` заменить на `module="cms", level="write"`. `auth=None` (`_create_contact_request`, `_list_news`, `news_by_slug`, `_get_news`, `_list_categories`, `_list_tags`, `home_sections_public`, `conference_invite_public`, `conference_invite_guest_token`) не трогать. Внутренний `_is_admin(user)` в `apps/cms/services/news_service.py:47` (черновики в публичном списке) — не трогать (§10 спеки).

- [ ] **Step 6: Реестр** — `TRANSLATED_APPS` += `"cms"`; `SELF_SERVICE["cms"] = {}` с комментарием «контент — под `cms:write`, приглашения — `cms:read` + `may_manage_invites`, публичное — `auth=None`».

- [ ] **Step 7: Тесты аппки** — рядовой `{"cms": "read"}`, редактор/администратор `{"cms": "full"}` (бывший `admin_token`); прогнать `apps/cms`, чинить 403 по правилам шаблона. Существующие тесты `test_conference_invites.py`, ожидающие, что посторонний видит/отзывает ссылку, — это закреплённая дыра: переписать ожидание на 404/пустой список и отметить в отчёте.

- [ ] **Step 8: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/cms apps/access/tests/test_gate.py apps/core/tests/test_app_isolation.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 9: Коммит**

```bash
git add backend/apps/cms/views.py backend/apps/cms/services/conference_invite_service.py backend/apps/access/self_service.py backend/apps/cms/tests/test_gate_roles.py <правленные тесты поимённо>
git commit -m "feat(cms): гейт модуля cms, контент по роли; приглашения — только организатору и автору"
```

---

### Task 9: `approvals`

**Files:**
- Modify: `backend/apps/approvals/views.py` (46 ручек)
- Modify: `backend/apps/approvals/tests/helpers.py` (компания и роли в `auth()`)
- Modify: `backend/apps/access/self_service.py`
- Create: `backend/apps/approvals/tests/test_gate_roles.py`

- [ ] **Step 1: Падающий тест ролей** — `backend/apps/approvals/tests/test_gate_roles.py` (`_as` — из шаблона, `COMPANY = "t-approvals-gate"`, `token` — `apps.approvals.tests.helpers.token`):

```python
import pytest
from django.test import Client

from apps.approvals.tests.helpers import BASE, post_json, token

COMPANY = "t-approvals-gate"

# _as(role_code, user_id) — как в шаблоне задач 4–9 плана блока L


@pytest.mark.django_db
def test_employee_basic_reads_templates_to_file_a_request():
    assert Client().get(f"{BASE}/templates/", **_as("employee-basic", 361)).status_code != 403


@pytest.mark.django_db
def test_employee_basic_may_not_create_a_project():
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "p"}, **_as("employee-basic", 362))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_create_a_project():
    headers = _as("employee-basic", 363)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=363, sub="363", company=COMPANY, is_staff=True, is_admin=True)
    assert post_json(Client(), f"{BASE}/projects/", {"name": "p"}, **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_creates_a_project():
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "p"}, **_as("services-admin", 364))
    assert resp.status_code != 403
```

- [ ] **Step 2: Прогнать — падают** `…staff…` и `test_services_admin_creates_a_project`.

- [ ] **Step 3: Гейт** — в `backend/apps/approvals/views.py`:
  - `module="approvals", level="read"`: `_list_instances`, `_get_instance`, `approve`, `reject`, `request_changes`, `recall`, `batch_approve`, `_list_projects`, `_get_project`, `_list_members`, `_list_templates`, `_get_template`, `get_version`, `stats_overview`, `stats_by_project`, `stats_by_template`, `stats_by_actor`, `stats_heatmap`, `list_sources`, `my_data_tables`, `get_source`, `list_rows`, `reference_options`;
  - `module="approvals", level="write"`: `_create_instance`, `_update_instance`, `submit_instance`, `resubmit_instance`, `cancel`, `_update_project`, `_add_member`, `remove_member`, `_create_template`, `_update_template`, `_delete_template`, `deactivate_template`, `activate_template`, `publish_version`, `preview_template`, `set_data_table_access`;
  - `admin=True` → `module="approvals", level="admin"`: `_create_project`, `_delete_project`, `create_source`, `update_source`, `delete_source`, `add_row`, `delete_row`;
  - `stream` (SSE, без `api_view`) — не трогать. Внутренние проверки (`ensure_can_manage_project/_template`, `request_runtime.act`, `can_manage_data_table`, `_is_admin` в `views.py:827`) — не трогать.

- [ ] **Step 4: Помощники** — в `backend/apps/approvals/tests/helpers.py`:

```python
COMPANY = "t-approvals-gate"


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7", "company": COMPANY,
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def auth(tok: str | None = None) -> dict:
    from apps.access.tests.helpers import gate_company

    gate_company(COMPANY, {7: {"approvals": "write"}, 9: {"approvals": "full"}})
    return {"HTTP_AUTHORIZATION": f"Bearer {tok or token()}",
            "HTTP_X_HTQ_COMPANY": COMPANY}
```

(Прогнать `apps/approvals`; каждый id согласующего/постороннего, которого тесты используют (`approver_id=11` в `simple_workflow` и т.д.), добавить в `grants` с `{"approvals": "write"}` — правило «постороннего» из шаблона.)

- [ ] **Step 5: Реестр** — `TRANSLATED_APPS` += `"approvals"`; `SELF_SERVICE["approvals"] = {}` с комментарием «заявка — общий объект (инициатор, согласующие, наблюдатели): своё над ней — `write`/`read` + собственные проверки, не `self`».

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/approvals apps/access/tests/test_gate.py -q -p no:cacheprovider`
Expected: PASS; все шесть блок-L-аппок в `TRANSLATED_APPS`, сторожа L1 зелёные по всем.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/approvals/views.py backend/apps/approvals/tests/helpers.py backend/apps/access/self_service.py backend/apps/approvals/tests/test_gate_roles.py <правленные тесты поимённо>
git commit -m "feat(approvals): гейт модуля approvals, проекты и справочники — по роли вместо admin=True"
```

---

### Task 10: Фронт — «Мессенджер» и «Почта» по уровню модуля

**Files:**
- Modify: `frontend/src/app/navigation/navItems.ts` (`NavRequirement`, `NavAbilities`, `allowed`, пункты `messenger`/`email`)
- Modify: `frontend/src/components/Header.tsx:122-127`, `frontend/src/components/BottomNav.tsx:37-42` (новые поля способностей)
- Modify: `frontend/src/components/profile/ProfileSidebar.tsx:273-283` (пункты мессенджера, конференций, почты)
- Test: `frontend/src/app/navigation/navItems.test.ts`

- [ ] **Step 1: Тест** — в `navItems.test.ts` заменить `FULL`/`PLAIN` и тест «рядовой сотрудник…»:

```typescript
const FULL: NavAbilities = {
  isEditor: true, isHr: true, hasTasks: true, hasDepartment: true,
  hasMessenger: true, hasMail: true,
};
const PLAIN: NavAbilities = {
  isEditor: false, isHr: false, hasTasks: false, hasDepartment: false,
  hasMessenger: true, hasMail: true,
};
const NO_COMMS: NavAbilities = { ...PLAIN, hasMessenger: false, hasMail: false };
```

и добавить:

```typescript
  it('без доступа к мессенджеру и почте их пунктов нет (иначе клик — 403)', () => {
    const ids = visibleNavItems(NO_COMMS).map((i) => i.id);
    expect(ids).not.toContain('messenger');
    expect(ids).not.toContain('email');
  });
```

(Существующие проверки `expect(ids).toContain('messenger'|'email')` для `PLAIN` остаются — у рядового сотрудника `employee-basic` даёт оба модуля.)

- [ ] **Step 2: Прогнать — падает** (`hasMessenger` не существует в типе; `NO_COMMS` видит пункты).

Run (из `frontend/`): `npx vitest run src/app/navigation/navItems.test.ts`

- [ ] **Step 3: Реализация** — в `navItems.ts`:

```typescript
export type NavRequirement =
  'always' | 'editor' | 'hr' | 'tasks' | 'department' | 'messenger' | 'mail';
```

в `NavAbilities` добавить `hasMessenger: boolean; hasMail: boolean;`, в `allowed` — `case 'messenger': return a.hasMessenger;` и `case 'mail': return a.hasMail;`, у пунктов `messenger` и `email` — `requires: 'messenger'` и `requires: 'mail'`. В `Header.tsx` и `BottomNav.tsx` в объект способностей добавить:

```typescript
    hasMessenger: permissions.atLeast('messenger', 'read'),
    hasMail: permissions.atLeast('mail', 'read'),
```

В `ProfileSidebar.tsx` рядом с `const hasTasksAccess = …` завести

```typescript
    const hasMessenger = permissions.atLeast('messenger', 'read');
    const hasConference = permissions.atLeast('conference', 'read');
    const hasMail = permissions.atLeast('mail', 'read');
```

и `communicationItems` собрать условно (обработчики `gateService('conference')` сохранить как есть):

```typescript
    const communicationItems: ItemConfig[] = useMemo(() => [
        ...(hasMessenger ? [{ id: 'messenger', to: '/messenger', icon: MessageSquare, label: t('profile.sidebar.messenger', 'Мессенджер') }] : []),
        ...(hasConference ? [
            { id: 'conference', to: '/conference', icon: Video, label: t('profile.sidebar.conference', 'Видеоконференция'), onClick: gateService('conference') },
            { id: 'conference-history', to: '/conference/history', icon: History, label: t('profile.sidebar.conferenceHistory', 'История конференций'), onClick: gateService('conference') },
        ] : []),
        ...(hasMail ? [{ id: 'email', to: '/email', icon: Mail, label: t('profile.sidebar.email', 'Почта') }] : []),
        // комментарий про `isDisabled` в зависимостях — оставить как есть
    ], [t, isDisabled, hasMessenger, hasConference, hasMail]);
```

- [ ] **Step 4: Прогнать**

Run (из `frontend/`): `npx vitest run src/app/navigation src/components` — PASS; `npx tsc --noEmit -p tsconfig.json` — 0 ошибок; `npx vitest run` — не больше 8 известных; `npm run lint` — не больше 376.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/app/navigation/navItems.ts frontend/src/app/navigation/navItems.test.ts frontend/src/components/Header.tsx frontend/src/components/BottomNav.tsx frontend/src/components/profile/ProfileSidebar.tsx
git commit -m "feat(frontend): пункты мессенджера, почты и конференций — по уровню модуля"
```

---

### Task 11: Документы и итоговый прогон

**Files:**
- Modify: `CLAUDE.md` (раздел «Модель прав — одна»: пять аппок → одиннадцать; `services-admin`; `employee-basic` расширена; `core` вне; WS/SSE вне)
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` §4 строка «Роли», §10
- Modify: `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` (фраза про «остаток гейта — 7 аппок», найти `grep -n "approvals\`, \`cms\`" `)
- Modify: `docs/deploy/subdomains-runbook.md` — раздел «Блок L» (шаги §11 спеки)

- [ ] **Step 1: `CLAUDE.md`** — в «Модель прав — одна»: «пять аппок `hr/users/companies/access/tasks`» → «одиннадцать аппок: `hr/users/companies/access/tasks` (блок I) и `media_files` (модуль `media`), `conference`, `messenger`, `mail`, `cms`, `approvals` (блок L, `docs/plans/2026-09-24-block-l-gate-remaining-apps-spec.md`)»; отдельным пунктом: «**`admin=True` в блоке L снят**: экраны ящиков, модерации, контента, проектов заявок открывает роль `services-admin` (`access/0012`, «Администратор сервисов»), текущим `is_staff` её выдаёт `manage.py access_backfill_services_admin`; `employee-basic` расширена `access/0011` так, что сотрудник не теряет сегодняшнего доступа, и ни в одном из шести модулей не несёт `delete` (инвариант L1, сторожа `test_employee_basic_passes_every_non_admin_handle`/`test_no_former_admin_handle_is_open_to_employee_basic`). Вне гейта: `core` (не модуль прав), WebSocket мессенджера, SSE `approvals/stream`.» Проверить соседние фразы про «остальные аппки без гейта» и поправить.
- [ ] **Step 2: roadmap** — §4 строка «Роли…», колонка «Расхождение»: «`contracts`/`signoff` пока без гейта — вешают владельцы» оставить, добавить «шесть аппок платформы — под гейтом с блока L»; §10 — абзац «Гейт на семь оставшихся аппок … отдельными спеками» → «Гейт на шесть аппок платформы — блок L ([спека](2026-09-24-block-l-gate-remaining-apps-spec.md), [план](2026-09-24-block-l-gate-remaining-apps.md)); `core` не модуль прав. Архив «только чтение» — отдельной спекой.»
- [ ] **Step 3: stage2-spec** — в пометке про остаток гейта (сверка §6.4 п. 5 называла строки ~866–874) дописать «— закрыто блоком L для шести аппок; `core` не модуль прав».
- [ ] **Step 4: Чеклист выкатки** — в `docs/deploy/subdomains-runbook.md` раздел «Блок L» с шагами §11 спеки дословно (migrate_shared → `access_backfill_services_admin --dry-run` → запуск → открыть трафик → проверки сотрудника и администратора) и строкой «Не раньше поддоменов: гейт считает уровень только в контексте компании».
- [ ] **Step 5: Итоговый прогон** — бэкенд по частям (≤10 минут на команду): `apps/core htqweb`; `apps/access apps/companies apps/users`; `apps/hr` тремя частями; `apps/tasks`; `apps/mail apps/messenger apps/approvals`; `apps/conference apps/cms apps/media_files`; `apps/contracts apps/signoff`. Ожидание: падают только шесть тестов `backend/ci-known-failures.txt`. `makemigrations --check --dry-run` (окружение dev-БД из CLAUDE.md) — «No changes detected». Фронт: `tsc` 0, `vitest` ≤ 8 известных, `lint` ≤ 376. Проверка ссылок документов:

```bash
cd /c/Users/User/Desktop/HTQ-Web && ./.venv/Scripts/python.exe - <<'EOF'
import re, pathlib
bad = []
for f in ["CLAUDE.md", "docs/plans/2026-09-14-group-structure-roadmap.md",
          "docs/plans/2026-08-29-stage2-access-and-roles-spec.md",
          "docs/deploy/subdomains-runbook.md",
          "docs/plans/2026-09-24-block-l-gate-remaining-apps-spec.md",
          "docs/plans/2026-09-24-block-l-gate-remaining-apps.md"]:
    p = pathlib.Path(f); t = p.read_text(encoding="utf-8")
    for m in re.finditer(r"\]\(([^)#]+)(#[^)]*)?\)", t):
        target = m.group(1)
        if target.startswith("http"): continue
        if not (p.parent / target).resolve().exists(): bad.append(f"{f}: {target}")
    if ".superpowers/" in t and f != "docs/plans/2026-09-24-block-l-gate-remaining-apps.md":
        bad.append(f"{f}: упоминание .superpowers/")
print("\n".join(bad) or "ссылки: ok")
EOF
```

- [ ] **Step 6: Коммит**

```bash
git add CLAUDE.md docs/plans/2026-09-14-group-structure-roadmap.md docs/plans/2026-08-29-stage2-access-and-roles-spec.md docs/deploy/subdomains-runbook.md
git commit -m "docs: блок L — гейт на шести аппках, services-admin, чеклист выкатки"
```
