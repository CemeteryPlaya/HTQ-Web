# Хвосты рефакторинга структуры группы (блок K) — план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** закрыть то, что итоговая сверка рефакторинга оставила открытым в зоне
этой ветки: немые бизнес-метрики tenant-аппок, «сегодня», зависящее от часового
пояса, необёрнутый `UnknownRole`, два давних красных теста, непереведённые
экраны прав, три известных обхода сторожа гейтов и устаревшие комментарии.

**Architecture:** сборщик `apps/core/metrics.py` обходит действующие компании
со схемой и размечает серии tenant-аппок меткой `company` (слаг); дашборды
сводят их `sum/max without (company)` с переменной «Компания», правила держат
компанию в серии. «Сегодня» на платформе одно — `timezone.localdate()`,
сторож на `ast` не пускает `date.today()`/`now().date()`. Остальное — точечные
правки с тестами.

**Tech Stack:** Django 5.2.7, pytest-django на Postgres `:55432`, Grafana 10.4
provisioning (JSON/YAML), React + i18next, vitest.

**Spec:** [2026-09-23-group-structure-verification.md](2026-09-23-group-structure-verification.md)
§6.4 и §7, [roadmap §9.2](2026-09-14-group-structure-roadmap.md#92-сознательно-оставлено-не-ошибки-а-известные-границы),
[followups п. 3 и «Побочная находка»](../multi-company-tenancy-followups.md).
Решения заказчика 24.09.2026: метрики — **меткой `company`** (не суммой по
группе); в веер — **все четыре** tenant-аппки, включая `contracts`/`signoff`
(их файлы не правятся, меняется только сборщик в `core`).

**Не входит (отдельными спеками и планами):** гейт `api_view(module=…)` на
семь оставшихся аппок (`approvals`, `cms`, `conference`, `core`, `mail`,
`media_files`, `messenger`) и архив компании «только чтение» (подпроект 4) —
у обоих свои проектные решения (узлы реестра и роли; кто читает архив и что
делает фронт), ошибка в первом закрывает почту и мессенджер всем сотрудникам.

## Global Constraints

- Зона второго разработчика не правится: `backend/apps/contracts/**`, `backend/apps/signoff/**`, `frontend/src/pages/{contracts,signoff}/**` — их `metrics.py` только вызываются сборщиком.
- Ветки/worktree не создавать; работать в `sanzhar`; `git add` поимённо, никогда `git add -A`/`.`; `git stash` не использовать; не стейджить `.codebase-memory/`, `.cursor/`, `.zed/`, `.github/copilot-instructions.md`, `.github/instructions/`.
- pytest — только в форграунде, параметр Bash `timeout: 600000`, одна сессия за раз (общая тестовая БД), `run_in_background` для pytest запрещён; из `backend/`: `../.venv/Scripts/python.exe -m pytest …`; Postgres: `docker compose -f docker-compose.test-local.yml up -d db` из корня.
- Межаппное — только через `apps.<x>.interface` (сторож `apps/core/tests/test_app_isolation.py`); `apps.core` вправе звать `apps.companies.interface`.
- Новая подмена — только `htqweb.fallback.fallback("<аппка>.<модуль>.<что>", …)`, `site` — статический литерал.
- Имена метрик без цифр (`htqweb_[a-z_]+`); метка компании называется ровно `company`, значение — слаг компании (не псевдоним поддомена).
- Коммиты на русском, в конце строка `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; не пушить.
- Фронт: `npx tsc --noEmit -p tsconfig.json` не хуже базы 148 ошибок; `npx vitest run` — известные 8 падений не больше.

## Review Focus

- Компания есть в реестре, а схемы `co_<slug>` нет (стенд до `tenancy_bootstrap`, осиротевшая строка) — `search_path` проваливается в `public`, и без проверки каждая такая «компания» отдала бы цифры `public` под своим именем; ожидание — компания пропущена с `logger.info`, цифры не дублируются. Тест — задача 1, `test_company_without_schema_is_skipped_not_duplicated`.
- `collect()` tenant-аппки падает в ОДНОЙ компании на проде (`FALLBACK_MODE=log`) — ожидание: остальные компании и остальные аппки собраны, строка `FALLBACK` в логе; в strict — `FallbackNotAllowed`. Тесты — задача 1.
- Архивная компания — её серии исчезают из метрик с первого сбора после архивации. Тест — задача 1, `test_archived_company_is_not_collected`.
- Дашборд с переменной «Компания» = All — панель показывает одну цифру по группе, как до блока, а не по серии на компанию; правило с агрегацией не теряет компанию. Тесты — задача 2 (сторож формы).
- Граница суток в поясе платформы ≠ UTC (21:30 UTC = 02:30 следующего дня в Алматы) — запись и чтение «сегодня» видят один день при любом `TIME_ZONE`. Тесты — задача 3, параметризация `UTC`/`Asia/Almaty` на закреплённых часах.

---

### Task 1: Сбор метрик tenant-аппок веером по компаниям

**Files:**
- Modify: `backend/apps/core/metrics.py` (докстринг модуля строки 29–48; `_metric_modules` 85–123; `collect_all` 146–166)
- Modify: `backend/apps/core/tests/test_metrics.py` (заменить `test_tenant_apps_are_not_collected` и `test_tenant_apps_are_skipped_without_calling_collect`; поправить комментарий в `test_business_metrics_are_discovered_across_apps`)
- Modify: `backend/apps/core/tests/test_metrics_are_observed.py` (удалить `_BLOCKED_ON_TENANT_FANOUT` и комментарий над ним, строки 99–132; оба теста «код ↔ инфра» — на фикстуре `company_schema`)

**Interfaces:**
- Produces: `apps.core.metrics.COMPANY_LABEL = "company"`; снимок `collect_all()` для tenant-аппки — `{"<имя>": {"help": str|None, "labels": ["company", *свои], "values": [((slug, *свои_значения), число), ...]}}`. Задача 2 опирается на `COMPANY_LABEL` и на то, что каждая метрика tenant-аппки несёт `company` первой меткой.
- Consumes: `apps.companies.interface.active_company_slugs()`, `apps.companies.interface.schema_exists(slug)`, `htqweb.tenancy.db.use_company(slug)`; фикстуры `two_company_schemas`, `company_row`, `company_schema`, `fallback_log_mode` из `backend/conftest.py`.

- [ ] **Step 1: Написать падающие тесты** — в `backend/apps/core/tests/test_metrics.py` удалить `test_tenant_apps_are_not_collected` и `test_tenant_apps_are_skipped_without_calling_collect` целиком и вставить на их место:

```python
def _hr_employee(slug: str, *, user_id=None) -> None:
    """Сотрудник в схеме компании ``slug`` (минимальный набор полей)."""
    import datetime as dt

    from apps.hr.models import Department, Employee, Position
    from htqweb.tenancy.db import use_company

    with use_company(slug):
        dep = Department.objects.create(name="Отдел", path="otdel")
        pos = Position.objects.create(title="Инженер", department=dep, weight=300)
        Employee.objects.create(
            first_name="Т", last_name="Тестов", email=f"t@{slug}.test",
            department=dep, position=pos, hire_date=dt.date(2024, 1, 9),
            user_id=user_id,
        )


def _by_company(collected: dict, app: str, name: str) -> dict:
    """``{slug: сумма по сериям}`` одной метрики tenant-аппки."""
    spec = collected[app][name]
    assert spec["labels"][0] == "company"
    out: dict = {}
    for labels, number in spec["values"]:
        out[labels[0]] = out.get(labels[0], 0) + number
    return out


@pytest.mark.django_db
def test_tenant_apps_without_companies_export_nothing():
    """Компаний нет — tenant-метрик нет вовсе (а не нули): «не из чего
    считать» и «ноль» обязаны выглядеть по-разному."""
    from django.conf import settings

    from apps.core import metrics as business

    collected = business.collect_all()
    assert set(settings.TENANT_APPS) & set(collected) == set()


def test_tenant_metrics_are_collected_per_company_with_a_company_label(two_company_schemas):
    """Веер: collect() каждой tenant-аппки зовётся в схеме КАЖДОЙ компании,
    серия несёт слаг первой меткой, цифры одной компании не видны в другой."""
    from django.conf import settings

    from apps.core import metrics as business

    alpha, beta = two_company_schemas
    _hr_employee(alpha)                         # без учётной записи

    collected = business.collect_all()

    assert set(settings.TENANT_APPS) <= set(collected)
    assert _by_company(collected, "hr", "hr_active_without_account") == {alpha: 1, beta: 0}
    assert collected["hr"]["hr_employees"]["labels"] == ["company", "status"]
    assert _by_company(collected, "hr", "hr_employees") == {alpha: 1}
    for app in settings.TENANT_APPS:
        for name, spec in collected[app].items():
            assert spec["labels"][0] == business.COMPANY_LABEL, (app, name)


def test_company_without_schema_is_skipped_not_duplicated(two_company_schemas, company_row):
    """Строка реестра без схемы: search_path в несуществующую схему
    проваливается в public, и без проверки «компания» отдала бы чужие цифры
    под своим именем. Её нет в сериях вовсе."""
    from apps.core import metrics as business

    collected = business.collect_all()
    assert set(_by_company(collected, "hr", "hr_active_without_account")) == set(two_company_schemas)


def test_archived_company_is_not_collected(two_company_schemas):
    from apps.companies.models import Company, CompanyStatus
    from apps.core import metrics as business

    alpha, beta = two_company_schemas
    Company.objects.filter(slug=beta).update(status=CompanyStatus.ARCHIVED)

    collected = business.collect_all()
    assert set(_by_company(collected, "hr", "hr_active_without_account")) == {alpha}


def test_one_failing_company_does_not_take_the_others_down(
        two_company_schemas, monkeypatch, fallback_log_mode):
    from apps.core import metrics as business
    from apps.hr import metrics as hr_metrics
    from htqweb.tenancy.context import current_company

    alpha, beta = two_company_schemas
    real = hr_metrics.collect

    def flaky():
        if current_company() == alpha:
            raise RuntimeError("подсчёт кадров упал")
        return real()

    monkeypatch.setattr(hr_metrics, "collect", flaky)
    collected = business.collect_all()

    assert set(_by_company(collected, "hr", "hr_active_without_account")) == {beta}
    assert "tasks" in collected and "approvals" in collected


def test_a_failing_company_is_loud_for_developers(two_company_schemas, monkeypatch):
    from apps.core import metrics as business
    from apps.hr import metrics as hr_metrics
    from htqweb.fallback import FallbackNotAllowed

    def boom():
        raise RuntimeError("подсчёт кадров упал")

    monkeypatch.setattr(hr_metrics, "collect", boom)
    with pytest.raises(FallbackNotAllowed) as info:
        business.collect_all()
    assert isinstance(info.value.__cause__, RuntimeError)
```

В `test_business_metrics_are_discovered_across_apps` заменить последние строки комментария («Тенантных … см. два теста ниже.») на: `# Тенантных (settings.TENANT_APPS) здесь нет: без компаний со схемой их`
`# сборщик не зовёт — см. test_tenant_apps_without_companies_export_nothing.`

- [ ] **Step 2: Прогнать — убедиться, что падают**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_metrics.py -q -p no:cacheprovider`
Expected: FAIL — `KeyError: 'hr'` в тестах веера (сборщик пропускает tenant-аппки), `AttributeError: … COMPANY_LABEL`.

- [ ] **Step 3: Реализация в `backend/apps/core/metrics.py`**

Докстринг модуля: абзацы «**Тенантные аппки (``settings.TENANT_APPS``) сборщик пропускает явно.** …» и «Полная форма — веер по компаниям …» (строки 29–48) заменить на:

```
**Тенантные аппки (``settings.TENANT_APPS``) собираются веером по компаниям.**
Их ``collect()`` читает модели напрямую, а модели живут в схеме компании
(``co_<slug>``): вне контекста компании запрос ушёл бы в ``public``. Поэтому
сборщик зовёт ``collect()`` tenant-аппки внутри ``use_company(slug)`` для
КАЖДОЙ действующей компании и размечает её серии меткой ``company`` (слаг) —
решение заказчика 24.09.2026: алерт обязан называть компанию. Дашборды сводят
серии ``sum/max without (company)`` с переменной «Компания».

Компания без физической схемы пропускается (``logger.info``, не
``fallback``): ``search_path`` в несуществующую схему молча проваливается в
``public``, и такая «компания» отдала бы цифры ``public`` под своим именем —
на стенде до ``tenancy_bootstrap`` каждая из них. Падение ``collect()`` в
одной компании — ``fallback`` на эту компанию, остальные собираются.
```

Заменить `_metric_modules` и `collect_all` и добавить помощники (константа `COMPANY_LABEL` — сразу под `PREFIX = "htqweb"`):

```python
# Метка компании у серий tenant-аппок. Значение — слаг (не псевдоним
# поддомена): по слагу живут схема, claim токена и роли.
COMPANY_LABEL = "company"


def _metric_modules() -> list[tuple[str, object, bool]]:
    """``[(app_label, модуль metrics, тенантная ли аппка)]`` для аппок,
    которые его объявили.

    Тот же приём автодискавери, что у ``API_PREFIX`` в ``htqweb/urls.py``:
    добавление метрик новой аппке не требует правок здесь.
    """
    found = []
    tenant_apps = set(settings.TENANT_APPS)
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        if config.label == "core":          # свои метрики core не собирает
            continue
        if not module_has_submodule(config.module, "metrics"):
            continue
        module = __import__(f"{config.name}.metrics", fromlist=["metrics"])
        if callable(getattr(module, "collect", None)):
            found.append((config.label, module, config.label in tenant_apps))
            continue
        # Модуль есть, а функции нет — это опечатка в имени или недописанный
        # файл, и молча пропустить его значит потерять метрики целой аппки
        # без единого следа.
        fallback("core.metrics.module_without_collect", None,
                 reason="apps/<домен>/metrics.py без функции collect()",
                 app=config.label)
    return found


def _metric_companies() -> list[str]:
    """Слаги действующих компаний, у которых есть схема (см. докстринг модуля)."""
    from apps.companies.interface import active_company_slugs, schema_exists

    slugs = []
    for slug in active_company_slugs():
        if schema_exists(slug):
            slugs.append(slug)
        else:
            logger.info(
                "business metrics: у компании %r нет схемы — её tenant-метрики "
                "не считаются (штатно до tenancy_bootstrap; после — осиротевшая "
                "строка реестра)", slug,
            )
    return slugs


def _add_company(merged: dict, name: str, spec, slug: str) -> None:
    """Дописать серии одной компании в общую метрику, метка ``company`` — первой."""
    if isinstance(spec, (int, float)):
        spec = {"values": [((), spec)]}
    target = merged.setdefault(name, {
        "help": spec.get("help"),
        "labels": [COMPANY_LABEL, *spec.get("labels", [])],
        "values": [],
    })
    target["values"].extend(((slug, *labels), number)
                            for labels, number in spec.get("values", []))


def _collect_tenant(label: str, module, slugs: list[str]) -> dict:
    from htqweb.tenancy.db import use_company

    merged: dict = {}
    for slug in slugs:
        try:
            with use_company(slug):
                values = module.collect()
        except Exception as exc:
            fallback("core.metrics.tenant_collect_failed", None,
                     reason="сбор бизнес-метрик тенантной аппки в компании упал",
                     exc=exc, app=label, company=slug)
            continue
        for name, spec in (values or {}).items():
            _add_company(merged, name, spec, slug)
    return merged


def collect_all() -> dict[str, dict]:
    """Опросить все аппки. Вызывается из Celery-задачи, не из экспорта.

    Падение одной аппки (или одной компании у tenant-аппки) не должно
    уносить метрики остальных: сбор — это диагностика, и «нет ничего,
    потому что в задачах ошибка» — худший из возможных исходов. В строгом
    режиме (машина разработчика, тесты) эта терпимость намеренно снимается —
    ``fallback`` поднимет исключение, и сломанный сборщик будет видно сразу,
    а не по дырке на графике.
    """
    result: dict[str, dict] = {"core": _core_metrics()}
    slugs: list[str] | None = None
    for label, module, tenant in _metric_modules():
        if tenant:
            if slugs is None:
                slugs = _metric_companies()
            values = _collect_tenant(label, module, slugs)
        else:
            try:
                values = module.collect()
            except Exception as exc:
                fallback("core.metrics.app_collect_failed", None,
                         reason="сбор бизнес-метрик аппки упал",
                         exc=exc, app=label)
                continue
        if values:
            result[label] = values
    return result
```

- [ ] **Step 4: Сторож «код ↔ инфра» без исключения для tenant-метрик** — в `backend/apps/core/tests/test_metrics_are_observed.py` удалить блок комментария над `_BLOCKED_ON_TENANT_FANOUT` и сам `_BLOCKED_ON_TENANT_FANOUT` (строки 99–132), убрать `| _BLOCKED_ON_TENANT_FANOUT` из `defined` в `test_every_referenced_metric_exists_in_code`; у обоих тестов `test_every_collected_metric_is_observed` и `test_every_referenced_metric_exists_in_code` заменить `@pytest.mark.django_db` + пустую сигнатуру на параметр фикстуры `company_schema` (компания со схемой — иначе веер ничего не соберёт):

```python
def test_every_collected_metric_is_observed(company_schema):
```

```python
def test_every_referenced_metric_exists_in_code(company_schema):
```

`_CONDITIONAL` не трогать (`daily_report_staleness_days`, `signoff_oldest_pending_seconds` появляются только при данных).

- [ ] **Step 5: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_metrics.py apps/core/tests/test_metrics_are_observed.py apps/core/tests/test_digest.py apps/core/tests/test_app_isolation.py -q -p no:cacheprovider`
Expected: PASS. Если `test_every_collected_metric_is_observed` краснеет на метрике tenant-аппки — это реальная находка (метрика считается, но не нарисована): записать в отчёт, не добавлять в `_KNOWN_UNOBSERVED` молча.

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/core/metrics.py backend/apps/core/tests/test_metrics.py backend/apps/core/tests/test_metrics_are_observed.py
git commit -m "feat(metrics): метрики tenant-аппок собираются веером по компаниям с меткой company"
```

---

### Task 2: Дашборды, правила и уведомления под метку `company`

**Files:**
- Modify: `infra/logging/grafana-dashboards/htqweb-business.json` (`templating.list`; `expr` строк 78, 310, 410, 419, 580)
- Modify: `infra/logging/grafana-dashboards/htqweb-domains.json` (`templating.list`; `expr` строк 87, 143, 185, 237, 285, 334, 404, 448, 500, 548, 618, 660, 712)
- Modify: `infra/logging/grafana-provisioning/alerting/rules.yml` (`expr` правил `htqweb-contracts-awaiting-accounting` ~строка 1708 и `htqweb-signoff-pending-stale` ~строка 1754)
- Modify: `infra/logging/grafana-provisioning/alerting/templates.yml` (шаблоны `htqweb.incident`/`htqweb.business` — строка компании)
- Modify: `backend/apps/core/tests/test_metrics_are_observed.py` (два новых сторожа формы)

**Interfaces:**
- Consumes: `apps.core.metrics.COMPANY_LABEL`, метка `company` первой у каждой метрики tenant-аппки (задача 1).

- [ ] **Step 1: Падающие сторожа формы** — в конец `backend/apps/core/tests/test_metrics_are_observed.py`:

```python
def _tenant_metric_names() -> set[str]:
    """Метрики, которые сборщик размечает компанией (веер tenant-аппок)."""
    return {
        PREFIX + name
        for app_values in metrics.collect_all().values()
        for name, spec in app_values.items()
        if isinstance(spec, dict) and metrics.COMPANY_LABEL in spec.get("labels", [])
    }


def _dashboard_targets():
    """(файл, dashboard, заголовок панели, expr) по всем панелям, включая вложенные."""
    for path in sorted(DASHBOARDS.glob("*.json")):
        dash = json.loads(path.read_text(encoding="utf-8"))

        def walk(panels):
            for panel in panels:
                for target in panel.get("targets") or []:
                    if target.get("expr"):
                        yield path.name, dash, panel.get("title", "?"), target["expr"]
                yield from walk(panel.get("panels") or [])

        yield from walk(dash.get("panels") or [])


_COMPANY_FILTER = r'\{[^}]*company=~"\$company"'
_FOLDED = re.compile(r"\b(sum|max|min|avg)\s+without\s*\(\s*company\s*\)")


def test_tenant_metrics_on_dashboards_follow_the_company_variable(company_schema):
    """Панель tenant-метрики фильтрует по переменной «Компания» и сводит
    компании в одну цифру: при «All» — число по группе, как до веера, а не
    по серии на компанию."""
    _skip_without_infra()
    tenant = _tenant_metric_names()
    assert tenant, "веер не собрал ни одной tenant-метрики — сломан сам сбор"

    bad = []
    for file, dash, title, expr in _dashboard_targets():
        names = set(_METRIC_RE.findall(expr)) & tenant
        if not names:
            continue
        variables = {v.get("name") for v in dash.get("templating", {}).get("list", [])}
        if "company" not in variables:
            bad.append(f"{file}: нет переменной company, а панель «{title}» её требует")
        for name in sorted(names):
            if not re.search(re.escape(name) + _COMPANY_FILTER, expr):
                bad.append(f'{file} «{title}»: {name} без {{company=~"$company"}}')
        if not _FOLDED.search(expr):
            bad.append(f"{file} «{title}»: не сведено sum/max without (company)")
    assert bad == [], bad


_AGGREGATION = re.compile(r"\b(sum|max|min|avg|count)\b")
_BY = re.compile(r"\bby\s*\(([^)]*)\)")


def test_alert_rules_keep_the_company_of_tenant_metrics(company_schema):
    """Правило на tenant-метрике либо не агрегирует вовсе (серия на
    компанию), либо агрегирует ``by (company, …)`` — иначе уведомление не
    назовёт компанию, ради чего метка и заведена."""
    _skip_without_infra()
    yaml = pytest.importorskip("yaml")
    tenant = _tenant_metric_names()

    bad = []
    for group in yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]:
        for rule in group["rules"]:
            for query in rule.get("data") or []:
                expr = (query.get("model") or {}).get("expr") or ""
                if not set(_METRIC_RE.findall(expr)) & tenant:
                    continue
                if _AGGREGATION.search(expr) and not any(
                    "company" in [part.strip() for part in by.split(",")]
                    for by in _BY.findall(expr)
                ):
                    bad.append(f"{rule['uid']}: {expr}")
    assert bad == [], bad
