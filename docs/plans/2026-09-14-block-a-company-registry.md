# Блок A «Реестр компаний — из CLI в платформу» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реестр компаний группы становится частью платформы: HTTP-API и экран
дерева группы, переключатель компании в шапке, слепок раскладки таблиц для
безопасных выкаток, гейт «последнюю компанию не архивировать».

**Architecture:** Оркестрация жизненного цикла компании выносится из трёх
management-команд в `apps/companies/services/lifecycle.py`; команды и новые
CBV-вьюхи (`htqweb.http.ApiView`, `api_view` пометодно) зовут один и тот же
сервис. URL монтируются автодискавери по уже объявленному
`API_PREFIX = "api/companies/v1/"`. Фронт получает клиент `api/companies.ts`,
хук `useMyCompanies`, `CompanySwitcher` в `Header` и страницу `/companies`.
**Создание компании через HTTP в блоке не делается**: `migrate_company`
гонит миграции четырёх аппок около минуты, а `gunicorn --timeout 60`
(`docker-compose.yml`) убьёт воркер посреди DDL и оставит схему без таблиц при
живой строке реестра — ровно «осиротевшая строка» из CLAUDE.md. Заведение
остаётся `manage.py company_create`; экран это говорит словами.

**Tech Stack:** Django 5.2.7 / Python 3.14 (`backend/.venv`), Pydantic-схемы,
pytest-django против Postgres `:55432`; React + Vite, TanStack Query,
vitest + RTL, i18next с инлайн-фолбэками `t('key', 'текст')`.

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md)
§3 (режим перехода) и §5.A; контракт реестра —
[multi-company-tenancy-design.md §5](../multi-company-tenancy-design.md).

## Global Constraints

- Интерпретатор — корневой `.venv` (Python 3.13, Django 5.2.7; проверено
  14.09.2026 — `backend/.venv`, на который ссылается CLAUDE.md, больше не
  существует). Тесты: `docker compose -f docker-compose.test-local.yml up -d db`,
  затем из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
  Везде ниже `./.venv/Scripts/python.exe` читать как `../.venv/Scripts/python.exe`.
- Межаппный доступ — только `apps.<x>.interface`; `apps.core` — общий
  фундамент, его импортировать можно (`apps/core/tests/test_app_isolation.py`).
- Никаких межаппных FK; `user_id` — `IntegerField`.
- `APPEND_SLASH = False`: каждый путь в `urls.py` в двух написаниях.
- Конверт ошибок — `{"detail": ...}`; коды 401/403/404/409/422.
- `apps.companies` — общая аппка (`public`), не тенантная: обычные миграции.
- **Режим перехода (roadmap §3):** одна действующая компания
  `hi-tech-qazaqstan`; ни одна задача не переносит/не переименовывает/не
  удаляет таблицы `hr_*`, `tasks_*`, `contracts_*`, `signoff_*`; `regional`
  в `CompanyKind` остаётся принимаемым.
- **Зона:** `apps/contracts/**`, `apps/signoff/**` и их экраны не трогаются.
- **Ветки не создавать** — работа в выданной `structure-refactoring`.
- Коммиты — с `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Фронт: перед коммитом `npx tsc --noEmit -p tsconfig.json` и
  `npx vitest run <файлы>`; новый домен в `API_ENDPOINTS` обязан иметь правило
  в `vite.config.ts` (сторож `src/api/endpoints.proxy.test.ts`).

---

## Файловая структура

**Backend (создать):**
- `apps/companies/management/commands/tenancy_status.py` — слепок раскладки таблиц (только чтение).
- `apps/companies/migrations/0003_alter_company_kind.py` — расширение `CompanyKind` (choices, без SQL).
- `apps/companies/services/lifecycle.py` — provision / update / archive / restore + типизированные ошибки.
- `apps/companies/services/module_service.py` — список и переключение модулей компании.
- `apps/companies/schemas.py` — Pydantic-контракт `/api/companies/v1`.
- `apps/companies/views.py`, `apps/companies/urls.py`.
- `apps/companies/tests/api_helpers.py`, `test_tenancy_status.py`, `test_lifecycle.py`, `test_module_service.py`, `test_membership_service.py`, `test_api_read.py`, `test_api_write.py`, `test_api_modules_memberships.py`.

**Backend (изменить):**
- `apps/companies/models.py` — `CompanyKind`, `Company.parent_slug`.
- `apps/companies/services/membership_service.py` — `list_memberships`, `revoke_membership`.
- `apps/companies/management/commands/company_create.py`, `company_archive.py`, `company_restore.py` — тонкие обёртки над `lifecycle`.
- `CLAUDE.md` (команда `tenancy_status`), `API.md` (раздел companies), `docs/multi-company-tenancy-design.md` §1/§5, `STRUCTURE.md`.

**Frontend (создать):**
- `src/types/companies.ts`, `src/api/companies.ts`, `src/hooks/useMyCompanies.ts`.
- `src/components/companies/CompanySwitcher.tsx` (+ `.test.tsx`).
- `src/pages/companies/CompanyRegistry.tsx` (+ `.test.tsx`).
- `src/components/companies/CompanyFormDialog.tsx` (+ `.test.tsx`), `CompanyModulesPanel.tsx`, `CompanyMembersPanel.tsx` (+ `.test.tsx`).

**Frontend (изменить):**
- `src/api/endpoints.ts`, `vite.config.ts`, `src/components/Header.tsx`,
  `src/app/routing/lazyPages.ts`, `src/app/routing/routeDefinitions.ts`,
  `src/components/profile/ProfileSidebar.tsx`.

---

## Контракт API (замороженный на время блока)

Префикс `/api/companies/v1/`. Все ручки `auth="jwt"`.

| Метод | Путь | Гейт | Ответ |
|---|---|---|---|
| GET | `me` | jwt | `[MyCompany]` — компании, где у пользователя есть членство и которые действуют |
| GET | `companies?status=active\|archived\|all` | `module=companies, level=read` | `[CompanyRead]` (по умолчанию `all`) |
| GET | `companies/tree` | `module=companies, level=read` | `[CompanyTreeNode]` — корни дерева владения (только действующие) |
| GET | `companies/<slug>` | `module=companies, level=read` | `CompanyRead` |
| PATCH | `companies/<slug>` | `module=companies, level=write` + `is_superuser` | `CompanyRead`; тело `CompanyPatch` |
| POST | `companies/<slug>/archive` | `admin=True` + `is_superuser` | `CompanyRead`; 409 `last_active` |
| POST | `companies/<slug>/restore` | `admin=True` + `is_superuser` | `CompanyRead` |
| GET | `companies/<slug>/modules` | `module=companies, level=read` + своя компания | `[ModuleRead]` |
| PATCH | `companies/<slug>/modules/<app_label>` | `module=companies, level=write` + `is_superuser` | `ModuleRead`; 422 unknown, 409 core |
| GET | `companies/<slug>/memberships` | `module=companies, level=read` + своя компания | `[MembershipRead]` |
| POST | `companies/<slug>/memberships` | `module=companies, level=write` + `is_superuser` | `MembershipRead` (201; 200 если уже было) |
| DELETE | `companies/<slug>/memberships/<user_id>` | `admin=True` + `is_superuser` | 204; 409 `self_revoke` |

⚠️ **Исправлено по итогам финального ревью блока A.** `module=companies,
level=…` резолвит уровень в компании ВЫЗЫВАЮЩЕГО (`current_company_or_none()`
на стороне заголовка `X-HTQ-Company`) и ничего не знает про `<slug>` из URL —
как исходно записано в этой таблице, гейт сам по себе не мешал компании A
писать/читать строку компании B. Ревью нашло это как критическую (запись:
`PATCH companies/<slug>`, `PATCH .../modules/<app_label>`, `POST
.../memberships` — включая выдачу членства, то есть легитимного claim
`company` и целой тенантной схемы) и важную (чтение: `GET .../modules`, `GET
.../memberships` — состав ролей и `username`/`full_name`/`email` соседней
компании) находки. Исправление — второй, явный гейт внутри вьюхи поверх
табличного: `deny_unless_platform_admin` на трёх записывающих ручках (тот же
хелпер, что уже стоял на архиве/восстановлении/отзыве) и новый
`deny_unless_own_company` на двух читающих (пропускает суперпользователя или
компанию, совпадающую с `X-HTQ-Company`). Таблица выше — уже ИСПРАВЛЕННЫЙ
контракт; `PATCH`/`POST` на реестре и модулях/членстве теперь фактически
платформенные операции, несмотря на внешний декоратор `write`.

Формы:

```json
CompanyRead    {"id":1,"slug":"hi-tech-qazaqstan","name":"Hi-Tech Qazaqstan","kind":"construction",
                "status":"active","country":"KZ","parent_slug":null,"archived_at":null}
CompanyTreeNode{"slug":"...","name":"...","kind":"...","status":"active","country":"KZ","children":[...]}
MyCompany      {"slug":"...","name":"...","kind":"...","is_default":true,"is_current":true}
CompanyPatch   {"name"?: str, "kind"?: str, "country"?: str, "parent_slug"?: str|null}
ModuleRead     {"app_label":"tasks","enabled":true,"message":"","is_core":false}
ModulePatch    {"enabled": bool, "message"?: str}
MembershipRead {"user_id":7,"username":"ivanov","full_name":"Иванов Иван","email":"...","is_active":true,"is_default":false}
MembershipCreate {"user_id":7,"is_default"?: bool}
```

Почему `module=companies` на чтении, а не голый jwt: в `access_functions.py`
аппки уже объявлены `companies.registry/modules/memberships`, и реестр —
данные платформы, а не справочник. Без контекста компании (переходный
период, голый домен) `permission_level` даёт `none` всем, кроме
суперпользователя, — это и есть целевое поведение блока: реестр ведёт
платформенный администратор.

---

### Task 1: `tenancy_status` — слепок раскладки таблиц

**Files:**
- Create: `backend/apps/companies/management/commands/tenancy_status.py`
- Test: `backend/apps/companies/tests/test_tenancy_status.py`
- Modify: `CLAUDE.md` (раздел «Django management»)

**Interfaces:**
- Produces: `snapshot(*, exact: bool = False) -> dict` c ключами `exact`, `companies`, `schemas`, `holding_views`; команда `manage.py tenancy_status [--json] [--exact]`.

- [ ] **Step 1: Написать падающий тест**

```python
# backend/apps/companies/tests/test_tenancy_status.py
"""tenancy_status — слепок раскладки тенантных таблиц (roadmap §3, п.5).

Команда только читает: её результат до и после выкатки должен совпадать по
составу таблиц и компаний, иначе выкатка что-то унесла.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command

from htqweb.tenancy.context import schema_for


@pytest.mark.django_db
def test_json_snapshot_lists_registry_and_both_schemas(company_schema):
    out = StringIO()
    call_command("tenancy_status", "--json", stdout=out)
    data = json.loads(out.getvalue())

    company = next(c for c in data["companies"] if c["slug"] == company_schema["slug"])
    assert company["schema_exists"] is True
    assert company["schema"] == schema_for(company_schema["slug"])

    schema = schema_for(company_schema["slug"])
    # Тестовая база лежит в раскладке ДО bootstrap: те же таблицы есть и в
    # public, и в схеме компании — слепок обязан показать обе, не выбирая.
    assert "contracts_agreement" in data["schemas"]["public"]["tables"]
    assert "contracts_agreement" in data["schemas"][schema]["tables"]
    assert "signoff_approvalroute" in data["schemas"][schema]["tables"]
    assert set(data["schemas"][schema]["apps"]) == {"hr", "tasks", "contracts", "signoff"}
    assert data["exact"] is False


@pytest.mark.django_db
def test_text_output_names_each_company_and_schema(company_schema):
    out = StringIO()
    call_command("tenancy_status", stdout=out)
    text = out.getvalue()
    assert company_schema["slug"] in text
    assert schema_for(company_schema["slug"]) in text
    assert "Сводки holding" in text


@pytest.mark.django_db
def test_exact_mode_counts_rows(company_schema):
    out = StringIO()
    call_command("tenancy_status", "--json", "--exact", stdout=out)
    data = json.loads(out.getvalue())
    schema = schema_for(company_schema["slug"])
    assert data["exact"] is True
    assert data["schemas"][schema]["tables"]["signoff_approvalroute"] == 0
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_tenancy_status.py -q`
Expected: FAIL — `CommandError: Unknown command: 'tenancy_status'`.

- [ ] **Step 3: Написать команду**

```python
# backend/apps/companies/management/commands/tenancy_status.py
"""Слепок раскладки тенантных таблиц — ТОЛЬКО чтение.

Зачем. На время доводки структуры группы (docs/plans/2026-09-14-group-
structure-roadmap.md, §3) в реестре одна компания, а модули contracts и
signoff проходят боевые проверки. Каждая выкатка обязана доказать, что их
таблицы на месте и строки не пропали. Команда печатает, где лежит каждая
таблица тенантных аппок (``public`` или ``co_<slug>``), сколько в ней строк,
какие компании есть в реестре и есть ли под ними физические схемы;
``--json`` даёт форму, которую сохраняют и сравнивают diff'ом со слепком
после выкатки.