```

- [ ] **Step 2: Прогнать — падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_metrics_are_observed.py -q -p no:cacheprovider`
Expected: FAIL — 18 панелей без фильтра/свёртки и без переменной; 2 правила (`htqweb-contracts-awaiting-accounting`, `htqweb-signoff-pending-stale`).

- [ ] **Step 3: Переменная «Компания»** — в ОБОИХ дашбордах `"templating": {"list": []}` заменить на:

```json
  "templating": {
    "list": [
      {
        "name": "company",
        "label": "Компания",
        "type": "query",
        "datasource": { "type": "prometheus", "uid": "prometheus" },
        "definition": "label_values(htqweb_hr_terminated_still_active, company)",
        "query": { "query": "label_values(htqweb_hr_terminated_still_active, company)", "refId": "company" },
        "refresh": 2,
        "includeAll": true,
        "multi": true,
        "allValue": ".*",
        "current": { "selected": true, "text": ["All"], "value": ["$__all"] },
        "sort": 1
      }
    ]
  },
```

(`hr_terminated_still_active` — серия без своих меток, есть у каждой компании со схемой, даже с нулём.)

- [ ] **Step 4: Переписать 18 выражений.** Правило одно: `M` → `sum without (company) (M{company=~"$company"})`; две метрики «самое старое» — `max`, не `sum`. В JSON кавычки экранируются:

| Файл:строка | Было | Стало |
|---|---|---|
| business.json:78 | `htqweb_tasks_overdue` | `sum without (company) (htqweb_tasks_overdue{company=~\"$company\"})` |
| business.json:310 | `htqweb_tasks` | `sum without (company) (htqweb_tasks{company=~\"$company\"})` |
| business.json:410 | `htqweb_daily_reports_today` | `sum without (company) (htqweb_daily_reports_today{company=~\"$company\"})` |
| business.json:419 | `htqweb_daily_report_staleness_days` | `max without (company) (htqweb_daily_report_staleness_days{company=~\"$company\"})` |
| business.json:580 | `htqweb_projects_active` | `sum without (company) (htqweb_projects_active{company=~\"$company\"})` |
| domains.json:87 | `htqweb_contracts_signoff_desync` | `sum without (company) (htqweb_contracts_signoff_desync{company=~\"$company\"})` |
| domains.json:143 | `htqweb_contracts_budget_lines_overspent` | `sum without (company) (htqweb_contracts_budget_lines_overspent{company=~\"$company\"})` |
| domains.json:185 | `htqweb_contracts_accountable_funds_outstanding` | `sum without (company) (htqweb_contracts_accountable_funds_outstanding{company=~\"$company\"})` |
| domains.json:237 | `htqweb_contracts_agreements` | `sum without (company) (htqweb_contracts_agreements{company=~\"$company\"})` |
| domains.json:285 | `htqweb_contracts_awaiting_accounting` | `sum without (company) (htqweb_contracts_awaiting_accounting{company=~\"$company\"})` |
| domains.json:334 | `htqweb_contracts_awaiting_accounting_amount` | `sum without (company) (htqweb_contracts_awaiting_accounting_amount{company=~\"$company\"})` |
| domains.json:404 | `htqweb_signoff_routes_without_approvers` | `sum without (company) (htqweb_signoff_routes_without_approvers{company=~\"$company\"})` |
| domains.json:448 | `htqweb_signoff_oldest_pending_seconds` | `max without (company) (htqweb_signoff_oldest_pending_seconds{company=~\"$company\"})` |
| domains.json:500 | `htqweb_signoff_processes` | `sum without (company) (htqweb_signoff_processes{company=~\"$company\"})` |
| domains.json:548 | `htqweb_signoff_pending_stale` | `sum without (company) (htqweb_signoff_pending_stale{company=~\"$company\"})` |
| domains.json:618 | `htqweb_hr_terminated_still_active` | `sum without (company) (htqweb_hr_terminated_still_active{company=~\"$company\"})` |
| domains.json:660 | `htqweb_hr_active_without_account` | `sum without (company) (htqweb_hr_active_without_account{company=~\"$company\"})` |
| domains.json:712 | `htqweb_hr_employees` | `sum without (company) (htqweb_hr_employees{company=~\"$company\"})` |

Номера строк — на коммит `4bb2df9`; перед правкой сверить `grep -n '"expr"' infra/logging/grafana-dashboards/htqweb-*.json`. `legendFormat` панелей, если ссылаются на `{{company}}`, не нужны — компания свёрнута.

- [ ] **Step 5: Два правила** — в `infra/logging/grafana-provisioning/alerting/rules.yml`:
  - `expr: 'sum(htqweb_contracts_awaiting_accounting)'` → `expr: 'sum by (company) (htqweb_contracts_awaiting_accounting)'`
  - `expr: 'sum by (subject_type) (htqweb_signoff_pending_stale)'` → `expr: 'sum by (company, subject_type) (htqweb_signoff_pending_stale)'`

  Четыре правила без агрегации (`htqweb_contracts_signoff_desync`, `htqweb_contracts_budget_lines_overspent`, `htqweb_hr_terminated_still_active`, `htqweb_signoff_routes_without_approvers`) не трогать: серия на компанию уже даёт экземпляр алерта на компанию.

- [ ] **Step 6: Компания в уведомлении** — в `infra/logging/grafana-provisioning/alerting/templates.yml` в ОБОИХ шаблонах (`htqweb.incident` и `htqweb.business`) внутри `{{ range .Alerts }}` сразу после строки `{{ .Annotations.summary }}` вставить:

```
      {{- if .Labels.company }}
      Компания: {{ .Labels.company }}{{ end }}
```

- [ ] **Step 7: Прогнать сторожа и проверку конфигов**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_metrics_are_observed.py -q -p no:cacheprovider` — Expected: PASS.
Run (из корня, Bash): `./scripts/check-monitoring-config.sh` — Expected: все проверки OK (Grafana поднимается на провижининге, JSON валиден). Требует docker; если Docker Desktop выключен — запустить `"C:\Program Files\Docker\Docker\Docker Desktop.exe"` и повторить.

- [ ] **Step 8: Документы** —
  - `CLAUDE.md`, раздел Observability: абзац от «⚠️ **Having a `metrics.py` is not the same as being collected:**» до «Open item — [docs/multi-company-tenancy-followups.md](docs/multi-company-tenancy-followups.md), п. 3.» заменить на: «**Tenant apps are collected per company.** `_metric_modules()` marks `settings.TENANT_APPS` (`hr`, `tasks`, `contracts`, `signoff`), and `collect_all()` calls their `collect()` inside `use_company(slug)` for every active company that has a schema, labelling each series `company=<slug>` (a company without a schema is skipped with a `logger.info` — `search_path` into a missing schema falls through to `public` and would duplicate its numbers). Dashboards fold them with `sum/max without (company)` under a «Компания» variable; the six rules on them keep the company (no aggregation, or `by (company, …)`), and the notification templates print it. Guards: `test_tenant_metrics_on_dashboards_follow_the_company_variable`, `test_alert_rules_keep_the_company_of_tenant_metrics`.»
  - `docs/multi-company-tenancy-followups.md`: заголовок п. 3 → `### 3. Бизнес-метрики tenant-аппок после переноса данных — ЗАКРЫТО блоком K`; в начало раздела абзац «**Состояние на <дата коммита> — закрыто** (блок K, коммиты задач 1–2): веер по компаниям с меткой `company`, решение заказчика 24.09.2026 — метка, а не сумма по группе.»; прежний абзац «Состояние на 23.09.2026 …» оставить ниже как историю.
  - `docs/plans/2026-09-14-group-structure-roadmap.md` §10: абзац «Открыто без хозяина — бизнес-метрики tenant-аппок …» заменить на «Бизнес-метрики tenant-аппок — закрыто блоком K ([план](2026-09-24-post-refactoring-leftovers.md)): веер по компаниям с меткой `company`.»

- [ ] **Step 9: Коммит**

```bash
git add infra/logging/grafana-dashboards/htqweb-business.json infra/logging/grafana-dashboards/htqweb-domains.json infra/logging/grafana-provisioning/alerting/rules.yml infra/logging/grafana-provisioning/alerting/templates.yml backend/apps/core/tests/test_metrics_are_observed.py CLAUDE.md docs/multi-company-tenancy-followups.md docs/plans/2026-09-14-group-structure-roadmap.md
git commit -m "feat(monitoring): дашборды и правила tenant-метрик — переменная и метка company"
```

---

### Task 3: «Сегодня» на платформе — одна точка, `timezone.localdate()`

**Files:**
- Create: `backend/apps/core/tests/test_platform_today.py`
- Modify: `backend/conftest.py` (фикстура `pinned_clock` — после `fallback_log_mode`)
- Modify (код): `backend/apps/approvals/views.py:551,576,734`; `backend/apps/tasks/views.py:2076,2090,2110,2154`; `backend/apps/tasks/tasks.py:73`; `backend/apps/tasks/services/task_service.py:738`; `backend/apps/tasks/management/commands/seed_tasks_demo.py:97`; `backend/apps/hr/services/pmo_service.py:164,214,227,254,257,290,308,315,327`; `backend/apps/hr/services/org_service.py:292,355`; `backend/apps/hr/services/recruitment_service.py:137`; `backend/apps/hr/views.py:1834`; `backend/apps/hr/interface.py:458`; `backend/apps/hr/management/commands/seed_hr_demo.py:447`
- Modify (тесты): `backend/apps/tasks/tests/test_interface_conference.py`; `backend/apps/tasks/tests/test_daily_reports_api.py:355-359`; `backend/apps/tasks/tests/test_project_staff_reports_api.py:448-456`; `backend/apps/approvals/tests/test_stats_api.py`; плюс все `date.today()`/`now().date()` в `backend/apps/tasks/tests/{test_seed_tasks_demo,test_tasks_background,test_sites_api}.py` и `backend/apps/hr/tests/{test_time_api,test_recruiting_api,test_pmo_api,test_org_api,test_interface_substitutes}.py`

**Interfaces:**
- Produces: фикстура `pinned_clock(moment: datetime, tz: str) -> datetime` в `backend/conftest.py`.

Почему: сводка согласований пишет день `timezone.localdate(finalized_at)` (`apps/approvals/services/stats_rollup.py:46`), а ручки статистики читают «сегодня» как `timezone.now().date()` — UTC; ручки `tasks` и `hr` местами берут дату ХОСТА (`date.today()`). Пока `TIME_ZONE="UTC"` и хост в UTC, это совпадает; стоит поясу платформы отличаться — 4 теста падают (прогон 24.09.2026 при `Asia/Almaty`), а два теста досок падают каждую ночь с 00:00 до 05:00 по Алматы (followups, «Побочная находка»).

- [ ] **Step 1: Фикстура закреплённых часов** — в `backend/conftest.py` после `fallback_log_mode`:

```python
# Часы платформы, закреплённые на моменте, и её пояс. Нужны тестам границы
# суток: «сегодня» в поясе платформы и «сегодня» в UTC расходятся несколько
# часов в сутки, и без закрепления такой тест краснеет только ночью.
# Подменяется django.utils.timezone.now — через него идут timezone.localdate(),
# auto_now-поля и сервисы; JWT считает время сам (datetime.now), поэтому
# выданные токены остаются действительными.
@pytest.fixture
def pinned_clock(settings, monkeypatch):
    from django.utils import timezone as dj_timezone

    def pin(moment, tz: str):
        settings.TIME_ZONE = tz
        monkeypatch.setattr(dj_timezone, "now", lambda: moment)
        return moment

    return pin
```

- [ ] **Step 2: Падающий сторож** — `backend/apps/core/tests/test_platform_today.py`:

```python
"""«Сегодня» на платформе одно — ``timezone.localdate()``.

``date.today()`` — дата ХОСТА, ``timezone.now().date()`` — дата UTC, а
записи (сводка согласований, отчёты, доски) датируются днём в поясе
платформы (``TIME_ZONE``). Пока все три совпадают, смесь не видна; стоит
поясу платформы отличаться — несколько часов в сутки запись и чтение смотрят
в разные дни. Разбор — ``ast``: строки и комментарии не считаются.

Зона второго разработчика (``contracts``, ``signoff``) не сканируется —
правило к ней не применялось и навязывать его не нам. Миграции — история.
"""
import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[3]
_OTHER_DEVELOPER = {"contracts", "signoff"}


def _foreign_dates(text: str):
    """(lineno, форма) для ``date.today()`` и ``<…>.now().date()``."""
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and not node.args):
            continue
        func = node.func
        owner = func.value
        if func.attr == "today" and (
            (isinstance(owner, ast.Name) and owner.id == "date")
            or (isinstance(owner, ast.Attribute) and owner.attr == "date")
        ):
            yield node.lineno, "date.today()"
        elif (func.attr == "date" and isinstance(owner, ast.Call)
              and isinstance(owner.func, ast.Attribute) and owner.func.attr == "now"):
            yield node.lineno, "now().date()"


def _scanned_files():
    for root in (BACKEND / "apps", BACKEND / "htqweb"):
        for path in sorted(root.rglob("*.py")):
            parts = path.relative_to(BACKEND).parts
            if "migrations" in parts:
                continue
            if parts[0] == "apps" and len(parts) > 1 and parts[1] in _OTHER_DEVELOPER:
                continue
            yield path


def test_today_is_taken_in_the_platform_time_zone():
    offenders = [
        f"{path.relative_to(BACKEND).as_posix()}:{lineno} {form}"
        for path in _scanned_files()
        for lineno, form in _foreign_dates(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "«сегодня» берётся не в поясе платформы — замените на "
        "django.utils.timezone.localdate(): %s" % offenders
    )


_SAMPLE = '''
import datetime
import datetime as dt
from datetime import date
from django.utils import timezone

a = date.today()
b = dt.date.today()
c = datetime.date.today()
d = timezone.now().date()
e = timezone.localdate()
f = timezone.now().astimezone(dt.timezone.utc).date()
g = "date.today()"
'''


def test_guard_sees_every_foreign_form():
    assert [form for _lineno, form in _foreign_dates(_SAMPLE)] == [
        "date.today()", "date.today()", "date.today()", "now().date()",
    ]
```

- [ ] **Step 3: Прогнать — сторож падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_platform_today.py -q -p no:cacheprovider`
Expected: FAIL со списком ~27 мест кода и ~17 мест тестов.

- [ ] **Step 4: Падающие тесты границы суток.** Во всех четырёх файлах ниже добавить `from django.utils import timezone`, если его нет, и константу:

```python
# 21:30 UTC — в Алматы уже 02:30 следующего дня: «сегодня» в поясе платформы
# и в UTC здесь разные дни.
BOUNDARY = dt.datetime(2026, 9, 24, 21, 30, tzinfo=dt.timezone.utc)
```

(`backend/apps/approvals/tests/test_stats_api.py` не импортирует `datetime` — добавить `import datetime as dt`.)

`backend/apps/approvals/tests/test_stats_api.py` — новый тест после `test_heatmap_returns_per_day_rows`:

```python
@pytest.mark.parametrize("tz", ["UTC", "Asia/Almaty"])
@pytest.mark.django_db
def test_heatmap_counts_today_at_the_day_boundary(tz, pinned_clock):
    """Сводка датирует решение днём в поясе платформы — тем же днём его
    обязана видеть и тепловая карта, иначе ночью «сегодня» пусто."""
    client = Client()
    _pid, tid = _setup(client, "Stat-HM-TZ")
    pinned_clock(BOUNDARY, tz)
    _submit_approved(client, tid, 100)

    body = client.get(f"{BASE}/stats/heatmap", **auth(admin_token())).json()
    assert [row["date"] for row in body if row["approved"] >= 1] == [
        timezone.localdate().isoformat()]
```

`backend/apps/tasks/tests/test_daily_reports_api.py` — заменить `test_board_defaults_to_today` (строки 354–359, вместе с декоратором) на:

```python
@pytest.mark.parametrize("tz", ["UTC", "Asia/Almaty"])
@pytest.mark.django_db
def test_board_defaults_to_today(task, valy, tz, pinned_clock):
    pinned_clock(BOUNDARY, tz)
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=timezone.localdate(), quantity=15)
    body = Client().get(f"{BASE}/daily-reports/board", **auth()).json()
    assert [r["quantity"] for r in body[0]["reports"]] == [15.0]
```

`backend/apps/tasks/tests/test_project_staff_reports_api.py` — заменить `test_board_defaults_to_today_and_rejects_a_malformed_date` (строки 447–456) на:

```python
@pytest.mark.parametrize("tz", ["UTC", "Asia/Almaty"])
@pytest.mark.django_db
def test_board_defaults_to_today_and_rejects_a_malformed_date(project, block, tz, pinned_clock):
    pinned_clock(BOUNDARY, tz)
    ok = Client().get(f"{BASE}/projects/{project.id}/staff-board",
                      **auth(admin_token()))
    assert ok.status_code == 200
    assert ok.json()["date"] == timezone.localdate().isoformat()

    bad = Client().get(f"{BASE}/projects/{project.id}/staff-board?date=вчера",
                       **auth(admin_token()))
    assert bad.status_code == 422