Ничего не пишет и не блокирует: ``information_schema``,
``pg_stat_user_tables`` (оценка планировщика; ``--exact`` — настоящий
``count(*)`` по каждой таблице, на больших таблицах долго) и реестр.
"""

import json

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from psycopg import sql

from apps.companies.models import Company
from apps.companies.services import schema_service
from htqweb.tenancy.context import schema_for


def tenant_tables() -> dict[str, list[str]]:
    """app_label -> имена таблиц конкретных моделей тенантной аппки.

    ``include_auto_created=True`` — m2m-таблицы такие же носители данных, и
    забыть их значило бы не заметить их пропажу.
    """
    out: dict[str, list[str]] = {}
    for label in settings.TENANT_APPS:
        config = django_apps.get_app_config(label)
        out[label] = sorted(
            model._meta.db_table
            for model in config.get_models(include_auto_created=True)
            if not model._meta.proxy
        )
    return out


def snapshot(*, exact: bool = False) -> dict:
    tables = tenant_tables()
    label_of = {name: label for label, names in tables.items() for name in names}
    names = sorted(label_of)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' AND table_name = ANY(%s) "
            "ORDER BY table_schema, table_name",
            [names],
        )
        placed = cur.fetchall()
        cur.execute(
            "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables "
            "WHERE relname = ANY(%s)",
            [names],
        )
        estimates = {(s, r): int(n) for s, r, n in cur.fetchall()}
        rows: dict[tuple[str, str], int] = {}
        for schema, table in placed:
            if exact:
                cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                    sql.Identifier(schema), sql.Identifier(table)))
                rows[(schema, table)] = cur.fetchone()[0]
            else:
                rows[(schema, table)] = estimates.get((schema, table), 0)
        cur.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'holding' ORDER BY table_name"
        )
        holding = [row[0] for row in cur.fetchall()]

    schemas: dict[str, dict] = {}
    for (schema, table), count in rows.items():
        entry = schemas.setdefault(schema, {"apps": {}, "tables": {}})
        entry["tables"][table] = count
        app = entry["apps"].setdefault(label_of[table], {"tables": 0, "rows": 0})
        app["tables"] += 1
        app["rows"] += count

    companies = [
        {
            "slug": c.slug, "name": c.name, "kind": c.kind, "status": c.status,
            "schema": schema_for(c.slug),
            "schema_exists": schema_service.schema_exists(c.slug),
        }
        for c in Company.objects.order_by("slug")
    ]
    return {"exact": exact, "companies": companies, "schemas": schemas,
            "holding_views": holding}


def render(data: dict) -> str:
    lines = [f"Реестр: {len(data['companies'])} компани(й)"]
    for c in data["companies"]:
        mark = "есть" if c["schema_exists"] else "НЕТ СХЕМЫ"
        lines.append(
            f"  {c['slug']:<24} {c['name']!r:<34} kind={c['kind']:<13} "
            f"status={c['status']:<9} {c['schema']} ({mark})"
        )
    mode = "точно" if data["exact"] else "оценка планировщика"
    lines.append(f"Таблицы тенантных аппок по схемам (строк — {mode}):")
    labels = list(settings.TENANT_APPS)
    lines.append("  " + f"{'схема':<24}" + "".join(f"{label:>12}" for label in labels)
                 + f"{'строк':>12}")
    for schema, entry in sorted(data["schemas"].items()):
        cells = "".join(
            f"{entry['apps'].get(label, {}).get('tables', 0):>12}" for label in labels
        )
        lines.append(f"  {schema:<24}{cells}{sum(entry['tables'].values()):>12}")
    lines.append(f"Сводки holding: {len(data['holding_views'])} представлени(й)")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Слепок раскладки тенантных таблиц по схемам (только чтение)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="JSON для сравнения слепков до/после выкатки.")
        parser.add_argument("--exact", action="store_true",
                            help="Точный count(*) вместо оценки планировщика.")

    def handle(self, *args, **opts):
        data = snapshot(exact=opts["exact"])
        if opts["as_json"]:
            self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
            return
        self.stdout.write(render(data))
        orphans = [c["slug"] for c in data["companies"]
                   if c["status"] == "active" and not c["schema_exists"]]
        if orphans:
            self.stderr.write(self.style.ERROR(
                "Действующие компании без физической схемы: " + ", ".join(orphans)
                + " — см. CLAUDE.md, «Осиротевшая строка реестра»."
            ))
```

- [ ] **Step 4: Убедиться, что тест проходит**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_tenancy_status.py -q`
Expected: 3 passed.

- [ ] **Step 5: Добавить команду в CLAUDE.md**

В блок «Django management» после строки `mail_check` добавить:

```bash
./.venv/Scripts/python.exe manage.py tenancy_status [--json] [--exact]   # слепок раскладки тенантных таблиц по схемам (только чтение); снимать до и после каждой боевой выкатки
```

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/companies/management/commands/tenancy_status.py backend/apps/companies/tests/test_tenancy_status.py CLAUDE.md
git commit -m "feat(companies): tenancy_status — слепок раскладки тенантных таблиц

Только чтение. Снимается до и после каждой боевой выкатки на время
доводки структуры группы: доказывает, что таблицы contracts/signoff на
месте и строки не пропали (roadmap §3, п.5).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `CompanyKind` под утверждённую структуру + `parent_slug`

**Files:**
- Modify: `backend/apps/companies/models.py:31-34` (`CompanyKind`), класс `Company` (свойство `parent_slug`)
- Create: `backend/apps/companies/migrations/0003_alter_company_kind.py` (makemigrations)
- Test: `backend/apps/companies/tests/test_models.py` (дописать)
- Modify: `docs/multi-company-tenancy-design.md` §1 (строки 12–25), §5 (описание `kind`)

**Interfaces:**
- Produces: `CompanyKind.CONSTRUCTION = "construction"`, `CompanyKind.IT = "it"`; `Company.parent_slug: str | None` (свойство).

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `backend/apps/companies/tests/test_models.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from apps.companies.models import Company, CompanyKind


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["holding", "construction", "it", "service", "regional"])
def test_kinds_of_the_approved_group_structure_validate(kind):
    """Утверждённая структура: холдинг, строительная ДО, IT, сервисная.

    ``regional`` — значение первой редакции дизайна (UZ/KG-регионы); остаётся
    принимаемым, пока единственная боевая компания не получит kind через
    PATCH (roadmap §3, п.6) — contract-шаг после этого.
    """
    Company(slug=f"k-{kind}", name=kind, kind=kind).full_clean()


@pytest.mark.django_db
def test_unknown_kind_is_rejected():
    with pytest.raises(ValidationError):
        Company(slug="k-bad", name="x", kind="branch").full_clean()


@pytest.mark.django_db
def test_parent_slug_property_follows_parent():
    holding = Company.objects.create(slug="grp", name="Group", kind=CompanyKind.HOLDING)
    child = Company.objects.create(slug="kid", name="Kid", kind=CompanyKind.IT, parent=holding)
    assert holding.parent_slug is None
    assert child.parent_slug == "grp"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_models.py -q -k "approved_group or unknown_kind or parent_slug"`
Expected: FAIL — `construction`/`it` не проходят `full_clean`; `AttributeError: parent_slug`.

- [ ] **Step 3: Изменить модель**

В `backend/apps/companies/models.py` заменить `CompanyKind`:

```python
class CompanyKind(models.TextChoices):
    """Вид компании по утверждённой оргструктуре группы (10.09.2026).

    Холдинг владеет долями, ДО — строительная (Hi-Tech Qazaqstan), IT
    (Hi-Tech Systems) и сервисная (Kazakhstan Engineering Group).
    """

    HOLDING = "holding", "Холдинг"
    CONSTRUCTION = "construction", "Строительная"
    IT = "it", "IT-компания"
    SERVICE = "service", "Сервисная"
    # Значение первой редакции дизайна (региональные компании UZ/KG, которых в
    # утверждённой структуре нет). Принимается, пока строка с ним есть в бою:
    # единственная компания получает kind правкой через API блока A, после
    # чего значение снимается отдельным contract-шагом. Убрать его сейчас —
    # значит уронить валидацию существующей строки реестра.
    REGIONAL = "regional", "Региональная (устар.)"
```

В класс `Company` после `__str__` добавить:

```python
    @property
    def parent_slug(self) -> str | None:
        """Slug вышестоящей компании — для схем ответа (``from_attributes``)."""
        return self.parent.slug if self.parent_id else None
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `./.venv/Scripts/python.exe manage.py makemigrations companies -n alter_company_kind`
Expected: файл `0003_alter_company_kind.py` с одной операцией `AlterField` (только `choices` — SQL не порождает).

- [ ] **Step 5: Убедиться, что тесты проходят и ничего не сломано**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies -q`
Expected: все зелёные (в т.ч. `test_company_grant.py`, где фикстура создаёт `kind=REGIONAL`).

- [ ] **Step 6: Обновить дизайн-документ**

В `docs/multi-company-tenancy-design.md` заменить строки 12–25 («Структура трёхуровневая…») на:

```markdown
Структура (утверждена 10.09.2026, комментарии К. Садыева):

1. **Холдинг** — ТОО «Hi-Tech Group LTD»: владение долями и стратегический
   контроль. Над ГД группы — Общее собрание участников. Три дирекции: по
   финансам и экономике, проектно-техническая, по операционной деятельности.
2. **Дочерние общества**, все напрямую под холдингом:
   ТОО «HI-TECH QAZAQSTAN» (строительная, `kind=construction`),
   ТОО «HI-TECH SYSTEMS» (IT, `kind=it`),
   ТОО «KAZAKHSTAN ENGINEERING GROUP» (сервисная, `kind=service`).

Первая редакция этого документа описывала региональные компании UZ/KG и
сервисный блок КУП/СЭС/СТЗЭР — в утверждённой структуре их нет. Модель
данных (дерево владения + отдельный граф услуг ``CompanyServiceLink``)
осталась: она не зависит от состава.

Доводка под утверждённую структуру и режим перехода с одной компанией —
[plans/2026-09-14-group-structure-roadmap.md](plans/2026-09-14-group-structure-roadmap.md).
```

В §5 строку `- \`name\`, \`kind\` (\`holding\` / \`regional\` / \`service\`), \`country\`.` заменить на
`- \`name\`, \`kind\` (\`holding\` / \`construction\` / \`it\` / \`service\`; \`regional\` — устаревшее, см. модель), \`country\`.`

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/companies/models.py backend/apps/companies/migrations/0003_alter_company_kind.py backend/apps/companies/tests/test_models.py docs/multi-company-tenancy-design.md
git commit -m "feat(companies): виды компаний по утверждённой структуре группы

construction и it добавлены, regional оставлен принимаемым до contract-шага:
единственная боевая компания получит kind правкой через API, а не миграцией.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `lifecycle.py` — одна оркестрация для CLI и HTTP

**Files:**
- Create: `backend/apps/companies/services/lifecycle.py`
- Modify: `backend/apps/companies/management/commands/company_create.py`, `company_archive.py`, `company_restore.py`
- Test: `backend/apps/companies/tests/test_lifecycle.py`; существующие `test_company_create.py`, `test_company_archive.py` остаются зелёными

**Interfaces:**
- Produces:
  - `class LifecycleError(Exception)` с `.detail: str`, `.status: int`, `.code: str`; наследники `CompanyExists(409)`, `CompanyNotFound(404)`, `CompanyInvalid(422)`, `ParentNotFound(422)`, `ParentCycle(422)`, `LastActiveCompany(409, code="last_active")`, `HoldingViewsStale(409)`;
  - `provision_company(*, slug, name, kind, parent_slug=None, country="") -> Company`;
  - `update_company(slug, *, name=None, kind=None, country=None, parent_slug=UNSET) -> Company`;
  - `archive_company(slug) -> tuple[Company, bool]`, `restore_company(slug) -> tuple[Company, bool]` (bool — изменилось ли);
  - `get_company_or_raise(slug) -> Company`.

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/companies/tests/test_lifecycle.py
"""Жизненный цикл компании — сервис, общий для CLI и HTTP.

Проверяются только правила, которых не было в командах: гейт последней
действующей компании (roadmap §3, п.4), правка с проверкой цикла в дереве
владения, отказы без побочных эффектов. Заведение со схемой и откаты
по-прежнему покрывает test_company_create.py — команда стала обёрткой.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import lifecycle, schema_service


@pytest.mark.django_db(transaction=True)
def test_archive_refuses_the_last_active_company(company_schema):
    with pytest.raises(lifecycle.LastActiveCompany) as exc:
        lifecycle.archive_company(company_schema["slug"])
    assert exc.value.status == 409
    assert exc.value.code == "last_active"
    assert Company.objects.get(slug=company_schema["slug"]).status == CompanyStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_cli_archive_refuses_the_last_active_company(company_schema):
    with pytest.raises(CommandError, match="единственная действующая"):
        call_command("company_archive", "--company", company_schema["slug"])


@pytest.mark.django_db
def test_archive_unknown_company_is_404():
    with pytest.raises(lifecycle.CompanyNotFound) as exc:
        lifecycle.archive_company("net-takoy")
    assert exc.value.status == 404


@pytest.mark.django_db
def test_update_changes_name_kind_country_and_parent():
    holding = Company.objects.create(slug="grp", name="Group", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.REGIONAL)

    updated = lifecycle.update_company(
        "htq", name="Hi-Tech Qazaqstan", kind="construction", country="KZ",
        parent_slug="grp",
    )
    assert updated.name == "Hi-Tech Qazaqstan"
    assert updated.kind == CompanyKind.CONSTRUCTION
    assert updated.country == "KZ"
    assert updated.parent_id == holding.id


@pytest.mark.django_db
def test_update_without_parent_key_keeps_parent_and_with_null_clears_it():
    holding = Company.objects.create(slug="grp", name="Group", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION, parent=holding)

    assert lifecycle.update_company("htq", name="HTQ-2").parent_id == holding.id
    assert lifecycle.update_company("htq", parent_slug=None).parent_id is None


@pytest.mark.django_db
def test_update_rejects_self_and_cycle_as_parent():
    a = Company.objects.create(slug="a", name="A", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="b", name="B", kind=CompanyKind.SERVICE, parent=a)

    with pytest.raises(lifecycle.ParentCycle):
        lifecycle.update_company("a", parent_slug="a")
    with pytest.raises(lifecycle.ParentCycle):
        lifecycle.update_company("a", parent_slug="b")
    assert Company.objects.get(slug="a").parent_id is None


@pytest.mark.django_db
def test_update_rejects_unknown_parent_and_kind():
    Company.objects.create(slug="a", name="A", kind=CompanyKind.HOLDING)
    with pytest.raises(lifecycle.ParentNotFound):
        lifecycle.update_company("a", parent_slug="nope")
    with pytest.raises(lifecycle.CompanyInvalid):
        lifecycle.update_company("a", kind="branch")


@pytest.mark.django_db(transaction=True)
def test_provision_rejects_duplicate_before_touching_the_schema(company_schema):
    with pytest.raises(lifecycle.CompanyExists):
        lifecycle.provision_company(slug=company_schema["slug"], name="Дубль", kind="service")
    # Схема фикстуры на месте, лишней не появилось.
    assert schema_service.schema_exists(company_schema["slug"])
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_lifecycle.py -q`
Expected: FAIL — `ImportError: cannot import name 'lifecycle'`.

- [ ] **Step 3: Написать сервис**

```python
# backend/apps/companies/services/lifecycle.py
"""Жизненный цикл компании: заведение, правка, архив, восстановление.

Единственное место оркестрации — им пользуются и management-команды
(``company_create`` / ``company_archive`` / ``company_restore``), и HTTP-вьюхи
``apps.companies.views``. Раньше оркестрация жила в самих командах; вторая
копия во вьюхах разошлась бы с первой на первой же правке порядка шагов,
а порядок здесь — не деталь (см. докстринг ``provision_company``).

Ошибки типизированы и несут ``status``/``code``: команда переводит их в
``CommandError``, вьюха — в конверт ``{"detail": ...}``. Сообщения на
русском, потому что уходят пользователю как есть.

Гейт ``LastActiveCompany`` — требование режима перехода
(docs/plans/2026-09-14-group-structure-roadmap.md, §3 п.4): архив = 404 на
весь трафик компании, и пока компания одна, это 404 на contracts/signoff
целиком. Гейт стоит здесь, а не во вьюхе, чтобы действовать и для CLI.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import ProgrammingError, transaction
from django.utils import timezone

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import holding_views, migration_service, schema_service
from apps.companies.services.migration_service import _cleanup

#: Маркер «аргумент не передан» для необязательных полей правки: ``None`` у
#: ``parent_slug`` — законное значение («без родителя»), и путать его с
#: «не трогать» нельзя.
UNSET = object()

_HOLDING_STALE = (
    "{what}, но сводки холдинга собрать нельзя: состав столбцов разошёлся с "
    "другой компанией, отставшей по миграциям. Представления оставлены "
    "снесёнными: читатель получит громкую ошибку вместо цифр по "
    "полумигрированной группе. Доведите остальные компании — "
    "`manage.py migrate_companies` без фильтров. Причина: {exc}"
)


class LifecycleError(Exception):
    status = 400
    code = "lifecycle"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class CompanyExists(LifecycleError):
    status = 409
    code = "exists"


class CompanyNotFound(LifecycleError):
    status = 404
    code = "not_found"


class CompanyInvalid(LifecycleError):
    status = 422
    code = "invalid"


class ParentNotFound(LifecycleError):
    status = 422
    code = "parent_not_found"


class ParentCycle(LifecycleError):
    status = 422
    code = "parent_cycle"


class LastActiveCompany(LifecycleError):
    status = 409
    code = "last_active"


class HoldingViewsStale(LifecycleError):
    status = 409
    code = "holding_stale"


def get_company_or_raise(slug: str) -> Company:
    company = Company.objects.select_related("parent").filter(slug=slug).first()
    if company is None:
        raise CompanyNotFound(f"Компания {slug} не найдена.")
    return company


def _resolve_parent(parent_slug: str | None) -> Company | None:
    if parent_slug is None:
        return None
    parent = Company.objects.filter(slug=parent_slug).first()
    if parent is None:
        raise ParentNotFound(f"Вышестоящая компания {parent_slug} не найдена.")
    return parent


def _assert_no_cycle(company: Company, parent: Company | None) -> None:
    """Дерево владения обязано оставаться деревом.

    ``PROTECT`` на self-FK защищает только от удаления; правка ``parent``
    может замкнуть цикл, и ``companies_below`` в apps.access тогда ходила бы
    по кругу (у неё есть своя защита, но она — последняя линия, не первая).
    """
    cursor = parent
    seen: set[int] = set()
    while cursor is not None and cursor.id not in seen:
        if cursor.id == company.id:
            raise ParentCycle(
                f"Компания {company.slug} не может подчиняться {parent.slug}: "
                "получился бы цикл в дереве владения."
            )
        seen.add(cursor.id)
        cursor = cursor.parent


def _full_clean(company: Company) -> None:
    try:
        # full_clean(), а не save(): objects.create() валидаторы (в том числе
        # SLUG_VALIDATOR и choices у kind) не вызывает вовсе.
        company.full_clean()
    except ValidationError as exc:
        raise CompanyInvalid("; ".join(
            f"{field}: {' '.join(msgs)}" for field, msgs in exc.message_dict.items()
        )) from exc


def _rebuild_or_raise(what: str) -> None:
    try:
        holding_views.rebuild_holding_views()
    except ProgrammingError as exc:
        raise HoldingViewsStale(_HOLDING_STALE.format(what=what, exc=exc)) from exc


def provision_company(*, slug: str, name: str, kind: str,
                      parent_slug: str | None = None, country: str = "") -> Company:
    """Строка реестра + схема + миграции + сводки холдинга.

    Порядок шагов — единственный безопасный (подробно — докстринг
    ``management/commands/company_create.py``): валидация до разрушающих
    действий; строка и ``CREATE SCHEMA`` одной транзакцией; ``drop_holding_views``
    и ``migrate_company`` вне транзакции; ``rebuild_holding_views`` в конце.
    Откат — три НЕЗАВИСИМЫХ шага через ``_cleanup``.

    ⚠️ Долгая операция (миграции четырёх аппок, ~минута): из HTTP-запроса
    под ``gunicorn --timeout 60`` не вызывать — воркер будет убит посреди
    DDL. Поэтому в блоке A заведение остаётся за CLI.
    """
    if Company.objects.filter(slug=slug).exists():
        raise CompanyExists(f"Компания {slug} уже существует.")
    parent = _resolve_parent(parent_slug)
    company = Company(slug=slug, name=name, kind=kind, parent=parent, country=country)
    _full_clean(company)

    with transaction.atomic():
        company.save()
        schema_service.create_schema(slug)

    try:
        holding_views.drop_holding_views()
        migration_service.migrate_company(slug)
    except Exception:
        _cleanup("снос схемы после отката",
                 lambda: schema_service.drop_schema(slug))
        _cleanup("удаление строки реестра после отката", company.delete)
        _cleanup("пересборка сводок холдинга после отката",
                 holding_views.rebuild_holding_views)
        raise

    _rebuild_or_raise(f"Компания {slug} создана и мигрирована")
    return company


def update_company(slug: str, *, name: str | None = None, kind: str | None = None,
                   country: str | None = None, parent_slug=UNSET) -> Company:
    """Правка реестровых полей. Slug не правится никогда: он — имя схемы и поддомен."""
    company = get_company_or_raise(slug)
    if name is not None:
        company.name = name
    if kind is not None:
        if kind not in CompanyKind.values:
            raise CompanyInvalid(f"kind: {kind!r} не входит в {list(CompanyKind.values)}")
        company.kind = kind
    if country is not None:
        company.country = country
    if parent_slug is not UNSET:
        parent = _resolve_parent(parent_slug)
        _assert_no_cycle(company, parent)
        company.parent = parent
    _full_clean(company)
    company.save()
    return company


def archive_company(slug: str) -> tuple[Company, bool]:
    """Перевести в архив. Идемпотентно: архивная компания — ``(company, False)``."""
    company = get_company_or_raise(slug)
    if company.status == CompanyStatus.ARCHIVED:
        return company, False
    others = Company.objects.filter(status=CompanyStatus.ACTIVE).exclude(pk=company.pk)
    if not others.exists():
        raise LastActiveCompany(
            f"{slug} — единственная действующая компания: её архив закрыл бы "
            "404-м весь трафик платформы, включая contracts и signoff."
        )
    company.status = CompanyStatus.ARCHIVED
    company.archived_at = timezone.now()
    company.save(update_fields=["status", "archived_at", "updated_at"])
    _rebuild_or_raise(f"Компания {slug} переведена в архив")
    return company, True


def restore_company(slug: str) -> tuple[Company, bool]:
    """Вернуть из архива. Идемпотентно: действующая компания — ``(company, False)``."""
    company = get_company_or_raise(slug)
    if company.status == CompanyStatus.ACTIVE:
        return company, False
    company.status = CompanyStatus.ACTIVE
    company.archived_at = None
    company.save(update_fields=["status", "archived_at", "updated_at"])
    _rebuild_or_raise(f"Компания {slug} возвращена из архива")
    return company, True
```

- [ ] **Step 4: Переписать команды в обёртки**

`backend/apps/companies/management/commands/company_create.py` — модульный докстринг оставить (он объясняет порядок шагов, на который ссылается сервис), тело класса заменить:

```python
from django.core.management.base import BaseCommand, CommandError

from apps.companies.models import CompanyKind
from apps.companies.services import lifecycle


class Command(BaseCommand):
    help = "Завести компанию: строка реестра, схема Postgres, миграции, представления."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--kind", required=True, choices=[c.value for c in CompanyKind])
        parser.add_argument("--parent", help="slug вышестоящей компании")
        parser.add_argument("--country", default="")

    def handle(self, *args, **opts):
        try:
            company = lifecycle.provision_company(
                slug=opts["slug"], name=opts["name"], kind=opts["kind"],
                parent_slug=opts["parent"], country=opts["country"],
            )
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Компания {company.slug} создана, схема "
            f"co_{company.slug.replace('-', '_')} готова."
        ))
```

Импорты `ValidationError`, `ProgrammingError`, `transaction`, `Company`, `holding_views`, `migration_service`, `schema_service`, `_cleanup` из файла команды убрать — они переехали в сервис.

`company_archive.py` — докстринг оставить, тело:

```python
from django.core.management.base import BaseCommand, CommandError

from apps.companies.services import lifecycle


class Command(BaseCommand):
    help = "Перевести компанию в архив и пересобрать сводки холдинга."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, dest="company_slug",
                            help="slug компании из реестра.")

    def handle(self, *args, **opts):
        slug = opts["company_slug"]
        try:
            _company, changed = lifecycle.archive_company(slug)
        except lifecycle.LifecycleError as exc:
            raise CommandError(exc.detail) from exc
        if not changed:
            self.stdout.write(self.style.WARNING(
                f"Компания {slug} уже в архиве — повторный вызов ничего не меняет."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} переведена в архив. Сводки холдинга пересобраны."
        ))
```

`company_restore.py` — симметрично, с `lifecycle.restore_company`, сообщениями
«уже действует — повторный вызов ничего не меняет» и «возвращена из архива.
Сводки холдинга пересобраны.».

⚠️ В `test_company_create.py` `monkeypatch.setattr(migration_service, "migrate_company", …)`
патчит атрибут МОДУЛЯ — сервис зовёт `migration_service.migrate_company(...)`
через модуль, а не через импортированное имя, поэтому патч продолжает
действовать. Не переписывать на `from ... import migrate_company`.

- [ ] **Step 5: Прогнать тесты аппки**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies -q`
Expected: все зелёные, включая `test_company_create.py` (откаты) и `test_company_archive.py` (две компании — гейт не срабатывает).

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/companies/services/lifecycle.py backend/apps/companies/management/commands/company_create.py backend/apps/companies/management/commands/company_archive.py backend/apps/companies/management/commands/company_restore.py backend/apps/companies/tests/test_lifecycle.py
git commit -m "refactor(companies): жизненный цикл компании вынесен в сервис, гейт последней компании

Одна оркестрация для CLI и будущих HTTP-вьюх. Единственную действующую
компанию архивировать нельзя: на время перехода это 404 на contracts и
signoff целиком (roadmap §3, п.4). Правка компании проверяет цикл в дереве
владения.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `module_service.py` — модули компании

**Files:**
- Create: `backend/apps/companies/services/module_service.py`
- Test: `backend/apps/companies/tests/test_module_service.py`

**Interfaces:**
- Produces: `list_modules(company: Company) -> list[dict]` (`app_label, enabled, message, is_core`); `set_module(company, app_label, *, enabled: bool, message: str | None = None) -> dict`; ошибки `UnknownModule` (`.detail`), `CoreModuleLocked` (`.detail`).

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/companies/tests/test_module_service.py
"""Рубильник модулей одной компании (второй слой над ServiceStatus)."""

import pytest
from django.core.cache import cache

from apps.companies import interface
from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.companies.services import module_service
from apps.core.models import KNOWN_SERVICES
from apps.core.services import CORE_MODULES


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.mark.django_db
def test_list_covers_every_known_service_and_defaults_to_enabled(company):
    rows = module_service.list_modules(company)
    assert [r["app_label"] for r in rows] == list(KNOWN_SERVICES)
    assert all(r["enabled"] for r in rows)
    assert {r["app_label"] for r in rows if r["is_core"]} == set(CORE_MODULES) & set(KNOWN_SERVICES)


@pytest.mark.django_db
def test_disable_writes_row_and_interface_sees_it(company):
    row = module_service.set_module(company, "tasks", enabled=False, message="Пока закрыто")
    assert row == {"app_label": "tasks", "enabled": False, "message": "Пока закрыто", "is_core": False}
    cache.clear()  # interface кэширует ответ на 5 секунд
    assert interface.module_enabled("htq", "tasks") == (False, "Пока закрыто")


@pytest.mark.django_db
def test_enable_removes_the_row_because_absence_means_enabled(company):
    module_service.set_module(company, "tasks", enabled=False)
    module_service.set_module(company, "tasks", enabled=True)
    assert not CompanyModule.objects.filter(company=company, app_label="tasks").exists()
    cache.clear()
    assert interface.module_enabled("htq", "tasks")[0] is True


@pytest.mark.django_db
def test_core_module_cannot_be_disabled(company):
    with pytest.raises(module_service.CoreModuleLocked):
        module_service.set_module(company, "hr", enabled=False)
    assert not CompanyModule.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_unknown_module_is_rejected(company):
    with pytest.raises(module_service.UnknownModule):
        module_service.set_module(company, "warehouse", enabled=False)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_module_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'module_service'`.

- [ ] **Step 3: Написать сервис**

```python
# backend/apps/companies/services/module_service.py
"""Модули одной компании — второй, компанейский слой рубильника.

Список модулей — ``KNOWN_SERVICES`` из ``apps.core`` (общий фундамент, его
импортировать можно): второго справочника платформа не заводит, иначе два
списка разъедутся. ``CORE_MODULES`` на уровне компании не выключаются — это
обязательное ядро, которое есть у каждой компании (CLAUDE.md,
«Два независимых рубильника»).