```

`backend/apps/tasks/tests/test_interface_conference.py` — интерфейс принимает границы МОМЕНТАМИ, и `_day_window` строит сутки в UTC; значит и день брать в UTC (сегодня тесты берут `timezone.localdate()` — день в поясе платформы — и промахиваются на границе). Добавить помощник после `_day_window`:

```python
def _utc_today() -> dt.date:
    """День по UTC — тот же, в котором ``_day_window`` строит сутки."""
    return timezone.now().astimezone(dt.timezone.utc).date()
```

и в `test_user_events_include_invitations_and_own`, `test_admin_sees_every_conference_of_the_day`, `test_events_of_other_days_are_out_of_range` заменить `today = timezone.localdate()` на `today = _utc_today()`, добавить им параметризацию и закрепление первой строкой тела:

```python
@pytest.mark.parametrize("tz", ["UTC", "Asia/Almaty"])
@pytest.mark.django_db
def test_user_events_include_invitations_and_own(tz, pinned_clock):
    pinned_clock(BOUNDARY, tz)
    today = _utc_today()
```

(то же для двух других). `test_cancelled_occurrence_is_hidden` не трогать: `exception_date` — день вхождения в поясе платформы, и `timezone.localdate()` там верен.

- [ ] **Step 5: Прогнать — новые тесты падают при `Asia/Almaty`**

Run: `../.venv/Scripts/python.exe -m pytest apps/approvals/tests/test_stats_api.py apps/tasks/tests/test_daily_reports_api.py apps/tasks/tests/test_project_staff_reports_api.py apps/tasks/tests/test_interface_conference.py -q -p no:cacheprovider`
Expected: FAIL `test_heatmap_counts_today_at_the_day_boundary[Asia/Almaty]` (ручка читает UTC-день). Тесты досок и конференций после правки ТЕСТОВ зелёные — это доказательство, что код их ручек уже верен, а падения были тестовыми.

- [ ] **Step 6: Код — `timezone.localdate()` везде, где сторож показал.** Правило замены:
  - `date.today()` / `dt.date.today()` / `datetime.date.today()` → `timezone.localdate()`;
  - `timezone.now().date()` → `timezone.localdate()`;
  - в файле без `from django.utils import timezone` — добавить импорт; если после замены импорт `date`/`datetime` стал не нужен — убрать (иначе `ruff`/линтер ругается; тип `date` в аннотациях оставить);
  - `seed_tasks_demo.py:97` `TODAY = date.today()` на уровне модуля → `TODAY = timezone.localdate()` (модуль команды импортируется после настройки Django);
  - докстринг `apps/tasks/services/holding_service.py:77-78` и `apps/hr/schemas.py:585` — это текст, сторож их не видит; `schemas.py:585` поправить на «подстановка ``timezone.localdate()`` в вьюхе».
  В тестах из списка Files — то же правило (`dt.date.today()` → `timezone.localdate()`).

- [ ] **Step 7: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_platform_today.py apps/approvals apps/tasks apps/hr -q -p no:cacheprovider`
Expected: PASS, кроме двух известных падений `apps/hr/tests/test_employees_api.py::test_create_employee_with_card_t2_writes_card` и `::test_update_employee_with_card_t2_applies_both` (чинит задача 5). Прогон долгий — одна сессия, форграунд, timeout 600000; при превышении — по одной аппке.

- [ ] **Step 8: Коммит**

```bash
git add backend/conftest.py backend/apps/core/tests/test_platform_today.py <все правленные файлы кода и тестов поимённо>
git commit -m "fix: «сегодня» берётся в поясе платформы — timezone.localdate() и сторож"
```

---

### Task 4: `UnknownRole` при незасеянной базовой роли — внятный ответ

**Files:**
- Modify: `backend/apps/access/interface.py` (реэкспорт `UnknownRole`, `__all__` строка 175)
- Modify: `backend/apps/companies/views.py:288-311` (`CompanyMembershipsView.post`)
- Modify: `backend/apps/companies/management/commands/company_grant.py:84-95`
- Test: `backend/apps/companies/tests/test_api_modules_memberships.py`, `backend/apps/companies/tests/test_company_grant.py`

**Interfaces:**
- Produces: `apps.access.interface.UnknownRole` (тот же класс, что `apps.access.services.errors.UnknownRole`). HTTP-ответ: `503 {"detail": <текст исключения>, "code": "access_not_seeded"}`.

Сегодня единственная HTTP-ручка, создающая членство, отдаёт на это 500 «Internal Server Error», а `company_grant` — голый трейсбек. 503 — потому что это незавершённая выкатка (миграции `access` не применены), а не ошибка клиента; рядом стоит тот же класс отказов `service_disabled`. `tenancy_bootstrap`, `seed_group_demo` и django-admin остаются «громкими» как задумано (`conftest.py`, `test_missing_role_is_loud_and_leaves_no_membership`) — трейсбек в консоли оператора там уместен, а `tenancy_bootstrap` откатывает всё одной транзакцией.

- [ ] **Step 1: Падающие тесты.** В `backend/apps/companies/tests/test_api_modules_memberships.py`:

```python
@pytest.mark.django_db
def test_membership_grant_without_the_basic_role_is_503_not_500(client, company, user):
    """Базовая роль не засеяна (миграции access не применены) — это
    незавершённая выкатка, а не падение сервера: 503 с кодом и причиной,
    членство не создано."""
    Role.objects.filter(code="employee-basic").delete()
    res = post_json(client, f"{BASE}/companies/htq/memberships",
                    {"user_id": user.id}, **auth(superuser_token()))
    assert res.status_code == 503
    assert res.json()["code"] == "access_not_seeded"
    assert "employee-basic" in res.json()["detail"]
    assert not CompanyMembership.objects.filter(company=company, user_id=user.id).exists()
```

В `backend/apps/companies/tests/test_company_grant.py`:

```python
@pytest.mark.django_db
def test_missing_basic_role_is_a_command_error_not_a_traceback(company, active_user):
    from apps.access.models import Role

    Role.objects.filter(code="employee-basic").delete()
    with pytest.raises(CommandError, match="employee-basic"):
        call_command("company_grant", company_slug=company.slug, user=str(active_user.id))
    assert not CompanyMembership.objects.filter(company=company).exists()
```

- [ ] **Step 2: Прогнать — падают** (`500 != 503`; `UnknownRole` вместо `CommandError`).

Run: `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_api_modules_memberships.py apps/companies/tests/test_company_grant.py -q -p no:cacheprovider`

- [ ] **Step 3: Реализация.** `backend/apps/access/interface.py` — к импортам:

```python
from apps.access.services.errors import UnknownRole
```

и `"UnknownRole"` в `__all__` (по алфавиту в списке). В `backend/apps/companies/views.py` импорт `from apps.access.interface import UnknownRole` рядом с `from apps.users.interface import get_user_brief`, а в `CompanyMembershipsView.post` вызов `grant_membership` обернуть:

```python
        try:
            created = membership_service.grant_membership(
                company, data.user_id, is_default=data.is_default,
            )
        except UnknownRole as exc:
            # Базовая роль не засеяна — выкатка не завершена (миграции access),
            # а не ошибка клиента и не падение сервера. Членство откатилось
            # вместе с неудачной выдачей (одна транзакция в grant_membership).
            return JsonResponse({"detail": str(exc), "code": "access_not_seeded"},
                                status=503)
```

`backend/apps/companies/management/commands/company_grant.py` — импорт `from apps.access.interface import UnknownRole, serving_holders` (вместо `serving_holders`), цикл:

```python
        granted = 0
        already = 0
        for user_id in user_ids:
            try:
                created = membership_service.grant_membership(company, user_id)
            except UnknownRole as exc:
                raise CommandError(
                    f"{exc}. Примените миграции access (manage.py migrate_shared) "
                    f"и повторите — уже выданные членства ({granted}) сохранены."
                ) from exc
            if created:
                granted += 1
            else:
                already += 1
```