Отсутствие строки ``CompanyModule`` означает «включено» (докстринг модели),
поэтому включение — удаление строки, а не запись ``enabled=True``: иначе
таблица обрастала бы строками, ничего не значащими.
"""

from __future__ import annotations

from apps.companies.models import Company, CompanyModule
from apps.core.models import KNOWN_SERVICES
from apps.core.services import CORE_MODULES


class UnknownModule(Exception):
    def __init__(self, app_label: str) -> None:
        self.detail = f"Модуля {app_label} нет в реестре сервисов платформы."
        super().__init__(self.detail)


class CoreModuleLocked(Exception):
    def __init__(self, app_label: str) -> None:
        self.detail = (f"Модуль {app_label} — ядро платформы и на уровне "
                       "компании не выключается.")
        super().__init__(self.detail)


def _row(app_label: str, stored: CompanyModule | None) -> dict:
    return {
        "app_label": app_label,
        "enabled": True if stored is None else stored.enabled,
        "message": "" if stored is None else stored.message,
        "is_core": app_label in CORE_MODULES,
    }


def list_modules(company: Company) -> list[dict]:
    stored = {m.app_label: m for m in company.modules.all()}
    return [_row(name, stored.get(name)) for name in KNOWN_SERVICES]


def set_module(company: Company, app_label: str, *, enabled: bool,
               message: str | None = None) -> dict:
    if app_label not in KNOWN_SERVICES:
        raise UnknownModule(app_label)
    if app_label in CORE_MODULES:
        raise CoreModuleLocked(app_label)
    if enabled:
        CompanyModule.objects.filter(company=company, app_label=app_label).delete()
        return _row(app_label, None)
    defaults = {"enabled": False}
    if message:
        defaults["message"] = message
    stored, _ = CompanyModule.objects.update_or_create(
        company=company, app_label=app_label, defaults=defaults,
    )
    return _row(app_label, stored)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_module_service.py apps/core/tests/test_app_isolation.py -q`
Expected: passed (импорт `apps.core.*` разрешён сторожем изоляции).

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/companies/services/module_service.py backend/apps/companies/tests/test_module_service.py
git commit -m "feat(companies): сервис модулей компании

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: членство — список и отзыв

**Files:**
- Modify: `backend/apps/companies/services/membership_service.py`
- Test: `backend/apps/companies/tests/test_membership_service.py`

**Interfaces:**
- Consumes: `apps.users.interface.get_users_brief(ids) -> list[{id, username, email, full_name, is_active}]`.
- Produces: `list_memberships(company) -> list[dict]` (`user_id, username, full_name, email, is_active, is_default`); `revoke_membership(company, user_id) -> bool`; `grant_membership` — как было.

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/companies/tests/test_membership_service.py
"""Членство: список с данными учётки и отзыв."""

import pytest

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.companies.services import membership_service
from apps.users.models import User, UserStatus


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.fixture
def user(db):
    return User.objects.create(username="ivanov", email="ivanov@example.test",
                               password="x", first_name="Иван", last_name="Иванов",
                               status=UserStatus.ACTIVE)


@pytest.mark.django_db
def test_list_joins_user_brief(company, user):
    membership_service.grant_membership(company, user.id, is_default=True)
    rows = membership_service.list_memberships(company)
    assert rows == [{
        "user_id": user.id, "username": "ivanov", "full_name": "Иванов Иван",
        "email": "ivanov@example.test", "is_active": True, "is_default": True,
    }]


@pytest.mark.django_db
def test_list_keeps_membership_of_a_deleted_account(company):
    """Учётки нет, строка есть: показать, а не спрятать — иначе её не отозвать."""
    CompanyMembership.objects.create(company=company, user_id=999_999)
    rows = membership_service.list_memberships(company)
    assert rows[0]["user_id"] == 999_999
    assert rows[0]["username"] == ""
    assert rows[0]["is_active"] is False


@pytest.mark.django_db
def test_revoke_is_idempotent(company, user):
    membership_service.grant_membership(company, user.id)
    assert membership_service.revoke_membership(company, user.id) is True
    assert membership_service.revoke_membership(company, user.id) is False
    assert not CompanyMembership.objects.filter(company=company).exists()
```

⚠️ `full_name` — строится `apps.users.interface.full_name_for`; если в проекте
порядок «Имя Фамилия», поправить ожидание в первом тесте по фактическому
выводу `get_users_brief` (проверить одним `print` при первом прогоне).

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_membership_service.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'list_memberships'`.

- [ ] **Step 3: Дописать сервис**

В `membership_service.py` расширить импорт из `apps.users.interface`, добавив
`get_users_brief`, и дописать в конец файла:

```python
def list_memberships(company: Company) -> list[dict]:
    """Участники компании с данными учётки.

    Учётка может быть удалена, а строка членства — остаться: такую строку
    показываем с пустыми полями учётки, а не прячем — спрятанную нельзя
    отозвать.
    """
    rows = list(
        CompanyMembership.objects.filter(company=company)
        .order_by("-is_default", "user_id")
        .values("user_id", "is_default")
    )
    briefs = {b["id"]: b for b in get_users_brief([r["user_id"] for r in rows])}
    out = []
    for row in rows:
        brief = briefs.get(row["user_id"], {})
        out.append({
            "user_id": row["user_id"],
            "username": brief.get("username", ""),
            "full_name": brief.get("full_name", ""),
            "email": brief.get("email", ""),
            "is_active": bool(brief.get("is_active", False)),
            "is_default": row["is_default"],
        })
    return out


def revoke_membership(company: Company, user_id: int) -> bool:
    """Снять членство. ``True`` — строка была и удалена, ``False`` — её не было."""
    deleted, _ = CompanyMembership.objects.filter(
        company=company, user_id=user_id,
    ).delete()
    return deleted > 0
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_membership_service.py apps/companies/tests/test_company_grant.py -q`
Expected: passed.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/companies/services/membership_service.py backend/apps/companies/tests/test_membership_service.py
git commit -m "feat(companies): список участников с данными учётки и отзыв членства

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: схемы, чтение реестра, `me`, `urls.py`

**Files:**
- Create: `backend/apps/companies/schemas.py`, `backend/apps/companies/views.py`, `backend/apps/companies/urls.py`
- Create: `backend/apps/companies/tests/api_helpers.py`
- Test: `backend/apps/companies/tests/test_api_read.py`

**Interfaces:**
- Consumes: `lifecycle.get_company_or_raise`, `Company.parent_slug` (Task 2).
- Produces: `schemas.CompanyRead/CompanyTreeNode/MyCompany/CompanyPatch/ModuleRead/ModulePatch/MembershipRead/MembershipCreate`; вьюхи `MyCompaniesView`, `CompanyCollectionView`, `CompanyTreeView`, `CompanyItemView`; базовый класс `CompaniesView` с `deny_unless_platform_admin()` и `lifecycle_error(exc)`.

- [ ] **Step 1: Написать помощники тестов**

```python
# backend/apps/companies/tests/api_helpers.py
"""Токены и запросы для API-тестов реестра — тот же стиль, что в
apps/access/tests/helpers.py (копия, а не импорт: тесты соседней аппки —
не публичный контракт)."""

from __future__ import annotations

import json

import jwt as pyjwt
from django.conf import settings
from django.test import Client

BASE = "/api/companies/v1"


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def staff_token(**over) -> str:
    return token(user_id=8, sub="8", is_staff=True, is_admin=True, **over)


def superuser_token(**over) -> str:
    return token(user_id=9, sub="9", is_staff=True, is_superuser=True,
                 is_admin=True, **over)


def auth(tok: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}


def headers(slug: str, tok: str) -> dict:
    """Как ставит шлюз: слаг компании + токен, выпущенный на неё."""
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


def post_json(client: Client, path: str, body, **extra):
    return client.post(path, data=json.dumps(body, default=str),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body, **extra):
    return client.patch(path, data=json.dumps(body, default=str),
                        content_type="application/json", **extra)
```

- [ ] **Step 2: Написать падающие тесты**

```python
# backend/apps/companies/tests/test_api_read.py
"""Чтение реестра: /me, список, дерево, карточка. Коды и формы тел."""

import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership, CompanyStatus
from apps.companies.tests.api_helpers import (
    BASE, auth, headers, staff_token, superuser_token, token,
)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def group(db):
    holding = Company.objects.create(slug="hi-tech-group", name="Hi-Tech Group", kind=CompanyKind.HOLDING)
    htq = Company.objects.create(slug="hi-tech-qazaqstan", name="Hi-Tech Qazaqstan",
                                 kind=CompanyKind.CONSTRUCTION, country="KZ", parent=holding)
    keg = Company.objects.create(slug="keg", name="KEG", kind=CompanyKind.SERVICE, parent=holding,
                                 status=CompanyStatus.ARCHIVED)
    return {"holding": holding, "htq": htq, "keg": keg}


# ── /me ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_me_requires_auth(client):
    assert client.get(f"{BASE}/me").status_code == 401


@pytest.mark.django_db
def test_me_lists_active_memberships_and_marks_current(client, group):
    CompanyMembership.objects.create(company=group["htq"], user_id=7, is_default=True)
    CompanyMembership.objects.create(company=group["holding"], user_id=7)
    CompanyMembership.objects.create(company=group["keg"], user_id=7)  # архив — не показывать

    res = client.get(f"{BASE}/me", **headers("hi-tech-qazaqstan", token(company="hi-tech-qazaqstan")))
    assert res.status_code == 200
    assert res.json() == [
        {"slug": "hi-tech-qazaqstan", "name": "Hi-Tech Qazaqstan", "kind": "construction",
         "is_default": True, "is_current": True},
        {"slug": "hi-tech-group", "name": "Hi-Tech Group", "kind": "holding",
         "is_default": False, "is_current": False},
    ]


@pytest.mark.django_db
def test_me_without_company_header_marks_nothing_current(client, group):
    CompanyMembership.objects.create(company=group["htq"], user_id=7)
    res = client.get(f"{BASE}/me", **auth(token()))
    assert res.status_code == 200
    assert res.json()[0]["is_current"] is False


# ── Реестр ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_registry_is_closed_to_users_without_the_module(client, group):
    """Без контекста компании уровень у обычного пользователя — none: 403."""
    assert client.get(f"{BASE}/companies", **auth(token())).status_code == 403
    assert client.get(f"{BASE}/companies", **auth(staff_token())).status_code == 403


@pytest.mark.django_db
def test_superuser_lists_all_by_default_and_filters_by_status(client, group):
    res = client.get(f"{BASE}/companies", **auth(superuser_token()))
    assert res.status_code == 200
    assert [c["slug"] for c in res.json()] == ["hi-tech-group", "hi-tech-qazaqstan", "keg"]
    htq = next(c for c in res.json() if c["slug"] == "hi-tech-qazaqstan")
    assert htq == {"id": group["htq"].id, "slug": "hi-tech-qazaqstan", "name": "Hi-Tech Qazaqstan",
                   "kind": "construction", "status": "active", "country": "KZ",
                   "parent_slug": "hi-tech-group", "archived_at": None}

    res = client.get(f"{BASE}/companies?status=archived", **auth(superuser_token()))
    assert [c["slug"] for c in res.json()] == ["keg"]
    assert client.get(f"{BASE}/companies?status=bogus", **auth(superuser_token())).status_code == 422


@pytest.mark.django_db
def test_tree_nests_active_children_under_roots(client, group):
    res = client.get(f"{BASE}/companies/tree", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json() == [{
        "slug": "hi-tech-group", "name": "Hi-Tech Group", "kind": "holding",
        "status": "active", "country": "",
        "children": [{
            "slug": "hi-tech-qazaqstan", "name": "Hi-Tech Qazaqstan", "kind": "construction",
            "status": "active", "country": "KZ", "children": [],
        }],
    }]


@pytest.mark.django_db
def test_item_and_404(client, group):
    res = client.get(f"{BASE}/companies/keg", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["status"] == "archived"
    assert res.json()["archived_at"] is None  # архивирована фикстурой напрямую, без lifecycle
    assert client.get(f"{BASE}/companies/nope", **auth(superuser_token())).status_code == 404
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_read.py -q`
Expected: FAIL — 404 на все пути (аппка без `urls.py` не монтируется).

- [ ] **Step 4: Написать схемы**

```python
# backend/apps/companies/schemas.py
"""Контракт ``/api/companies/v1`` — план блока A, раздел «Контракт API».

Изменение формы — только вслед за правкой плана: фронт (``src/types/companies.ts``)
собран по этой же таблице.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.companies.models import CompanyKind


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    kind: str
    status: str
    country: str
    parent_slug: str | None
    archived_at: datetime | None


class CompanyTreeNode(BaseModel):
    slug: str
    name: str
    kind: str
    status: str
    country: str
    children: list[CompanyTreeNode] = Field(default_factory=list)


class MyCompany(BaseModel):
    slug: str
    name: str
    kind: str
    is_default: bool
    is_current: bool