- [ ] **Step 4: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/companies apps/access/tests/test_basic_role_on_membership.py apps/core/tests/test_app_isolation.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/access/interface.py backend/apps/companies/views.py backend/apps/companies/management/commands/company_grant.py backend/apps/companies/tests/test_api_modules_memberships.py backend/apps/companies/tests/test_company_grant.py
git commit -m "fix(companies): незасеянная базовая роль — 503 access_not_seeded и CommandError вместо 500"
```

---

### Task 5: Два давних падения кадров — тесты под карточку без `certs`

**Files:**
- Modify: `backend/apps/hr/tests/test_employees_api.py:1206-1225`, `:1279-1292`
- Modify: `backend/ci-known-failures.txt` (блок «# hr: карточка сотрудника», 5 строк)

Дефект в тестах, не в коде: секция `card_t2.certs` и поле `EmployeeCard.sro_permit_number` намеренно сняты миграцией `hr/0016_remove_employeecard_certs` (закреплено `test_card_t2_patch_ignores_removed_certs_section` и `test_certs_keys_are_gone`). Первый тест падает на `AttributeError` последней строки, второй — на `DoesNotExist`, потому что в его теле нет ни одной живой секции.

- [ ] **Step 1: Убедиться, что падают**

Run: `../.venv/Scripts/python.exe -m pytest "apps/hr/tests/test_employees_api.py::test_create_employee_with_card_t2_writes_card" "apps/hr/tests/test_employees_api.py::test_update_employee_with_card_t2_applies_both" -q -p no:cacheprovider`
Expected: `2 failed` (`AttributeError: 'EmployeeCard' object has no attribute 'sro_permit_number'`; `EmployeeCard.DoesNotExist`).

- [ ] **Step 2: Исправить тесты.** `test_create_employee_with_card_t2_writes_card` — убрать строку `"certs": {"sro_permit_number": "СРО-11"},` из тела и последнюю строку `assert card.sro_permit_number == "СРО-11"`. `test_update_employee_with_card_t2_applies_both` заменить целиком:

```python
@pytest.mark.django_db
def test_update_employee_with_card_t2_applies_both(admin_auth, hr_dep):
    """Правка сотрудника с секцией Т-2 меняет и сотрудника, и карточку —
    карточка заводится, если её ещё не было."""
    pos = _pos("Инженер-5", hr_dep, weight=314)
    target = _emp(hr_dep, pos, "upd-t2@htq.test", phone="+7700")

    resp = Client().put(
        f"{BASE}/{target.id}/",
        data={"phone": "+77012345678", "card_t2": {"personal": {"citizenship": "KZ"}}},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200, resp.content

    target.refresh_from_db()
    assert target.phone == "+77012345678"
    assert EmployeeCard.objects.get(employee_id=target.id).citizenship == "KZ"
```

- [ ] **Step 3: Прогнать** — та же команда, Expected: `2 passed`.

- [ ] **Step 4: Снять из списка известных падений** — в `backend/ci-known-failures.txt` удалить пять строк блока:

```
# hr: карточка сотрудника
# TODO: EmployeeCard не создаётся при создании/правке сотрудника «с карточкой».
# К signoff отношения не имеет — отдельная задача.
apps/hr/tests/test_employees_api.py::test_create_employee_with_card_t2_writes_card
apps/hr/tests/test_employees_api.py::test_update_employee_with_card_t2_applies_both
```

и, если выше в файле названо число известных падений («восемь»), исправить на шесть. В `CLAUDE.md` фразу «**Eight tests fail for reasons that predate CI** (signoff quorum, contracts budget maths — …; hr employee cards)» заменить на «**Six tests fail for reasons that predate CI** (signoff quorum, contracts budget maths — …)», убрав «; hr employee cards».

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/tests/test_employees_api.py backend/ci-known-failures.txt CLAUDE.md
git commit -m "test(hr): карточка Т-2 без снятой секции certs — два давних падения закрыты"
```

---

### Task 6: Переводы экранов прав `access.*`

**Files:**
- Modify: `frontend/public/locales/ru/translation.json` (объект `access`, строки ~4909–4911)
- Modify: `frontend/public/locales/en/translation.json` (объект `access`, строки ~4902–4904)
- Modify: `frontend/src/pages/access/RoleCatalog.tsx:365` (ключ `access.catalog.save` → `access.catalog.savePermissions`)
- Modify: `frontend/src/lib/i18n/__tests__/translationKeys.test.ts` (новый сторож)

Сегодня 97 вызовов `t('access.…')` в 10 файлах (78 уникальных ключей) показывают запасной текст из кода: в словарях есть только `access.companyBadge`, а сторож ключей пропускает вызовы с запасным текстом. Один ключ — `access.catalog.save` — обслуживает две разные кнопки с разным текстом («Сохранить права» в каталоге и «Сохранить» в диалоге), его нужно развести.

- [ ] **Step 1: Падающий сторож** — в `translationKeys.test.ts` после функции `collectUsedKeys` добавить:

```typescript
/** Экраны, чьи ключи обязаны быть в словаре даже с запасным текстом в коде:
 *  запасной текст — только русский, и в английском интерфейсе он всплыл бы
 *  как есть. Список расширяется по мере перевода экранов. */
const STRICT_PREFIXES = ['access.'];

function collectStrictKeys(): Array<{ key: string; where: string }> {
  const used: Array<{ key: string; where: string }> = [];
  for (const file of sourceFiles(SRC)) {
    const text = fs.readFileSync(file, 'utf-8');
    const rel = path.relative(FRONTEND, file).split(path.sep).join('/');
    const lineOf = (idx: number) => text.slice(0, idx).split('\n').length;
    for (const m of text.matchAll(T_CALL)) {
      const key = m[2];
      if (!KEYISH.test(key) || !STRICT_PREFIXES.some((p) => key.startsWith(p))) continue;
      used.push({ key, where: rel + ':' + lineOf(m.index ?? 0) });
    }
  }
  return used;
}
```

и в конец файла:

```typescript
describe('i18n: переведённые экраны не держатся на запасном тексте', () => {
  const ru = loadLocale('ru');
  const en = loadLocale('en');
  const strict = collectStrictKeys();

  it('находит ключи экранов прав', () => {
    expect(strict.length).toBeGreaterThan(90);
  });

  it('каждый ключ access.* есть и в ru, и в en', () => {
    const missing = strict
      .filter(({ key }) => !present(key, ru) || !present(key, en))
      .map(({ key, where }) => `${where}  ${key}`);
    expect([...new Set(missing)].sort()).toEqual([]);
  });
});
```

- [ ] **Step 2: Прогнать — падает**

Run (из `frontend/`): `npx vitest run src/lib/i18n/__tests__/translationKeys.test.ts`
Expected: FAIL — ~77 ключей отсутствуют.

- [ ] **Step 3: Развести ключ кнопки** — `frontend/src/pages/access/RoleCatalog.tsx:365`: `t('access.catalog.save', 'Сохранить права')` → `t('access.catalog.savePermissions', 'Сохранить права')`. `RoleFormDialog.tsx:128` оставляет `access.catalog.save` («Сохранить»).

- [ ] **Step 4: Словари.** В `ru/translation.json` объект `"access": { "companyBadge": … }` заменить на (русские тексты — дословно запасные тексты из кода):

```json
  "access": {
    "companyBadge": "Компания: {{company}}",
    "catalog": {
      "created": "Роль создана",
      "codeTaken": "Код роли уже занят — он уникален на всей платформе",
      "saveFailed": "Не удалось сохранить",
      "copied": "Роль скопирована",
      "renamed": "Роль переименована",
      "codeLocked": "Код системной роли менять нельзя: по нему её находят миграции.",
      "deleted": "Роль удалена",
      "inUse": "Роль назначена: должностей — {{positions}}, пользователей — {{users}}. Сначала снимите её, иначе права пропадут у всех сразу.",
      "systemRole": "Служебную роль удалить нельзя",
      "deleteFailed": "Не удалось удалить роль",
      "permissionsSaved": "Права роли сохранены",
      "title": "Каталог ролей",
      "rolesHeader": "Роли",
      "system": "служебная",
      "renameRole": "Переименовать роль",
      "copyRole": "Копировать роль",
      "deleteRole": "Удалить роль",
      "empty": "Ролей пока нет",
      "codePlaceholder": "код, например hr-admin",
      "codeLabel": "Код роли",
      "titlePlaceholder": "название",
      "titleLabel": "Название роли",
      "create": "Создать роль",
      "save": "Сохранить",
      "savePermissions": "Сохранить права",
      "registryUnavailable": "Не удалось загрузить реестр функций — редактировать права нечем.",
      "pickRole": "Выберите роль, чтобы увидеть её права",
      "copyTitle": "{{title}} (копия)",
      "copyDialogTitle": "Копия роли",
      "renameDialogTitle": "Переименовать роль",
      "copyDialogHint": "Права копируются целиком — их можно поправить после.",
      "renameDialogHint": "Права роли не меняются."
    },
    "assignments": {
      "saved": "Личные назначения сохранены",
      "saveFailed": "Не удалось сохранить",
      "title": "Личные назначения",
      "wholeCompany": "вся компания",
      "department": "отдел",
      "remove": "Убрать назначение",
      "empty": "Личных назначений нет — права идут от должности",
      "addRole": "Добавить роль",
      "pickRole": "— выберите роль —",
      "scope": "Область",
      "add": "Добавить",
      "save": "Сохранить"
    },
    "matrix": {
      "noAccess": "нет доступа",
      "functionColumn": "Функция",
      "depthColumn": "Глубина",
      "notSet": "не задано (нет доступа)",
      "inherits": "наследует: {{value}}",
      "allowed": "разрешено",
      "pages": "Страницы сайта",
      "pagesHint": "закрытая страница отменяет всё, что разрешено выше",
      "pageAccess": "Страница",
      "pageUnrestricted": "не ограничена",
      "pageVisible": "видна",
      "pageHidden": "скрыта"
    },
    "positionRoles": {
      "saved": "Роли должности сохранены",
      "saveFailed": "Не удалось сохранить роли",
      "title": "Роли должности",
      "noRoles": "В каталоге пока нет ролей",
      "save": "Сохранить"
    },
    "delete": {
      "title": "Удалить роль",
      "free": "Роль ни у кого не задействована — её можно удалить.",
      "inUse": "Роль задействована. Удалить её можно только после того, как её снимут у всех перечисленных.",
      "person": "Сотрудник",
      "company": "Компания",
      "department": "Отдел",
      "position": "Должность",
      "personal": "лично",
      "nobody": "Роль никому не выдана",
      "confirm": "Удалить"
    },
    "hierarchy": {
      "youAreHere": "ваша компания",
      "subordinate": "подчинённая",
      "noCompany": "компания не определена",
      "inheritedFrom": "Ваши права в этой компании действуют также от должности в:",
      "switchLabel": "Иерархия должностей",
      "internal": "Внутренняя",
      "external": "Внешняя"
    }
  }
```

В `en/translation.json` — та же структура с английскими текстами:

```json
  "access": {
    "companyBadge": "Company: {{company}}",
    "catalog": {
      "created": "Role created",
      "codeTaken": "This role code is already taken — codes are unique across the platform",
      "saveFailed": "Could not save",
      "copied": "Role copied",
      "renamed": "Role renamed",
      "codeLocked": "A system role's code cannot be changed: migrations look the role up by it.",
      "deleted": "Role deleted",
      "inUse": "The role is assigned: positions — {{positions}}, users — {{users}}. Remove it from them first, otherwise everyone loses these permissions at once.",
      "systemRole": "A system role cannot be deleted",
      "deleteFailed": "Could not delete the role",
      "permissionsSaved": "Role permissions saved",
      "title": "Role catalog",
      "rolesHeader": "Roles",
      "system": "system",
      "renameRole": "Rename role",
      "copyRole": "Copy role",
      "deleteRole": "Delete role",
      "empty": "No roles yet",
      "codePlaceholder": "code, e.g. hr-admin",
      "codeLabel": "Role code",
      "titlePlaceholder": "title",
      "titleLabel": "Role title",
      "create": "Create role",
      "save": "Save",
      "savePermissions": "Save permissions",
      "registryUnavailable": "Could not load the function registry — there is nothing to edit permissions with.",
      "pickRole": "Select a role to see its permissions",
      "copyTitle": "{{title}} (copy)",
      "copyDialogTitle": "Copy of role",
      "renameDialogTitle": "Rename role",
      "copyDialogHint": "Permissions are copied in full — you can adjust them afterwards.",
      "renameDialogHint": "The role's permissions do not change."
    },
    "assignments": {
      "saved": "Personal assignments saved",
      "saveFailed": "Could not save",
      "title": "Personal assignments",
      "wholeCompany": "whole company",
      "department": "department",
      "remove": "Remove assignment",
      "empty": "No personal assignments — permissions come from the position",
      "addRole": "Add role",
      "pickRole": "— select a role —",
      "scope": "Scope",
      "add": "Add",
      "save": "Save"
    },
    "matrix": {
      "noAccess": "no access",
      "functionColumn": "Function",
      "depthColumn": "Depth",
      "notSet": "not set (no access)",
      "inherits": "inherits: {{value}}",
      "allowed": "allowed",
      "pages": "Site pages",
      "pagesHint": "a hidden page overrides everything allowed above",
      "pageAccess": "Page",
      "pageUnrestricted": "unrestricted",
      "pageVisible": "visible",
      "pageHidden": "hidden"
    },
    "positionRoles": {
      "saved": "Position roles saved",
      "saveFailed": "Could not save roles",
      "title": "Position roles",
      "noRoles": "The catalog has no roles yet",
      "save": "Save"
    },
    "delete": {
      "title": "Delete role",
      "free": "The role is not used by anyone — it can be deleted.",
      "inUse": "The role is in use. It can be deleted only after it is removed from everyone listed.",
      "person": "Employee",
      "company": "Company",
      "department": "Department",
      "position": "Position",
      "personal": "personally",
      "nobody": "The role is not assigned to anyone",
      "confirm": "Delete"
    },
    "hierarchy": {
      "youAreHere": "your company",
      "subordinate": "subordinate",
      "noCompany": "company not determined",
      "inheritedFrom": "Your permissions in this company also come from a position in:",
      "switchLabel": "Position hierarchy",
      "internal": "Internal",
      "external": "External"
    }
  }
```

Перед записью сверить список с кодом: `grep -rnoE "t\(\s*['\"]access\.[a-zA-Z.]+" frontend/src` — ключ из кода, которого нет в словаре выше, добавить с его запасным текстом (ru) и переводом (en); сторож шага 1 это и проверит. Сверить, что русские тексты совпадают с запасными текстами в коде дословно.

- [ ] **Step 5: Прогнать**

Run (из `frontend/`): `npx vitest run src/lib/i18n/__tests__/translationKeys.test.ts` — PASS; `npx vitest run` — известных падений не больше 8; `npx tsc --noEmit -p tsconfig.json` — не больше 148 ошибок; `npm run lint` — без новых ошибок.

- [ ] **Step 6: Коммит**

```bash
git add frontend/public/locales/ru/translation.json frontend/public/locales/en/translation.json frontend/src/pages/access/RoleCatalog.tsx frontend/src/lib/i18n/__tests__/translationKeys.test.ts
git commit -m "feat(i18n): переводы экранов прав access.* и сторож без поблажки запасному тексту"
```

---

### Task 7: Сторож гейтов — три известных обхода

**Files:**
- Modify: `backend/apps/access/tests/test_gate.py` (`_view_classes` 559–573, `_iter_undecorated_api_methods` 576–600, `test_every_view_method_of_translated_apps_is_decorated` 437–456, `_factory_call_offenders` 659–680, `_level_offenders` 683–744; новые образцы и сторож `urls.py` в конце файла)

Обходы из roadmap §9.2: (а) база вьюхи под псевдонимом импорта (`ApiView as _Base`) или объявленная в соседнем модуле аппки — `_view_classes` сравнивает только имя базы в том же файле; (б) `level = "none"` в теле фабрики после параметра и `**{"level": "none"}` на вызове фабрики — сторож видит лишь умолчание сигнатуры и именованный аргумент; (в) функция-ручка `hr`/`users`/`tasks` вовсе без `@api_view` — сторож идёт от найденных вызовов `api_view(` и её не видит.

- [ ] **Step 1: Падающие образцы** — в конец `test_gate.py`:

```python
_ALIASED_BASE_SAMPLE = '''
from htqweb.http import ApiView as _Base

class SneakyView(_Base):
    def post(self, request):
        return {}
'''


def test_guard_resolves_an_aliased_view_base():
    found = {name for _lineno, name in _iter_undecorated_api_methods(_ALIASED_BASE_SAMPLE)}
    assert found == {"SneakyView.post"}


_BASE_MODULE_SAMPLE = '''
from htqweb.http import ApiView

class HrApiView(ApiView):
    pass
'''

_VIEWS_ON_FOREIGN_BASE_SAMPLE = '''
from ._base import HrApiView

class ItemView(HrApiView):
    def delete(self, request):
        return {}
'''


def test_guard_follows_a_view_base_from_a_sibling_module():
    roots = _roots_of_sources([_BASE_MODULE_SAMPLE, _VIEWS_ON_FOREIGN_BASE_SAMPLE])
    assert "HrApiView" in roots
    found = {name for _lineno, name in
             _iter_undecorated_api_methods(_VIEWS_ON_FOREIGN_BASE_SAMPLE, roots)}
    assert found == {"ItemView.delete"}


_REASSIGNED_LEVEL_SAMPLE = '''
MODULE = "hr"


def write(method, *, level="write"):
    level = "none"
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     module=MODULE, level=level))


def read(method, *, level="read"):
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     module=MODULE, level=level))


class ItemView(ApiView):
    @read("GET", **{"level": "none"})
    def get(self, request):
        return {}
'''


def test_guard_sees_a_level_hidden_in_the_factory():
    """Уровень, переприсвоенный в теле фабрики, и уровень, пришедший
    распаковкой на её вызове, сторож прочитать не может — нарушение."""
    offenders = {name for _lineno, name, _why in _level_offenders(_REASSIGNED_LEVEL_SAMPLE)}
    assert offenders == {"write", "ItemView.get"}


_URLS_SAMPLE = '''
from django.urls import path
from . import views

urlpatterns = [
    path("gated/", views.gated_handle),
    path("sneaky/", views.sneaky_handle),
    path("items/", views.ItemView.as_view()),
    path("odd/", make_view()),
]
'''

_FUNCTION_VIEWS_SAMPLE = '''
@api_view(methods=("GET",), module="hr", level="read")
def gated_handle(request):
    return {}


def sneaky_handle(request):
    return {}
'''


def test_guard_sees_a_url_view_without_api_view():
    problems = {name for name, _why in _url_view_offenders(_URLS_SAMPLE, _FUNCTION_VIEWS_SAMPLE)}
    assert problems == {"sneaky_handle", "make_view()"}
```

- [ ] **Step 2: Прогнать — падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q -p no:cacheprovider`
Expected: FAIL — `NameError: _roots_of_sources`/`_url_view_offenders`, `found == set()` для псевдонима, offenders без `write`/`ItemView.get`.

- [ ] **Step 3: (а) Псевдонимы и базы соседних модулей.** Заменить `_view_classes` и `_iter_undecorated_api_methods`, добавить `_roots_of_sources`/`_app_view_roots`:

```python
def _view_classes(tree: ast.Module, extra_roots: frozenset[str] = frozenset()) -> list[ast.ClassDef]:
    """Классы файла, унаследованные (прямо или через другой класс файла) от
    корня ``_VIEW_ROOTS`` или от ``extra_roots`` — вьюх, объявленных в
    соседних модулях аппки. Имя, под которым корень импортирован
    (``from htqweb.http import ApiView as _Base``), — тоже корень."""
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    known = set(_VIEW_ROOTS) | set(extra_roots)
    known |= {
        alias.asname
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names if alias.asname and alias.name in known
    }
    views: dict[str, ast.ClassDef] = {}
    changed = True
    while changed:
        changed = False
        for cls in classes:
            if cls.name not in views and any(_base_name(b) in known for b in cls.bases):
                views[cls.name] = cls
                known.add(cls.name)
                changed = True
    return sorted(views.values(), key=lambda cls: cls.lineno)


def _roots_of_sources(sources: list[str]) -> frozenset[str]:
    """Имена классов-вьюх, объявленных в любом из исходников (модули одной
    аппки): база, объявленная в ``_base.py``, — корень и для ``views.py``."""
    trees = [ast.parse(text) for text in sources]
    names: set[str] = set()
    while True:
        found = {cls.name for tree in trees for cls in _view_classes(tree, frozenset(names))}
        if found <= names:
            return frozenset(names)
        names |= found


def _app_modules(app: str) -> list[pathlib.Path]:
    backend = pathlib.Path(__file__).resolve().parents[3]
    return [path for path in sorted((backend / "apps" / app).rglob("*.py"))
            if "tests" not in path.parts and "migrations" not in path.parts]


def _app_view_roots(app: str) -> frozenset[str]:
    return _roots_of_sources([p.read_text(encoding="utf-8") for p in _app_modules(app)])


def _iter_undecorated_api_methods(text: str, extra_roots: frozenset[str] = frozenset()):
    """(lineno, ``Класс.метод``) для каждой ручки класса-вьюхи без гейта-декоратора.

    (Докстринг прежний — перенести без изменений, добавив:) ``extra_roots`` —
    вьюхи из соседних модулей аппки (``_app_view_roots``)."""
    tree = ast.parse(text)
    gate_names = _gate_decorator_names(tree)
    for cls in _view_classes(tree, extra_roots):
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in _HANDLER_METHODS and not any(
                    _is_gate_decorator(d, gate_names) for d in item.decorator_list
                ):
                    yield item.lineno, f"{cls.name}.{item.name}"
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in _HANDLER_METHODS:
                        yield item.lineno, f"{cls.name}.{target.id}"
```

В `test_every_view_method_of_translated_apps_is_decorated` проверять ВСЕ модули аппки (класс-вьюха может жить не только в `views.py`):

```python
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        roots = _app_view_roots(app)
        exempt = self_service.SELF_SERVICE.get(app, {})
        for path in _app_modules(app):
            for lineno, name in _iter_undecorated_api_methods(
                    path.read_text(encoding="utf-8"), roots):
                if name not in exempt:
                    offenders.append(f"{path.relative_to(backend).as_posix()}:{lineno} ({name})")
    assert offenders == [], f"ручка класса-вьюхи без api_view: {offenders}"
```

- [ ] **Step 4: (б) Уровень, спрятанный в фабрике.** В `_level_offenders` сразу после строки `if default is None: … continue` (перед `if default is not _REQUIRED:`) вставить:

```python
        reassigned = next((
            node for node in ast.walk(factory)
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
            and any(isinstance(t, ast.Name) and t.id == level
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target]))
        ), None)
        if reassigned is not None:
            yield start, name, (f"{level} переприсваивается в теле {factory.name} "
                                f"(строка {reassigned.lineno}) — сторож видит только сигнатуру")
            continue