class CompanyPatch(BaseModel):
    """Правка реестровых полей. Slug не правится: он — имя схемы и поддомен.

    ``parent_slug=None`` в теле — «без родителя»; отсутствие ключа — «не
    трогать». Разница читается через ``model_fields_set`` во вьюхе.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = None
    country: str | None = Field(default=None, max_length=2)
    parent_slug: str | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in CompanyKind.values:
            raise ValueError(f"kind должен быть одним из {list(CompanyKind.values)}")
        return value


class ModuleRead(BaseModel):
    app_label: str
    enabled: bool
    message: str
    is_core: bool


class ModulePatch(BaseModel):
    enabled: bool
    message: str | None = Field(default=None, max_length=200)


class MembershipRead(BaseModel):
    user_id: int
    username: str
    full_name: str
    email: str
    is_active: bool
    is_default: bool


class MembershipCreate(BaseModel):
    user_id: int = Field(gt=0)
    is_default: bool = False
```

- [ ] **Step 5: Написать вьюхи чтения и `urls.py`**

```python
# backend/apps/companies/views.py
"""HTTP-слой ``/api/companies/v1/*`` — план блока A, «Контракт API».

Стиль тот же, что в ``apps.access``: ``htqweb.http.ApiView``, ``api_view``
пометодно через ``method_decorator``.

**Гейты.** Чтение и правка реестра — ``api_view(module="companies", ...)``:
функции ``companies.registry/modules/memberships`` объявлены в
``access_functions.py`` аппки. Архив, восстановление и отзыв членства —
операции платформенного уровня (архив = 404 на весь трафик компании; отзыв
членства запирает человека снаружи), поэтому ``admin=True`` плюс явная
проверка ``is_superuser``, как у каталога ролей в ``apps.access``.

**Заведения компании здесь нет** — намеренно: ``provision_company`` гонит
миграции четырёх аппок около минуты, ``gunicorn --timeout 60`` убьёт воркер
посреди DDL. Заведение — ``manage.py company_create``.
"""

from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator

from apps.users.interface import get_user_brief
from htqweb.http import ApiView, api_view, json_error

from . import schemas
from .models import Company, CompanyMembership, CompanyStatus
from .services import lifecycle, membership_service, module_service

read = method_decorator(api_view(methods=("GET",), auth="jwt",
                                 module="companies", level="read"))


def write(method: str, body=None, status: int = 200):
    return method_decorator(api_view(methods=(method,), auth="jwt", body=body,
                                     status=status, module="companies", level="write"))


def platform(method: str, body=None, status: int = 200):
    """Платформенная операция: admin-гейт api_view + is_superuser внутри метода."""
    return method_decorator(api_view(methods=(method,), auth="jwt", body=body,
                                     status=status, admin=True))


class CompaniesView(ApiView):
    def deny_unless_platform_admin(self):
        if not self.request.token.is_superuser:
            return json_error(
                "Операция платформенного уровня: доступна только "
                "платформенному администратору", 403,
            )
        return None

    @staticmethod
    def lifecycle_error(exc: lifecycle.LifecycleError):
        return JsonResponse({"detail": exc.detail, "code": exc.code}, status=exc.status)

    @staticmethod
    def company_or_404(slug: str) -> Company:
        return lifecycle.get_company_or_raise(slug)


# ── Мои компании ─────────────────────────────────────────────────────────

class MyCompaniesView(ApiView):
    """``GET me`` — компании, где у пользователя есть членство. Без гейта модуля:
    это то, что нужно КАЖДОМУ вошедшему, чтобы переключиться."""

    @method_decorator(api_view(methods=("GET",), auth="jwt"))
    def get(self, request):
        current = request.company["slug"] if getattr(request, "company", None) else None
        rows = (
            CompanyMembership.objects
            .filter(user_id=request.token.user_id, company__status=CompanyStatus.ACTIVE)
            .select_related("company")
            .order_by("-is_default", "company__name")
        )
        return [
            schemas.MyCompany(
                slug=m.company.slug, name=m.company.name, kind=m.company.kind,
                is_default=m.is_default, is_current=(m.company.slug == current),
            )
            for m in rows
        ]


# ── Реестр ───────────────────────────────────────────────────────────────

_STATUS_FILTERS = {"all": None, "active": CompanyStatus.ACTIVE,
                   "archived": CompanyStatus.ARCHIVED}


class CompanyCollectionView(CompaniesView):
    @read
    def get(self, request):
        wanted = request.GET.get("status", "all")
        if wanted not in _STATUS_FILTERS:
            return json_error("status: ожидается all, active или archived", 422)
        qs = Company.objects.select_related("parent").order_by("name")
        if _STATUS_FILTERS[wanted] is not None:
            qs = qs.filter(status=_STATUS_FILTERS[wanted])
        return [schemas.CompanyRead.model_validate(c) for c in qs]


def _tree(companies: list[Company]) -> list[schemas.CompanyTreeNode]:
    by_parent: dict[int | None, list[Company]] = {}
    for company in companies:
        by_parent.setdefault(company.parent_id, []).append(company)

    def node(company: Company) -> schemas.CompanyTreeNode:
        return schemas.CompanyTreeNode(
            slug=company.slug, name=company.name, kind=company.kind,
            status=company.status, country=company.country,
            children=[node(c) for c in by_parent.get(company.id, [])],
        )

    # Корень — компания без родителя либо с родителем вне выборки (архивным):
    # ветка не должна пропадать из дерева из-за архива над ней.
    ids = {c.id for c in companies}
    return [node(c) for c in companies if c.parent_id is None or c.parent_id not in ids]


class CompanyTreeView(CompaniesView):
    @read
    def get(self, request):
        companies = list(Company.objects.filter(status=CompanyStatus.ACTIVE).order_by("name"))
        return _tree(companies)


class CompanyItemView(CompaniesView):
    @read
    def get(self, request, slug: str):
        return schemas.CompanyRead.model_validate(self.company_or_404(slug))
```

⚠️ `lifecycle.get_company_or_raise` бросает `CompanyNotFound` — это не
`Http404`, и `api_view` превратил бы его в 500. Переопределять `dispatch` в
`CompaniesView` бесполезно: `api_view` оборачивает сам МЕТОД и ловит только
`Http404`/`PermissionDenied`/`SuspiciousOperation`/`ServiceDisabled`, а всё
остальное превращает в 500 раньше, чем управление вернётся в `dispatch`.
Поэтому каждый метод, который зовёт `lifecycle`, ловит ошибку сам —
`CompanyItemView.get` выше написан именно так, и тот же `try/except`
повторяется в задачах 7–8. Повтор честный: он виден в каждом месте, где
ошибка сервиса становится HTTP-кодом.

`lifecycle_error` использует `JsonResponse` — добавить его в импорт из
`django.http` в шапке файла (`from django.http import HttpResponse, JsonResponse`)
и убрать локальный импорт из тела метода.

```python
# backend/apps/companies/urls.py
"""Маршруты ``/api/companies/v1/*``. Монтируются автодискавери по
``CompaniesConfig.API_PREFIX``; ``APPEND_SLASH = False`` — оба написания.

``companies/tree`` стоит ВЫШЕ ``companies/<slug>``: ``<slug:slug>`` матчит и
слово ``tree``.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("me", views.MyCompaniesView.as_view()),
    path("me/", views.MyCompaniesView.as_view()),

    path("companies/tree", views.CompanyTreeView.as_view()),
    path("companies/tree/", views.CompanyTreeView.as_view()),
    path("companies/<slug:slug>/archive", views.CompanyArchiveView.as_view()),
    path("companies/<slug:slug>/archive/", views.CompanyArchiveView.as_view()),
    path("companies/<slug:slug>/restore", views.CompanyRestoreView.as_view()),
    path("companies/<slug:slug>/restore/", views.CompanyRestoreView.as_view()),
    path("companies/<slug:slug>/modules/<str:app_label>", views.CompanyModuleItemView.as_view()),
    path("companies/<slug:slug>/modules/<str:app_label>/", views.CompanyModuleItemView.as_view()),
    path("companies/<slug:slug>/modules", views.CompanyModulesView.as_view()),
    path("companies/<slug:slug>/modules/", views.CompanyModulesView.as_view()),
    path("companies/<slug:slug>/memberships/<int:user_id>", views.CompanyMembershipItemView.as_view()),
    path("companies/<slug:slug>/memberships/<int:user_id>/", views.CompanyMembershipItemView.as_view()),
    path("companies/<slug:slug>/memberships", views.CompanyMembershipsView.as_view()),
    path("companies/<slug:slug>/memberships/", views.CompanyMembershipsView.as_view()),
    path("companies/<slug:slug>", views.CompanyItemView.as_view()),
    path("companies/<slug:slug>/", views.CompanyItemView.as_view()),
    path("companies", views.CompanyCollectionView.as_view()),
    path("companies/", views.CompanyCollectionView.as_view()),
]
```

Пока вьюх `CompanyArchiveView`, `CompanyRestoreView`, `CompanyModulesView`,
`CompanyModuleItemView`, `CompanyMembershipsView`, `CompanyMembershipItemView`
нет (задачи 7–8), в этой задаче в `views.py` добавить их заглушками-классами,
каждая — `CompaniesView` без методов (Django ответит 405 — контракт «метод не
разрешён», а не 500):

```python
class CompanyArchiveView(CompaniesView): ...
class CompanyRestoreView(CompaniesView): ...
class CompanyModulesView(CompaniesView): ...
class CompanyModuleItemView(CompaniesView): ...
class CompanyMembershipsView(CompaniesView): ...
class CompanyMembershipItemView(CompaniesView): ...
```

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_read.py apps/core/tests/test_app_isolation.py -q`
Expected: passed.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/companies/schemas.py backend/apps/companies/views.py backend/apps/companies/urls.py backend/apps/companies/tests/api_helpers.py backend/apps/companies/tests/test_api_read.py
git commit -m "feat(companies): HTTP-API реестра — мои компании, список, дерево, карточка

Аппка объявляла API_PREFIX, но не имела urls.py — автодискавери её
пропускал. Переключатель компании во фронте питается от /me.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: правка, архив, восстановление

**Files:**
- Modify: `backend/apps/companies/views.py` (`CompanyItemView.patch`, `CompanyArchiveView`, `CompanyRestoreView`)
- Test: `backend/apps/companies/tests/test_api_write.py`

**Interfaces:**
- Consumes: `lifecycle.update_company/archive_company/restore_company`, `schemas.CompanyPatch`.

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/companies/tests/test_api_write.py
"""Правка, архив и восстановление через HTTP: гейты и коды."""

import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.tests.api_helpers import (
    BASE, auth, patch_json, staff_token, superuser_token, token,
)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def pair(db):
    holding = Company.objects.create(slug="hi-tech-group", name="Group", kind=CompanyKind.HOLDING)
    htq = Company.objects.create(slug="hi-tech-qazaqstan", name="HTQ", kind=CompanyKind.REGIONAL)
    return holding, htq


@pytest.mark.django_db
def test_patch_sets_kind_and_parent_of_the_transition_company(client, pair):
    """Сценарий roadmap §3 п.6: единственная компания получает kind и родителя правкой."""
    res = patch_json(client, f"{BASE}/companies/hi-tech-qazaqstan",
                     {"kind": "construction", "parent_slug": "hi-tech-group", "country": "KZ"},
                     **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["kind"] == "construction"
    assert res.json()["parent_slug"] == "hi-tech-group"
    assert res.json()["country"] == "KZ"


@pytest.mark.django_db
def test_patch_rejects_cycle_unknown_parent_and_bad_kind(client, pair):
    holding, htq = pair
    htq.parent = holding
    htq.save()
    res = patch_json(client, f"{BASE}/companies/hi-tech-group", {"parent_slug": "hi-tech-qazaqstan"},
                     **auth(superuser_token()))
    assert res.status_code == 422
    assert res.json()["code"] == "parent_cycle"

    res = patch_json(client, f"{BASE}/companies/hi-tech-group", {"parent_slug": "nope"},
                     **auth(superuser_token()))
    assert res.status_code == 422
    assert res.json()["code"] == "parent_not_found"

    res = patch_json(client, f"{BASE}/companies/hi-tech-group", {"kind": "branch"},
                     **auth(superuser_token()))
    assert res.status_code == 422  # схема отбивает до сервиса


@pytest.mark.django_db
def test_patch_is_closed_without_write_level(client, pair):
    assert patch_json(client, f"{BASE}/companies/hi-tech-group", {"name": "X"},
                      **auth(token())).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_archive_and_restore_are_platform_operations(client, two_company_schemas):
    alpha, beta = two_company_schemas
    # staff — админ платформы «широкого» толка, но не суперпользователь: 403.
    assert client.post(f"{BASE}/companies/{alpha}/archive",
                       **auth(staff_token())).status_code == 403

    res = client.post(f"{BASE}/companies/{alpha}/archive", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["status"] == "archived"
    assert res.json()["archived_at"] is not None

    # Повтор — идемпотентно, 200 с тем же состоянием.
    assert client.post(f"{BASE}/companies/{alpha}/archive",
                       **auth(superuser_token())).status_code == 200

    # beta теперь единственная действующая — гейт режима перехода.
    res = client.post(f"{BASE}/companies/{beta}/archive", **auth(superuser_token()))
    assert res.status_code == 409
    assert res.json()["code"] == "last_active"
    assert Company.objects.get(slug=beta).status == CompanyStatus.ACTIVE

    res = client.post(f"{BASE}/companies/{alpha}/restore", **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["status"] == "active"
    assert res.json()["archived_at"] is None
```

⚠️ `test_archive_and_restore_are_platform_operations` пересобирает сводки
holding; на выходе снести схему `holding`, как делает `_drop_holding_schema`
в `test_company_archive.py` — скопировать эту функцию и фикстуру
`two_companies` оттуда в начало файла и использовать её вместо
`two_company_schemas` напрямую.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_write.py -q`
Expected: FAIL — 405 на PATCH/POST.

- [ ] **Step 3: Дописать вьюхи**

В `views.py` дополнить `CompanyItemView` и заменить заглушки архива/восстановления:

```python
class CompanyItemView(CompaniesView):
    @read
    def get(self, request, slug: str):
        try:
            return schemas.CompanyRead.model_validate(self.company_or_404(slug))
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)

    @write("PATCH", body=schemas.CompanyPatch)
    def patch(self, request, slug: str, data: schemas.CompanyPatch):
        kwargs = {"name": data.name, "kind": data.kind, "country": data.country}
        if "parent_slug" in data.model_fields_set:
            kwargs["parent_slug"] = data.parent_slug
        try:
            company = lifecycle.update_company(slug, **kwargs)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)


class CompanyArchiveView(CompaniesView):
    @platform("POST")
    def post(self, request, slug: str):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            company, _changed = lifecycle.archive_company(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)


class CompanyRestoreView(CompaniesView):
    @platform("POST")
    def post(self, request, slug: str):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            company, _changed = lifecycle.restore_company(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)
```

`archive_company` возвращает компанию с `select_related("parent")` из
`get_company_or_raise`, поэтому `parent_slug` в ответе не делает лишний запрос.

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_write.py apps/companies/tests/test_api_read.py -q`
Expected: passed.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/companies/views.py backend/apps/companies/tests/test_api_write.py
git commit -m "feat(companies): правка компании, архив и восстановление по HTTP

Архив/восстановление — платформенные операции (is_superuser); гейт
последней действующей компании отвечает 409 last_active.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: модули и участники по HTTP, `API.md`

**Files:**
- Modify: `backend/apps/companies/views.py` (четыре вьюхи)
- Test: `backend/apps/companies/tests/test_api_modules_memberships.py`
- Modify: `API.md` (новый раздел `companies`)

**Interfaces:**
- Consumes: `module_service.list_modules/set_module`, `membership_service.list_memberships/grant_membership/revoke_membership`, `apps.users.interface.get_user_brief`.

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/companies/tests/test_api_modules_memberships.py
"""Модули компании и членство через HTTP."""

import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.companies.tests.api_helpers import (
    BASE, auth, patch_json, post_json, superuser_token, token,
)
from apps.users.models import User, UserStatus


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def company(db):
    return Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION)


@pytest.fixture
def user(db):
    return User.objects.create(username="ivanov", email="ivanov@example.test",
                               password="x", status=UserStatus.ACTIVE)


@pytest.mark.django_db
def test_modules_list_and_patch(client, company):
    res = client.get(f"{BASE}/companies/htq/modules", **auth(superuser_token()))
    assert res.status_code == 200
    tasks = next(m for m in res.json() if m["app_label"] == "tasks")
    assert tasks == {"app_label": "tasks", "enabled": True, "message": "", "is_core": False}

    res = patch_json(client, f"{BASE}/companies/htq/modules/tasks",
                     {"enabled": False, "message": "Закрыто на инвентаризацию"},
                     **auth(superuser_token()))
    assert res.status_code == 200
    assert res.json()["enabled"] is False
    assert res.json()["message"] == "Закрыто на инвентаризацию"


@pytest.mark.django_db
def test_modules_core_is_409_and_unknown_is_422(client, company):
    res = patch_json(client, f"{BASE}/companies/htq/modules/hr", {"enabled": False},
                     **auth(superuser_token()))
    assert res.status_code == 409
    res = patch_json(client, f"{BASE}/companies/htq/modules/warehouse", {"enabled": False},
                     **auth(superuser_token()))
    assert res.status_code == 422


@pytest.mark.django_db
def test_memberships_grant_list_revoke(client, company, user):
    res = post_json(client, f"{BASE}/companies/htq/memberships",
                    {"user_id": user.id, "is_default": True}, **auth(superuser_token()))
    assert res.status_code == 201
    assert res.json()["username"] == "ivanov"
    assert res.json()["is_default"] is True

    # Повтор — 200, второй строки нет.
    res = post_json(client, f"{BASE}/companies/htq/memberships", {"user_id": user.id},
                    **auth(superuser_token()))
    assert res.status_code == 200
    assert CompanyMembership.objects.filter(company=company).count() == 1

    res = client.get(f"{BASE}/companies/htq/memberships", **auth(superuser_token()))
    assert [m["user_id"] for m in res.json()] == [user.id]

    res = client.delete(f"{BASE}/companies/htq/memberships/{user.id}", **auth(superuser_token()))
    assert res.status_code == 204
    assert client.delete(f"{BASE}/companies/htq/memberships/{user.id}",
                         **auth(superuser_token())).status_code == 404


@pytest.mark.django_db
def test_membership_grant_rejects_unknown_user(client, company):
    res = post_json(client, f"{BASE}/companies/htq/memberships", {"user_id": 424242},
                    **auth(superuser_token()))
    assert res.status_code == 422


@pytest.mark.django_db
def test_cannot_revoke_own_membership(client, company):
    CompanyMembership.objects.create(company=company, user_id=9)  # 9 = superuser_token
    res = client.delete(f"{BASE}/companies/htq/memberships/9", **auth(superuser_token()))
    assert res.status_code == 409
    assert res.json()["code"] == "self_revoke"


@pytest.mark.django_db
def test_membership_delete_is_platform_only(client, company, user):
    CompanyMembership.objects.create(company=company, user_id=user.id)
    assert client.delete(f"{BASE}/companies/htq/memberships/{user.id}",
                         **auth(token())).status_code == 403
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_modules_memberships.py -q`
Expected: FAIL — 405.

- [ ] **Step 3: Заменить заглушки вьюхами**

(`JsonResponse` и `get_user_brief` уже импортированы в шапке `views.py` в задаче 6.)

```python
class CompanyModulesView(CompaniesView):
    @read
    def get(self, request, slug: str):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return [schemas.ModuleRead(**row) for row in module_service.list_modules(company)]


class CompanyModuleItemView(CompaniesView):
    @write("PATCH", body=schemas.ModulePatch)
    def patch(self, request, slug: str, app_label: str, data: schemas.ModulePatch):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        try:
            row = module_service.set_module(company, app_label,
                                            enabled=data.enabled, message=data.message)
        except module_service.UnknownModule as exc:
            return json_error(exc.detail, 422)
        except module_service.CoreModuleLocked as exc:
            return json_error(exc.detail, 409)
        return schemas.ModuleRead(**row)


class CompanyMembershipsView(CompaniesView):
    @read
    def get(self, request, slug: str):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return [schemas.MembershipRead(**row)
                for row in membership_service.list_memberships(company)]

    @write("POST", body=schemas.MembershipCreate)
    def post(self, request, slug: str, data: schemas.MembershipCreate):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        if get_user_brief(data.user_id) is None:
            return json_error(f"Пользователь {data.user_id} не найден", 422)
        created = membership_service.grant_membership(
            company, data.user_id, is_default=data.is_default,
        )
        row = next(m for m in membership_service.list_memberships(company)
                   if m["user_id"] == data.user_id)
        return JsonResponse(schemas.MembershipRead(**row).model_dump(mode="json"),
                            status=201 if created else 200)


class CompanyMembershipItemView(CompaniesView):
    @platform("DELETE")
    def delete(self, request, slug: str, user_id: int):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        if user_id == request.token.user_id:
            # Запереть себя снаружи можно одним кликом, а вернуться — только
            # через company_grant в консоли.
            return JsonResponse({"detail": "Нельзя снять членство у себя",
                                 "code": "self_revoke"}, status=409)
        if not membership_service.revoke_membership(company, user_id):
            return json_error("Членства нет", 404)
        return HttpResponse(status=204)
```

`get_user_brief` — импорт `apps.users.interface`: разрешён сторожем изоляции
(`interface`). `membership_service` уже импортирует оттуда же.

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `./.venv/Scripts/python.exe -m pytest apps/companies -q && ./.venv/Scripts/python.exe -m pytest apps/core/tests/test_app_isolation.py apps/core/tests/test_invariants.py -q`
Expected: passed.

- [ ] **Step 5: Задокументировать в `API.md`**

Добавить раздел по образцу соседних (`access`), с таблицей из «Контракт API» этого плана и абзацем: «Заведения компании по HTTP нет намеренно — `manage.py company_create` (миграции ~1 мин, `gunicorn --timeout 60`). Архив последней действующей компании — 409 `last_active` (режим перехода, roadmap §3).»

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/companies/views.py backend/apps/companies/tests/test_api_modules_memberships.py API.md
git commit -m "feat(companies): модули компании и членство по HTTP

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: фронт — домен `companies`: endpoints, прокси, типы, клиент

**Files:**
- Modify: `frontend/src/api/endpoints.ts`, `frontend/vite.config.ts`
- Create: `frontend/src/types/companies.ts`, `frontend/src/api/companies.ts`

**Interfaces:**
- Produces: `companiesApi.{myCompanies, list, tree, get, patch, archive, restore, modules, setModule, memberships, grantMembership, revokeMembership}`; типы `Company`, `CompanyTreeNode`, `MyCompany`, `CompanyPatch`, `CompanyModule`, `CompanyMembership`, `CompanyKind`.

- [ ] **Step 1: Запустить сторож прокси, чтобы увидеть падение после добавления домена**

В `src/api/endpoints.ts` после строки `access: 'access/v1',` добавить:

```ts
  // Реестр компаний группы (Django app apps.companies): мои компании для
  // переключателя, дерево владения, модули и членство.
  companies: 'companies/v1',
```

Run: `cd frontend && npx vitest run src/api/endpoints.proxy.test.ts`
Expected: FAIL — `companies → /api/companies/` отсутствует в таблице прокси.

- [ ] **Step 2: Добавить правило прокси**

В `vite.config.ts` сразу после блока `"^/api/access/"` добавить:

```ts
    // Реестр компаний (apps.companies). Без правила запрос уходит в сам
    // dev-сервер и возвращает index.html — сторож src/api/endpoints.proxy.test.ts.
    "^/api/companies/": {
      target: backendTarget,
      changeOrigin: true,
    },
```

Run: `npx vitest run src/api/endpoints.proxy.test.ts`
Expected: PASS.

- [ ] **Step 3: Типы**

```ts
// frontend/src/types/companies.ts
/**
 * Типы домена реестра компаний (`/api/companies/v1`).
 *
 * Соответствуют таблице «Контракт API» плана
 * docs/plans/2026-09-14-block-a-company-registry.md; расхождение чинится
 * правкой плана, а не подгонкой типов.
 */

export type CompanyKind = 'holding' | 'construction' | 'it' | 'service' | 'regional';
export type CompanyStatus = 'active' | 'archived';

export interface Company {
  id: number;
  slug: string;
  name: string;
  kind: CompanyKind;
  status: CompanyStatus;
  country: string;
  parent_slug: string | null;
  archived_at: string | null;
}

export interface CompanyTreeNode {
  slug: string;
  name: string;
  kind: CompanyKind;
  status: CompanyStatus;
  country: string;
  children: CompanyTreeNode[];
}

export interface MyCompany {
  slug: string;
  name: string;
  kind: CompanyKind;
  is_default: boolean;
  is_current: boolean;
}

/** `parent_slug: null` — «без родителя»; отсутствие ключа — «не трогать». */
export interface CompanyPatch {
  name?: string;
  kind?: CompanyKind;
  country?: string;
  parent_slug?: string | null;
}

export interface CompanyModule {
  app_label: string;
  enabled: boolean;
  message: string;
  is_core: boolean;
}

export interface CompanyMembership {
  user_id: number;
  username: string;
  full_name: string;
  email: string;
  is_active: boolean;
  is_default: boolean;
}

export const COMPANY_KIND_LABELS: Record<CompanyKind, string> = {
  holding: 'Холдинг',
  construction: 'Строительная',
  it: 'IT-компания',
  service: 'Сервисная',
  regional: 'Региональная (устар.)',
};
```

- [ ] **Step 4: Клиент**

```ts
// frontend/src/api/companies.ts
/**
 * api/companies.ts
 * Клиент реестра компаний (`/api/companies/v1`). Пути без завершающего
 * слэша — бэкенд регистрирует оба написания. Слой транспортный.
 *
 * Создания компании здесь нет намеренно: заведение — `manage.py company_create`
 * (миграции схемы ~1 мин не помещаются в HTTP-запрос).
 */

import api from './client';
import { apiPath } from './endpoints';
import type {
  Company,
  CompanyMembership,
  CompanyModule,
  CompanyPatch,
  CompanyTreeNode,
  MyCompany,
} from '@/types/companies';

const path = (suffix: string) => apiPath('companies', suffix);

export const companiesApi = {
  /** Компании, где у меня есть членство и которые действуют. */
  myCompanies: () => api.get<MyCompany[]>(path('me')),

  list: (status: 'all' | 'active' | 'archived' = 'all') =>
    api.get<Company[]>(path(`companies?status=${status}`)),
  tree: () => api.get<CompanyTreeNode[]>(path('companies/tree')),
  get: (slug: string) => api.get<Company>(path(`companies/${slug}`)),
  patch: (slug: string, body: CompanyPatch) =>
    api.patch<Company>(path(`companies/${slug}`), body),
  /** 409 `last_active` — единственную действующую компанию архивировать нельзя. */
  archive: (slug: string) => api.post<Company>(path(`companies/${slug}/archive`)),
  restore: (slug: string) => api.post<Company>(path(`companies/${slug}/restore`)),

  modules: (slug: string) => api.get<CompanyModule[]>(path(`companies/${slug}/modules`)),
  /** 409 — модуль ядра; 422 — неизвестный модуль. */
  setModule: (slug: string, appLabel: string, body: { enabled: boolean; message?: string }) =>
    api.patch<CompanyModule>(path(`companies/${slug}/modules/${appLabel}`), body),

  memberships: (slug: string) =>
    api.get<CompanyMembership[]>(path(`companies/${slug}/memberships`)),
  grantMembership: (slug: string, body: { user_id: number; is_default?: boolean }) =>
    api.post<CompanyMembership>(path(`companies/${slug}/memberships`), body),
  /** 409 `self_revoke` — своё членство снять нельзя. */
  revokeMembership: (slug: string, userId: number) =>
    api.delete<void>(path(`companies/${slug}/memberships/${userId}`)),
};
```

- [ ] **Step 5: Типчек и коммит**

Run: `npx tsc --noEmit -p tsconfig.json && npx vitest run src/api`
Expected: без ошибок; сторож прокси зелёный.

```bash
git add frontend/src/api/endpoints.ts frontend/vite.config.ts frontend/src/types/companies.ts frontend/src/api/companies.ts
git commit -m "feat(frontend): клиент домена companies и правило dev-прокси

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: `useMyCompanies` и `CompanySwitcher` в шапке

**Files:**
- Create: `frontend/src/hooks/useMyCompanies.ts`, `frontend/src/components/companies/CompanySwitcher.tsx`, `frontend/src/components/companies/CompanySwitcher.test.tsx`
- Modify: `frontend/src/components/Header.tsx`

**Interfaces:**
- Consumes: `companiesApi.myCompanies`, `companyFromHost`, `switchCompany` из `src/lib/auth/companySwitch.ts`.
- Produces: `useMyCompanies({ enabled }) -> { companies: MyCompany[], isLoading }`; `<CompanySwitcher />`.

Правило видимости (режим перехода, roadmap §3): переключатель показывается,
если компаний **больше одной**, либо хост **уже** содержит поддомен компании.
Одна компания на голом домене — переключатель скрыт: принудительная
навигация на поддомен сломала бы работу до перевода пользователей на
поддомены (там нужен HTTPS и wildcard-сертификат).

- [ ] **Step 1: Написать падающий тест**

```tsx
// frontend/src/components/companies/CompanySwitcher.test.tsx
/**
 * Переключатель компании. Главное — правило видимости режима перехода:
 * одна компания на голом домене = переключателя нет.
 */
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { MyCompany } from '@/types/companies';

import { CompanySwitcher } from './CompanySwitcher';

const myCompanies = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: { myCompanies: () => myCompanies() },
}));

const switchCompany = vi.fn();
const companyFromHost = vi.fn<[string], string | null>();
vi.mock('@/lib/auth/companySwitch', () => ({
  switchCompany: (slug: string) => switchCompany(slug),
  companyFromHost: (host: string) => companyFromHost(host),
}));

const htq: MyCompany = { slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction', is_default: true, is_current: true };
const group: MyCompany = { slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', is_default: false, is_current: false };

describe('CompanySwitcher', () => {
  beforeEach(() => {
    switchCompany.mockReset();
    companyFromHost.mockReset();
  });

  it('скрыт при одной компании на голом домене (режим перехода)', async () => {
    companyFromHost.mockReturnValue(null);
    myCompanies.mockResolvedValue({ data: [htq] });
    renderWithProviders(<CompanySwitcher />);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('виден при одной компании, если хост уже на её поддомене', async () => {
    companyFromHost.mockReturnValue('hi-tech-qazaqstan');
    myCompanies.mockResolvedValue({ data: [htq] });
    renderWithProviders(<CompanySwitcher />);
    expect(await screen.findByRole('combobox')).toHaveTextContent('Hi-Tech Qazaqstan');
  });

  it('при выборе другой компании переходит на её поддомен', async () => {
    companyFromHost.mockReturnValue('hi-tech-qazaqstan');
    myCompanies.mockResolvedValue({ data: [htq, group] });
    renderWithProviders(<CompanySwitcher />);
    await userEvent.click(await screen.findByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: /Hi-Tech Group/ }));
    expect(switchCompany).toHaveBeenCalledWith('hi-tech-group');
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `npx vitest run src/components/companies/CompanySwitcher.test.tsx`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Хук и компонент**

```ts
// frontend/src/hooks/useMyCompanies.ts
import { useQuery } from '@tanstack/react-query';

import { companiesApi } from '@/api/companies';
import type { MyCompany } from '@/types/companies';

/** Компании, куда пользователя пускают (членство, действующие). Кэш 5 минут — как у usePermissions. */
export function useMyCompanies(options: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: ['companies', 'me'],
    queryFn: async () => (await companiesApi.myCompanies()).data,
    enabled: options.enabled ?? true,
    staleTime: 5 * 60 * 1000,
  });
  return {
    companies: (query.data ?? []) as MyCompany[],
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
```

```tsx
// frontend/src/components/companies/CompanySwitcher.tsx
import { Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useMyCompanies } from '@/hooks/useMyCompanies';
import { companyFromHost, switchCompany } from '@/lib/auth/companySwitch';

/**
 * Переключатель компании — навигация на поддомен, не запрос к API
 * (см. lib/auth/companySwitch.ts).
 *
 * Правило видимости — режим перехода (roadmap §3): компаний больше одной,
 * ЛИБО хост уже содержит поддомен компании. Одна компания на голом домене —
 * переключателя нет: принудительный уход на поддомен требует HTTPS и
 * wildcard-сертификата, которых у стенда может не быть.
 */
export function CompanySwitcher({ enabled = true }: { enabled?: boolean }) {
  const { t } = useTranslation();
  const { companies } = useMyCompanies({ enabled });
  const current = typeof window !== 'undefined' ? companyFromHost(window.location.host) : null;

  if (companies.length === 0) return null;
  if (companies.length === 1 && current === null) return null;

  const value = current ?? companies.find((c) => c.is_current)?.slug ?? companies[0].slug;

  return (
    <Select value={value} onValueChange={(slug) => { if (slug !== current) switchCompany(slug); }}>
      <SelectTrigger
        className="h-10 w-auto min-w-[12rem] gap-2 rounded-full"
        aria-label={t('companies.switcher.label', 'Компания')}
      >
        <Building2 className="h-4 w-4 shrink-0 text-primary" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {companies.map((c) => (
          <SelectItem key={c.slug} value={c.slug}>{c.name}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default CompanySwitcher;
```

Проверить, что `@/components/ui/select` существует (shadcn `Select` уже
используется в `OrgChart/index.tsx` — `SelectItem`); если экспортов
`SelectTrigger`/`SelectValue` нет, взять тот же импорт, что там.

- [ ] **Step 4: Вставить в `Header.tsx`**

Импорт: `import { CompanySwitcher } from '@/components/companies/CompanySwitcher';`.

В десктопном блоке, перед `<Link to="/myprofile">` в ветке `isLoggedIn`
(строка ~264), добавить `<CompanySwitcher enabled={isLoggedIn} />`. В
мобильном меню, первым элементом `<nav>` внутри `isLoggedIn ? … :` — тот же
компонент в обёртке `<div className="px-2 pb-2">`.

- [ ] **Step 5: Тесты, типчек**

Run: `npx vitest run src/components/companies src/components/Header.test.tsx 2>/dev/null; npx tsc --noEmit -p tsconfig.json`
(если `Header.test.tsx` нет — только первый путь). Expected: PASS, tsc чисто.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/hooks/useMyCompanies.ts frontend/src/components/companies/CompanySwitcher.tsx frontend/src/components/companies/CompanySwitcher.test.tsx frontend/src/components/Header.tsx
git commit -m "feat(frontend): переключатель компании в шапке

switchCompany существовал с подпроекта 1, но никем не вызывался. Правило
видимости учитывает режим перехода: одна компания на голом домене —
переключателя нет.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: страница `/companies` — дерево группы и карточка

**Files:**
- Create: `frontend/src/pages/companies/CompanyRegistry.tsx`, `frontend/src/pages/companies/CompanyRegistry.test.tsx`
- Modify: `frontend/src/app/routing/lazyPages.ts`, `frontend/src/app/routing/routeDefinitions.ts`, `frontend/src/components/profile/ProfileSidebar.tsx`

**Interfaces:**
- Consumes: `companiesApi.tree/list/archive/restore`, `isPlatformAdmin` (`@/lib/auth/roles`), `useActiveProfile`.
- Produces: страница с `data-testid="company-tree"` и панелью выбранной компании; кнопки «В архив»/«Вернуть из архива» только для платформенного администратора; пропсы-слоты для задач 12–13: `onEdit(company)`, `<CompanyModulesPanel slug>`, `<CompanyMembersPanel slug>` (пока не рендерятся).

- [ ] **Step 1: Написать падающий тест**

```tsx
// frontend/src/pages/companies/CompanyRegistry.test.tsx
/**
 * Реестр компаний. Проверяем то, что отличает экран: дерево из ответа
 * /companies/tree, подпись «создание — командой», архив как платформенная
 * операция и читаемый отказ 409 last_active.
 */
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import CompanyRegistry from './CompanyRegistry';

const tree = vi.fn();
const list = vi.fn();
const archive = vi.fn();
const restore = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: {
    tree: () => tree(),
    list: () => list(),
    archive: (slug: string) => archive(slug),
    restore: (slug: string) => restore(slug),
    modules: vi.fn(), setModule: vi.fn(), memberships: vi.fn(),
    grantMembership: vi.fn(), revokeMembership: vi.fn(), patch: vi.fn(), get: vi.fn(),
    myCompanies: vi.fn(),
  },
}));

const roles = vi.fn<[], string[]>();
vi.mock('@/hooks/useActiveProfile', () => ({
  useActiveProfile: () => ({ activeProfile: { roles: roles() }, isLoggedIn: true }),
}));
vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));

const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

const TREE = [{
  slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '',
  children: [{ slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction',
               status: 'active', country: 'KZ', children: [] }],
}];
const LIST = [
  { id: 1, slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '', parent_slug: null, archived_at: null },
  { id: 2, slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction', status: 'active', country: 'KZ', parent_slug: 'hi-tech-group', archived_at: null },
];

describe('CompanyRegistry', () => {
  beforeEach(() => {
    tree.mockResolvedValue({ data: TREE });
    list.mockResolvedValue({ data: LIST });
    archive.mockReset();
    toastError.mockReset();
  });

  it('рисует дерево владения и говорит, что создание — командой', async () => {
    roles.mockReturnValue(['admin']);
    renderWithProviders(<CompanyRegistry />);
    const treeEl = await screen.findByTestId('company-tree');
    expect(within(treeEl).getByText('Hi-Tech Group')).toBeInTheDocument();
    expect(within(treeEl).getByText('Hi-Tech Qazaqstan')).toBeInTheDocument();
    expect(screen.getByText(/company_create/)).toBeInTheDocument();
  });

  it('не показывает архив не платформенному администратору', async () => {
    roles.mockReturnValue(['staff']);
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    expect(screen.queryByRole('button', { name: /В архив/ })).toBeNull();
  });

  it('409 last_active показывается читаемо', async () => {
    roles.mockReturnValue(['admin']);
    archive.mockRejectedValue({ response: { status: 409, data: { detail: 'единственная действующая', code: 'last_active' } } });
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    await userEvent.click(screen.getByRole('button', { name: /В архив/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Подтвердить/ }));
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/единственная действующая/));
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `npx vitest run src/pages/companies/CompanyRegistry.test.tsx`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Страница**

```tsx
// frontend/src/pages/companies/CompanyRegistry.tsx
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { Archive, ArchiveRestore, Building2, CornerDownRight, Pencil, Terminal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { BackToProfile } from '@/components/BackToProfile';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { isPlatformAdmin } from '@/lib/auth/roles';
import { COMPANY_KIND_LABELS, type Company, type CompanyTreeNode } from '@/types/companies';

type ApiErr = AxiosError<{ detail?: string; code?: string }>;

const errorText = (e: unknown, fallback: string) =>
  (e as ApiErr)?.response?.data?.detail ?? fallback;

function TreeBranch({ node, depth, selected, onSelect }: {
  node: CompanyTreeNode; depth: number; selected: string | null; onSelect: (slug: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.slug)}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent ${selected === node.slug ? 'bg-accent font-medium' : ''}`}
        style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}
      >
        {depth > 0 ? <CornerDownRight className="h-4 w-4 text-muted-foreground" /> : <Building2 className="h-4 w-4 text-primary" />}
        <span>{node.name}</span>
        <Badge variant="outline" className="ml-auto">{COMPANY_KIND_LABELS[node.kind]}</Badge>
      </button>
      {node.children.length > 0 && (
        <ul>{node.children.map((c) => (
          <TreeBranch key={c.slug} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} />
        ))}</ul>
      )}
    </li>
  );
}