```

В `_factory_call_offenders` первой проверкой тела цикла после фильтра вызова:

```python
        if any(kw.arg is None for kw in call.keywords) or any(
                isinstance(arg, ast.Starred) for arg in call.args):
            yield (call.lineno,
                   _qualified_name(lines, call.lineno, call.end_lineno) or factory.name,
                   f"{factory.name}(…) получает аргументы распаковкой — уровень не прочитать")
            continue
```

- [ ] **Step 5: (в) Сверка с `urls.py`.** Добавить помощник и сторож на реальном коде:

```python
def _url_view_offenders(urls_text: str, views_text: str):
    """(имя, причина) для каждой вьюхи-функции из ``urls.py``, у которой нет
    декоратора с ``api_view``. Классы (``.as_view()``) проверяет сторож
    методов; ``include(...)`` — чужой список путей; всё, что не читается как
    ``views.<имя>`` или голое имя, — нарушение: молча пропущенная форма и
    была бы следующим слепым пятном."""
    views_tree = ast.parse(views_text)
    gate_names = _gate_decorator_names(views_tree)
    functions = {node.name: node for node in views_tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for call in ast.walk(ast.parse(urls_text)):
        if not (isinstance(call, ast.Call) and _base_name(call.func) in {"path", "re_path"}):
            continue
        view = call.args[1] if len(call.args) > 1 else next(
            (kw.value for kw in call.keywords if kw.arg == "view"), None)
        if view is None:
            continue
        if isinstance(view, ast.Call) and _base_name(view.func) in {"as_view", "include"}:
            continue
        if isinstance(view, ast.Attribute) and isinstance(view.value, ast.Name) \
                and view.value.id == "views":
            fn_name = view.attr
        elif isinstance(view, ast.Name):
            fn_name = view.id
        else:
            yield ast.unparse(view), "вьюха задана выражением, которое сторож не читает"
            continue
        fn = functions.get(fn_name)
        if fn is None:
            yield fn_name, "не найдена среди функций views.py"
        elif not any(_is_gate_decorator(d, gate_names) for d in fn.decorator_list):
            yield fn_name, "функция-ручка без декоратора с api_view"


def test_every_url_view_of_translated_apps_carries_api_view():
    """Функция-ручка ``hr``/``users``/``tasks`` вовсе без ``@api_view``
    невидима для сторожа полноты — у неё нет вызова ``api_view(``, который
    он читает. Список ручек даёт ``urls.py``: каждая зарегистрированная
    функция обязана нести декоратор с ``api_view`` (гейт или его отсутствие
    дальше проверяют сторожа выше и реестр самообслуживания)."""
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        urls = backend / "apps" / app / "urls.py"
        views = backend / "apps" / app / "views.py"
        for name, why in _url_view_offenders(urls.read_text(encoding="utf-8"),
                                             views.read_text(encoding="utf-8")):
            offenders.append(f"apps/{app}/urls.py: {name} — {why}")
    assert offenders == [], offenders
```

- [ ] **Step 6: Прогнать**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q -p no:cacheprovider`
Expected: PASS. Если красный сторож на РЕАЛЬНОМ коде (`test_every_url_view_…`, `test_every_view_method_…`, `test_every_module_gate_names_its_level`) — это находка: ручку без `api_view` не исключать молча, а описать в отчёте (путь, имя, что за ручка) и остановиться со статусом DONE_WITH_CONCERNS; если причина — форма `urls.py`, которую помощник честно не читает (например, `views` импортирован под другим именем), дописать её распознавание в `_url_view_offenders` и образец к ней в `_URLS_SAMPLE`.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/access/tests/test_gate.py
git commit -m "test(access): сторож гейтов видит псевдоним базы, уровень в фабрике и ручку без api_view"
```

---

### Task 8: Устаревшие комментарии, документы, итоговый прогон

**Files:**
- Modify: `backend/apps/tasks/views.py:2313-2323` (докстринг `_deny_unless_holding`)
- Modify: `docker-compose.yml:373-375,382` (комментарий `backend-web`)
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` §9.2
- Modify: `docs/multi-company-tenancy-followups.md` (раздел «Побочная находка: два теста падают ночью»)

- [ ] **Step 1: Докстринг** — в `_deny_unless_holding` абзац «Обычная проверка домена (``request.token.is_elevated``) знает только флаги ВЫЗЫВАЮЩЕГО …» заменить на:

```
    Гейт модуля (``api_view(module="tasks", level=…)``) отвечает на вопрос
    «какие права у вызывающего в ЕГО компании» и ничего не знает про ВИД
    этой компании: без этой сверки руководитель дочернего общества с
    управленческим доступом к задачам читал бы проекты, просрочку и
    отчётность соседних компаний группы.
```

- [ ] **Step 2: Комментарий compose** — в `docker-compose.yml` строки

```
  # Единый Django заменил девять FastAPI-микросервисов. migrate + идемпотентный
  # сид админа (admin/admin12345) — ТОЛЬКО backend-web (RUN_MIGRATIONS=1);
  # entrypoint ждёт БД и мигрирует напрямую (DB_HOST=db).
```

заменить на

```
  # Единый Django заменил девять FastAPI-микросервисов. Миграции общих аппок
  # (manage.py migrate_shared) — ТОЛЬКО backend-web и только при RUN_MIGRATIONS=1;
  # сид админа (admin/admin12345), collectstatic и бакеты — отдельно, по
  # RUN_BOOTSTRAP. Схемы компаний доводит manage.py migrate_companies руками.
```

и строку `# Только \`manage.py migrate\`. На боевой БД держим 0 (см. корневой .env).` — на `# Только \`manage.py migrate_shared\`. На боевой БД держим 0 (см. корневой .env).` Сверить с `backend/docker-entrypoint.sh` (строки ~36 и ~51). В `docker-compose.test-env.yml`/`test-local.yml` найти ту же формулировку (`grep -n "RUN_MIGRATIONS=1\|manage.py migrate\b" docker-compose.test-*.yml`) и поправить так же, если она там есть.

- [ ] **Step 3: roadmap §9.2** — пункты «Сторож гейтов», «Базовая роль», «Переводы» пометить «— **закрыто** блоком K ([план](2026-09-24-post-refactoring-leftovers.md), задачи 7, 4, 6)» в конце каждого пункта (текст пункта оставить как историю). В §10 после абзаца про метрики добавить: «Остальные хвосты сверки (даты в поясе платформы, `UnknownRole`, два давних падения кадров, переводы экранов прав, обходы сторожа гейтов, устаревшие комментарии) — закрыты блоком K. Гейт на семь оставшихся аппок и архив «только чтение» — отдельными спеками.»

- [ ] **Step 4: followups** — у раздела «Побочная находка: два теста падают ночью» абзац «**Состояние на 23.09.2026 — не исправлено:** …» заменить на «**Состояние на <дата коммита> — закрыто блоком K (задача 3):** «сегодня» на платформе одно — `timezone.localdate()`, сторож `apps/core/tests/test_platform_today.py`; оба теста досок закреплены на границе суток при `UTC` и `Asia/Almaty`.»

- [ ] **Step 5: Итоговый прогон бэкенда** — полный набор по частям (одна сессия за раз, форграунд, timeout 600000):

```
../.venv/Scripts/python.exe -m pytest apps/core apps/access apps/companies apps/users htqweb -q -p no:cacheprovider
../.venv/Scripts/python.exe -m pytest apps/hr -q -p no:cacheprovider
../.venv/Scripts/python.exe -m pytest apps/tasks -q -p no:cacheprovider
../.venv/Scripts/python.exe -m pytest apps/mail apps/messenger apps/approvals apps/conference apps/cms apps/media_files -q -p no:cacheprovider
../.venv/Scripts/python.exe -m pytest apps/contracts apps/signoff -q -p no:cacheprovider
```

Expected: падают только шесть тестов из `backend/ci-known-failures.txt` (contracts/signoff; бюджетный — порядко-зависимый, может пройти). Любое другое падение — находка, в отчёт. Плюс `../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` (с окружением dev-БД из CLAUDE.md) — «No changes detected».

- [ ] **Step 6: Фронт** — из `frontend/`: `npx tsc --noEmit -p tsconfig.json` (≤ 148), `npx vitest run` (≤ 8 известных), `npm run lint`.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/tasks/views.py docker-compose.yml docs/plans/2026-09-14-group-structure-roadmap.md docs/multi-company-tenancy-followups.md <docker-compose.test-*.yml, если правились>
git commit -m "docs: блок K — устаревшие комментарии и статусы хвостов рефакторинга"
```