const CompanyRegistry = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile({ retry: false });
  const platformAdmin = isPlatformAdmin(activeProfile?.roles);

  const [selected, setSelected] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'archive' | 'restore' | null>(null);

  const treeQuery = useQuery({ queryKey: ['companies', 'tree'], queryFn: async () => (await companiesApi.tree()).data });
  const listQuery = useQuery({ queryKey: ['companies', 'list'], queryFn: async () => (await companiesApi.list()).data });

  const bySlug = useMemo(() => new Map((listQuery.data ?? []).map((c) => [c.slug, c])), [listQuery.data]);
  const company: Company | undefined = selected ? bySlug.get(selected) : undefined;
  const archived = (listQuery.data ?? []).filter((c) => c.status === 'archived');

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['companies'] });

  const archiveMut = useMutation({
    mutationFn: (slug: string) => companiesApi.archive(slug),
    onSuccess: () => { toast.success(t('companies.archived', 'Компания переведена в архив')); invalidate(); },
    onError: (e) => toast.error(errorText(e, t('companies.archiveFailed', 'Не удалось архивировать'))),
    onSettled: () => setConfirm(null),
  });
  const restoreMut = useMutation({
    mutationFn: (slug: string) => companiesApi.restore(slug),
    onSuccess: () => { toast.success(t('companies.restored', 'Компания возвращена из архива')); invalidate(); },
    onError: (e) => toast.error(errorText(e, t('companies.restoreFailed', 'Не удалось восстановить'))),
    onSettled: () => setConfirm(null),
  });

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main className="container mx-auto w-full max-w-6xl flex-1 space-y-4 px-4 py-8">
        <BackToProfile />
        <div>
          <h1 className="text-2xl font-bold">{t('companies.title', 'Компании группы')}</h1>
          <p className="text-sm text-muted-foreground">
            {t('companies.subtitle', 'Дерево владения: холдинг и дочерние общества. Каждая компания — своя схема данных.')}
          </p>
        </div>

        <div className="flex items-start gap-2 rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          <Terminal className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            {t('companies.createHint',
              'Заведение новой компании — командой оператора: manage.py company_create <slug> --name … --kind … --parent … '
              + '(миграции схемы идут около минуты и в HTTP-запрос не помещаются).')}
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-[minmax(16rem,1fr)_2fr]">
          <section className="rounded-xl border bg-card p-3">
            <ul data-testid="company-tree" className="space-y-0.5">
              {(treeQuery.data ?? []).map((node) => (
                <TreeBranch key={node.slug} node={node} depth={0} selected={selected} onSelect={setSelected} />
              ))}
            </ul>
            {archived.length > 0 && (
              <div className="mt-3 border-t pt-3">
                <p className="px-2 text-xs uppercase text-muted-foreground">{t('companies.archivedHeading', 'В архиве')}</p>
                <ul className="space-y-0.5">
                  {archived.map((c) => (
                    <li key={c.slug}>
                      <button type="button" onClick={() => setSelected(c.slug)}
                        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent ${selected === c.slug ? 'bg-accent' : ''}`}>
                        <Archive className="h-4 w-4" /><span>{c.name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section className="rounded-xl border bg-card p-4">
            {!company ? (
              <p className="text-sm text-muted-foreground">{t('companies.pick', 'Выберите компанию в дереве.')}</p>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold">{company.name}</h2>
                  <Badge variant="outline">{COMPANY_KIND_LABELS[company.kind]}</Badge>
                  <Badge variant={company.status === 'active' ? 'default' : 'secondary'}>
                    {company.status === 'active' ? t('companies.status.active', 'Действует') : t('companies.status.archived', 'В архиве')}
                  </Badge>
                </div>
                <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
                  <dt className="text-muted-foreground">slug</dt><dd className="font-mono">{company.slug}</dd>
                  <dt className="text-muted-foreground">{t('companies.field.country', 'Страна')}</dt><dd>{company.country || '—'}</dd>
                  <dt className="text-muted-foreground">{t('companies.field.parent', 'Вышестоящая')}</dt><dd>{company.parent_slug ?? '—'}</dd>
                </dl>

                {platformAdmin && (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" disabled title={t('companies.editSoon', 'Правка — в следующей задаче')}>
                      <Pencil className="mr-1 h-4 w-4" />{t('companies.edit', 'Изменить')}
                    </Button>
                    {company.status === 'active' ? (
                      <Button variant="destructive" size="sm" onClick={() => setConfirm('archive')}>
                        <Archive className="mr-1 h-4 w-4" />{t('companies.archive', 'В архив')}
                      </Button>
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => setConfirm('restore')}>
                        <ArchiveRestore className="mr-1 h-4 w-4" />{t('companies.restore', 'Вернуть из архива')}
                      </Button>
                    )}
                  </div>
                )}

                {confirm && (
                  <div role="alertdialog" className="rounded-lg border border-amber-300/70 bg-amber-50/70 p-3 text-sm dark:border-amber-800/70 dark:bg-amber-950/30">
                    <p>
                      {confirm === 'archive'
                        ? t('companies.confirmArchive', 'Архив закрывает весь трафик компании: её поддомен ответит 404. Данные остаются на месте.')
                        : t('companies.confirmRestore', 'Компания снова станет доступна на своём поддомене и войдёт в сводки холдинга.')}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" onClick={() => (confirm === 'archive' ? archiveMut : restoreMut).mutate(company.slug)}
                        disabled={archiveMut.isPending || restoreMut.isPending}>
                        {t('common.confirm', 'Подтвердить')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>{t('common.cancel', 'Отмена')}</Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default CompanyRegistry;
```

- [ ] **Step 4: Маршрут, ленивый импорт, пункт меню**

`lazyPages.ts` после `AccessRoleCatalog`:

```ts
  CompanyRegistry: React.lazy(() => import('@/pages/companies/CompanyRegistry')),
```

`routeDefinitions.ts` после маршрута `/access/roles`:

```ts
  // ─── Реестр компаний группы ───────────────────────────────────────────
  // read — минимум для входа; архив/восстановление страница показывает только
  // платформенному администратору, сервер отвечает 403 остальным.
  { path: '/companies', component: lazyPages.CompanyRegistry, requiresAuth: true, requires: { module: 'companies', level: 'read' } },
```

`ProfileSidebar.tsx`, в `adminItems` перед `access-roles`:

```ts
            { id: 'companies', to: '/companies', icon: Building2, label: t('profile.sidebar.companies', 'Компании группы') },
```

(`Building2` уже импортирован в файле для `hr-departments`.)

- [ ] **Step 5: Тесты, типчек, линт**

Run: `npx vitest run src/pages/companies src/components/profile && npx tsc --noEmit -p tsconfig.json && npm run lint`
Expected: PASS; lint чисто.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/pages/companies/CompanyRegistry.tsx frontend/src/pages/companies/CompanyRegistry.test.tsx frontend/src/app/routing/lazyPages.ts frontend/src/app/routing/routeDefinitions.ts frontend/src/components/profile/ProfileSidebar.tsx
git commit -m "feat(frontend): страница «Компании группы» — дерево владения, архив и восстановление

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: `CompanyFormDialog` — правка реестровых полей

**Files:**
- Create: `frontend/src/components/companies/CompanyFormDialog.tsx`, `CompanyFormDialog.test.tsx`
- Modify: `frontend/src/pages/companies/CompanyRegistry.tsx` (кнопка «Изменить» открывает диалог)

**Interfaces:**
- Consumes: `companiesApi.patch(slug, CompanyPatch)`, `companiesApi.list` (варианты родителя).
- Produces: `<CompanyFormDialog company={Company} candidates={Company[]} open onOpenChange onSaved />`.

- [ ] **Step 1: Написать падающий тест**

```tsx
// frontend/src/components/companies/CompanyFormDialog.test.tsx
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Company } from '@/types/companies';

import { CompanyFormDialog } from './CompanyFormDialog';

const patch = vi.fn();
vi.mock('@/api/companies', () => ({ companiesApi: { patch: (s: string, b: unknown) => patch(s, b) } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const group: Company = { id: 1, slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '', parent_slug: null, archived_at: null };
const htq: Company = { id: 2, slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'regional', status: 'active', country: '', parent_slug: null, archived_at: null };

describe('CompanyFormDialog', () => {
  it('отправляет PATCH только с изменёнными полями, parent_slug — явно', async () => {
    patch.mockResolvedValue({ data: { ...htq, kind: 'construction', parent_slug: 'hi-tech-group', country: 'KZ' } });
    const onSaved = vi.fn();
    renderWithProviders(
      <CompanyFormDialog company={htq} candidates={[group, htq]} open onOpenChange={() => {}} onSaved={onSaved} />,
    );
    await userEvent.selectOptions(screen.getByLabelText(/Вид/), 'construction');
    await userEvent.selectOptions(screen.getByLabelText(/Вышестоящая/), 'hi-tech-group');
    await userEvent.type(screen.getByLabelText(/Страна/), 'KZ');
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/ }));

    expect(patch).toHaveBeenCalledWith('hi-tech-qazaqstan',
      { kind: 'construction', parent_slug: 'hi-tech-group', country: 'KZ' });
    expect(onSaved).toHaveBeenCalled();
  });

  it('не предлагает саму компанию в качестве родителя', () => {
    renderWithProviders(
      <CompanyFormDialog company={htq} candidates={[group, htq]} open onOpenChange={() => {}} onSaved={() => {}} />,
    );
    const options = Array.from((screen.getByLabelText(/Вышестоящая/) as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(['', 'hi-tech-group']);
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `npx vitest run src/components/companies/CompanyFormDialog.test.tsx`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Диалог**

```tsx
// frontend/src/components/companies/CompanyFormDialog.tsx
import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { COMPANY_KIND_LABELS, type Company, type CompanyKind, type CompanyPatch } from '@/types/companies';

interface Props {
  company: Company;
  /** Кандидаты в родители: сама компания исключается здесь. */
  candidates: Company[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (company: Company) => void;
}

/** Нативные <select>: список из 4–5 значений, и тесты через selectOptions. */
export function CompanyFormDialog({ company, candidates, open, onOpenChange, onSaved }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(company.name);
  const [kind, setKind] = useState<CompanyKind>(company.kind);
  const [country, setCountry] = useState(company.country);
  const [parent, setParent] = useState(company.parent_slug ?? '');

  useEffect(() => {
    setName(company.name); setKind(company.kind); setCountry(company.country); setParent(company.parent_slug ?? '');
  }, [company]);

  const mutation = useMutation({
    mutationFn: (body: CompanyPatch) => companiesApi.patch(company.slug, body),
    onSuccess: (res) => { toast.success(t('companies.saved', 'Сохранено')); onSaved(res.data); onOpenChange(false); },
    onError: (e: AxiosError<{ detail?: string }>) =>
      toast.error(e.response?.data?.detail ?? t('companies.saveFailed', 'Не удалось сохранить')),
  });

  const submit = () => {
    const body: CompanyPatch = {};
    if (name !== company.name) body.name = name;
    if (kind !== company.kind) body.kind = kind;
    if (country !== company.country) body.country = country;
    if ((parent || null) !== company.parent_slug) body.parent_slug = parent || null;
    mutation.mutate(body);
  };

  const kinds = (Object.keys(COMPANY_KIND_LABELS) as CompanyKind[]).filter((k) => k !== 'regional' || company.kind === 'regional');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('companies.editTitle', 'Компания')}: {company.name}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label htmlFor="cf-name">{t('companies.field.name', 'Название')}</Label>
            <Input id="cf-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label htmlFor="cf-kind">{t('companies.field.kind', 'Вид')}</Label>
            <select id="cf-kind" className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value as CompanyKind)}>
              {kinds.map((k) => <option key={k} value={k}>{COMPANY_KIND_LABELS[k]}</option>)}
            </select></div>
          <div><Label htmlFor="cf-parent">{t('companies.field.parent', 'Вышестоящая')}</Label>
            <select id="cf-parent" className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm" value={parent} onChange={(e) => setParent(e.target.value)}>
              <option value="">{t('companies.noParent', '— нет (корень) —')}</option>
              {candidates.filter((c) => c.slug !== company.slug).map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
            </select></div>
          <div><Label htmlFor="cf-country">{t('companies.field.country', 'Страна')}</Label>
            <Input id="cf-country" maxLength={2} value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} /></div>
          <p className="text-xs text-muted-foreground">
            {t('companies.slugLocked', 'slug не правится: он — имя схемы данных и поддомен компании.')}
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel', 'Отмена')}</Button>
          <Button onClick={submit} disabled={mutation.isPending}>{t('common.save', 'Сохранить')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Подключить на странице**

В `CompanyRegistry.tsx`: `const [editing, setEditing] = useState(false);`; кнопка
«Изменить» — `onClick={() => setEditing(true)}` без `disabled`; после
`</section>` карточки:

```tsx
        {company && (
          <CompanyFormDialog company={company} candidates={listQuery.data ?? []} open={editing}
            onOpenChange={setEditing} onSaved={() => invalidate()} />
        )}
```

- [ ] **Step 5: Тесты, типчек**

Run: `npx vitest run src/components/companies src/pages/companies && npx tsc --noEmit -p tsconfig.json`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/components/companies/CompanyFormDialog.tsx frontend/src/components/companies/CompanyFormDialog.test.tsx frontend/src/pages/companies/CompanyRegistry.tsx
git commit -m "feat(frontend): правка компании — вид, вышестоящая, страна

Именно этой формой единственная боевая компания получит kind=construction
и родителя-холдинг, когда тот будет заведён (roadmap §7, шаг 5).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: панели модулей и участников

**Files:**
- Create: `frontend/src/components/companies/CompanyModulesPanel.tsx`, `CompanyMembersPanel.tsx`, `CompanyPanels.test.tsx`
- Modify: `frontend/src/pages/companies/CompanyRegistry.tsx` (вкладки под карточкой)

**Interfaces:**
- Consumes: `companiesApi.modules/setModule/memberships/grantMembership/revokeMembership`.
- Produces: `<CompanyModulesPanel slug canEdit />`, `<CompanyMembersPanel slug canEdit canRevoke />`.

- [ ] **Step 1: Написать падающий тест**

```tsx
// frontend/src/components/companies/CompanyPanels.test.tsx
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { CompanyMembersPanel } from './CompanyMembersPanel';
import { CompanyModulesPanel } from './CompanyModulesPanel';

const modules = vi.fn();
const setModule = vi.fn();
const memberships = vi.fn();
const grantMembership = vi.fn();
const revokeMembership = vi.fn();
vi.mock('@/api/companies', () => ({
  companiesApi: {
    modules: () => modules(), setModule: (s: string, a: string, b: unknown) => setModule(s, a, b),
    memberships: () => memberships(), grantMembership: (s: string, b: unknown) => grantMembership(s, b),
    revokeMembership: (s: string, u: number) => revokeMembership(s, u),
  },
}));
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

describe('CompanyModulesPanel', () => {
  beforeEach(() => {
    modules.mockResolvedValue({ data: [
      { app_label: 'hr', enabled: true, message: '', is_core: true },
      { app_label: 'tasks', enabled: true, message: '', is_core: false },
    ] });
    setModule.mockResolvedValue({ data: { app_label: 'tasks', enabled: false, message: '', is_core: false } });
  });

  it('ядро не переключается, обычный модуль — PATCH с enabled=false', async () => {
    renderWithProviders(<CompanyModulesPanel slug="htq" canEdit />);
    const hr = await screen.findByRole('switch', { name: /hr/ });
    expect(hr).toBeDisabled();
    await userEvent.click(screen.getByRole('switch', { name: /tasks/ }));
    expect(setModule).toHaveBeenCalledWith('htq', 'tasks', { enabled: false });
  });
});

describe('CompanyMembersPanel', () => {
  beforeEach(() => {
    memberships.mockResolvedValue({ data: [
      { user_id: 7, username: 'ivanov', full_name: 'Иванов Иван', email: 'i@x', is_active: true, is_default: true },
    ] });
    grantMembership.mockResolvedValue({ data: { user_id: 8, username: 'petrov', full_name: '', email: '', is_active: true, is_default: false } });
    revokeMembership.mockReset();
  });

  it('выдаёт членство по id и показывает отказ self_revoke', async () => {
    revokeMembership.mockRejectedValue({ response: { status: 409, data: { detail: 'Нельзя снять членство у себя', code: 'self_revoke' } } });
    renderWithProviders(<CompanyMembersPanel slug="htq" canEdit canRevoke />);
    expect(await screen.findByText('ivanov')).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/id пользователя/i), '8');
    await userEvent.click(screen.getByRole('button', { name: /Выдать/ }));
    expect(grantMembership).toHaveBeenCalledWith('htq', { user_id: 8, is_default: false });

    await userEvent.click(screen.getByRole('button', { name: /Снять/ }));
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/у себя/));
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `npx vitest run src/components/companies/CompanyPanels.test.tsx`
Expected: FAIL — модули не найдены.

- [ ] **Step 3: Панели**

```tsx
// frontend/src/components/companies/CompanyModulesPanel.tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { Switch } from '@/components/ui/switch';

export function CompanyModulesPanel({ slug, canEdit }: { slug: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['companies', slug, 'modules'], queryFn: async () => (await companiesApi.modules(slug)).data });
  const mutation = useMutation({
    mutationFn: ({ appLabel, enabled }: { appLabel: string; enabled: boolean }) =>
      companiesApi.setModule(slug, appLabel, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['companies', slug, 'modules'] }),
    onError: (e: AxiosError<{ detail?: string }>) =>
      toast.error(e.response?.data?.detail ?? t('companies.modules.failed', 'Не удалось переключить модуль')),
  });

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {t('companies.modules.hint', 'Модули ядра есть у каждой компании и не выключаются. Выключенный модуль отвечает 503 только в этой компании.')}
      </p>
      <ul className="divide-y rounded-lg border">
        {(query.data ?? []).map((m) => (
          <li key={m.app_label} className="flex items-center justify-between px-3 py-2 text-sm">
            <span className="font-mono">{m.app_label}{m.is_core && <span className="ml-2 text-xs text-muted-foreground">{t('companies.modules.core', 'ядро')}</span>}</span>
            <Switch aria-label={m.app_label} checked={m.enabled} disabled={m.is_core || !canEdit || mutation.isPending}
              onCheckedChange={(enabled) => mutation.mutate({ appLabel: m.app_label, enabled })} />
          </li>
        ))}
      </ul>
    </div>
  );
}
```

```tsx
// frontend/src/components/companies/CompanyMembersPanel.tsx
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type ApiErr = AxiosError<{ detail?: string; code?: string }>;

export function CompanyMembersPanel({ slug, canEdit, canRevoke }: { slug: string; canEdit: boolean; canRevoke: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState('');
  const key = ['companies', slug, 'memberships'];
  const query = useQuery({ queryKey: key, queryFn: async () => (await companiesApi.memberships(slug)).data });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });
  const fail = (e: ApiErr, fallback: string) => toast.error(e.response?.data?.detail ?? fallback);

  const grant = useMutation({
    mutationFn: (id: number) => companiesApi.grantMembership(slug, { user_id: id, is_default: false }),
    onSuccess: () => { setUserId(''); invalidate(); },
    onError: (e: ApiErr) => fail(e, t('companies.members.grantFailed', 'Не удалось выдать членство')),
  });
  const revoke = useMutation({
    mutationFn: (id: number) => companiesApi.revokeMembership(slug, id),
    onSuccess: invalidate,
    onError: (e: ApiErr) => fail(e, t('companies.members.revokeFailed', 'Не удалось снять членство')),
  });

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t('companies.members.hint', 'Членство — право войти в компанию (токен получает claim company). Права внутри компании выдают роли должности и личные назначения.')}
      </p>
      <ul className="divide-y rounded-lg border">
        {(query.data ?? []).map((m) => (
          <li key={m.user_id} className="flex items-center gap-3 px-3 py-2 text-sm">
            <span className="font-mono">{m.username || `#${m.user_id}`}</span>
            <span className="text-muted-foreground">{m.full_name}</span>
            {m.is_default && <span className="text-xs text-muted-foreground">{t('companies.members.default', 'по умолчанию')}</span>}
            {!m.is_active && <span className="text-xs text-destructive">{t('companies.members.inactive', 'учётка неактивна')}</span>}
            {canRevoke && (
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => revoke.mutate(m.user_id)} disabled={revoke.isPending}>
                {t('companies.members.revoke', 'Снять')}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {canEdit && (
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); const id = Number(userId); if (id > 0) grant.mutate(id); }}>
          <div>
            <Label htmlFor="cm-user">{t('companies.members.userId', 'id пользователя')}</Label>
            <Input id="cm-user" inputMode="numeric" value={userId} onChange={(e) => setUserId(e.target.value.replace(/\D/g, ''))} className="w-40" />
          </div>
          <Button type="submit" size="sm" disabled={!userId || grant.isPending}>{t('companies.members.grant', 'Выдать')}</Button>
        </form>
      )}
    </div>
  );
}
```

Проверить наличие `@/components/ui/switch` и `@/components/ui/label` (shadcn);
если `Switch` отсутствует — `npx shadcn@latest add switch` в `frontend/`.

- [ ] **Step 4: Вкладки на странице**

В `CompanyRegistry.tsx` под блоком кнопок карточки (внутри `company && …`):

```tsx
                <div className="border-t pt-4">
                  <div className="mb-2 flex gap-2">
                    {(['modules', 'members'] as const).map((tab) => (
                      <Button key={tab} size="sm" variant={panel === tab ? 'default' : 'outline'} onClick={() => setPanel(tab)}>
                        {tab === 'modules' ? t('companies.tab.modules', 'Модули') : t('companies.tab.members', 'Участники')}
                      </Button>
                    ))}
                  </div>
                  {panel === 'modules'
                    ? <CompanyModulesPanel slug={company.slug} canEdit={platformAdmin} />
                    : <CompanyMembersPanel slug={company.slug} canEdit={platformAdmin} canRevoke={platformAdmin} />}
                </div>
```

и `const [panel, setPanel] = useState<'modules' | 'members'>('modules');` плюс импорты панелей.

- [ ] **Step 5: Тесты, типчек, линт**

Run: `npx vitest run src/components/companies src/pages/companies && npx tsc --noEmit -p tsconfig.json && npm run lint`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/components/companies/CompanyModulesPanel.tsx frontend/src/components/companies/CompanyMembersPanel.tsx frontend/src/components/companies/CompanyPanels.test.tsx frontend/src/pages/companies/CompanyRegistry.tsx
git commit -m "feat(frontend): модули и участники компании на странице реестра

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: сквозная проверка, `STRUCTURE.md`, рантбук выкатки

**Files:**
- Modify: `STRUCTURE.md` (аппка `companies`: `urls/views/schemas`, сервисы `lifecycle`/`module_service`; фронт `pages/companies`, `components/companies`), `docs/multi-company-tenancy-followups.md` (п.6 «companySwitch не подключён» — ЗАКРЫТО).

- [ ] **Step 1: Полный прогон бэкенда**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: зелёный; число тестов выросло на ~40. Два известных ночных падения
`tasks` (UTC/Алматы, followups) — не наши.

- [ ] **Step 2: Полный прогон фронта**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json && npm run lint && npm test`
Expected: чисто.

- [ ] **Step 3: Живой стенд — путь поддомен → заголовок → API**

```bash
docker compose -f docker-compose.test-local.yml up -d --build
cd backend
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe manage.py tenancy_status
```

Ожидание: реестр стенда (0 или 1 компания), таблицы в `public`. Затем в
браузере `http://localhost:3000/companies` под `admin/admin12345`: дерево,
карточка, вкладки; кнопка «В архив» у единственной компании → тост
«единственная действующая…». Переключатель в шапке при одной компании на
`localhost` **скрыт** — это ожидаемо (Task 10).

- [ ] **Step 4: Документы**

`STRUCTURE.md` — в описании `apps/companies` добавить `urls.py`, `views.py`,
`schemas.py`, `services/lifecycle.py`, `services/module_service.py`,
`management/commands/tenancy_status.py`; во фронте — `pages/companies/`,
`components/companies/`, `hooks/useMyCompanies.ts`.

`docs/multi-company-tenancy-followups.md`, п.6 — дописать сверху:
«**ЗАКРЫТО блоком A** (docs/plans/2026-09-14-block-a-company-registry.md):
`CompanySwitcher` в шапке зовёт `switchCompany`; правило видимости — режим
перехода».

- [ ] **Step 5: Коммит**

```bash
git add STRUCTURE.md docs/multi-company-tenancy-followups.md
git commit -m "docs: реестр компаний в карте структуры, followup 6 закрыт

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Рантбук боевой выкатки блока A (режим перехода)

1. До выкатки: `manage.py tenancy_status --json > before.json` на боевом
   контейнере `backend-web`.
2. Выкатка образов. `migrate_shared` применит `companies/0003` (только
   `choices`, SQL нет). Тенантные схемы не трогаются.
3. После: `manage.py tenancy_status --json > after.json`; `diff before.json
   after.json` — различий в `companies` и `schemas` быть не должно
   (оценки строк могут дрожать — сравнивать состав таблиц, при сомнении
   `--exact`).
4. Проверить `GET /api/companies/v1/me` под боевой учёткой и открыть
   `/companies`. Убедиться, что архив единственной компании отвечает 409.
5. Остальные компании **не заводить** — roadmap §7, шаг 5.

## Self-review (выполнен)

- **Покрытие roadmap §5.A:** API/экраны — задачи 6–8, 11–13; `me` +
  переключатель — 6, 10; `CompanyKind` — 2; `tenancy_status` — 1;
  гейт последней компании — 3 (+7 по HTTP); docs — 2, 8, 14. Создание по
  HTTP исключено осознанно (см. Architecture); roadmap §5.A говорит то же.
- **Плейсхолдеры:** нет.
- **Согласованность имён:** `lifecycle.get_company_or_raise` (3 → 6, 7, 8);
  `LifecycleError.status/code/detail` (3 → 6–8, тесты 7–8 читают `code`);
  `module_service.list_modules/set_module` (4 → 8); `membership_service.
  list_memberships/revoke_membership/grant_membership` (5 → 8); `companiesApi`
  (9 → 10–13); `COMPANY_KIND_LABELS` (9 → 11–12); `CompanyTreeNode.children`
  (6 → 9, 11); пути `companies/tree` до `companies/<slug>` (6).
