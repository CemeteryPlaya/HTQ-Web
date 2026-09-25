# Блок J — документы и итоговая сверка структурного рефакторинга: план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** привести все документы рефакторинга структуры группы к тому, что
реально построено блоками A–I.2, и проверить, что структурный рефакторинг
выполнен целиком — с доказательствами по каждому требованию руководства.

**Architecture:** блок без кода. Пять задач правят документы (каждая —
свой набор файлов, каждое утверждение сверяется с кодом командой), шестая —
итоговая сверка: трассировка «требование руководства → где реализовано →
чем доказано → статус», полные прогоны тестов и проверка стенда, результат —
отдельный документ. Найденные в сверке расхождения не чинятся в этом блоке, а
записываются с оценкой.

**Tech Stack:** Markdown-документы репозитория; проверки — `grep`, чтение
кода, pytest (бэкенд), vitest/tsc (фронт), Django shell на dev-БД (только
чтение).

**Spec:** [roadmap §5.J](2026-09-14-group-structure-roadmap.md) — «`design.md`,
`stage2-spec §1.6/§7`, `STRUCTURE.md`, `CLAUDE.md` — под новый состав группы и
блоки A–I»; расширено поручением заказчика от 23.09.2026: «запиши всю
документацию, что появилась, и после проверь выполнение всего структурного
рефакторинга».

## Global Constraints

- Документы — по-русски, в стиле соседних абзацев. Не переписывать разделы,
  не относящиеся к рефакторингу структуры группы (блоки A–I.2).
- **Каждое утверждение про файл, функцию, поле, миграцию, команду, ручку,
  код ответа или тест проверяется по репозиторию** (`grep`, чтение). Не
  писать того, чего нет в коде.
- Исторические документы (планы блоков `docs/plans/2026-09-1*-block-*.md`,
  `2026-08-29-stage2-executor-*.md`, спека и план I.2) НЕ переписываются: это
  журнал решений. Меняются только живые документы и пометки «выполнено /
  заменено» в спеках с ссылкой на то, что заменило.
- Ссылки на `.superpowers/…` в отслеживаемых документах недопустимы: каталог
  в `.gitignore` и удаляется по закрытии каждого блока.
- Кода не трогать: `backend/**`, `frontend/**`, `infra/**`, `docker-compose*.yml`.
  Исключение — нет. Расхождение кода с документом, найденное в задаче 6,
  записывается в документ сверки, а не чинится.
- `backend/apps/contracts/**`, `backend/apps/signoff/**`,
  `frontend/src/pages/{contracts,signoff}/**` — зона другого разработчика; их
  состояние описывается только ссылкой на roadmap §6.
- Ветки не создавать, работа в `sanzhar`, пуш — сам пользователь. `git add`
  только поимённо; `git stash` не использовать; не стейджить
  `.codebase-memory/`, `.cursor/`, `.zed/`, `.github/copilot-instructions.md`,
  `.github/instructions/`.
- Трейлер коммита: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- pytest — только форграунд, параметр Bash `timeout: 600000`, одна сессия за
  раз; интерпретатор — корневой `.venv` (`../.venv/Scripts/python.exe` из
  `backend/`).
- Состав группы (из оргструктуры 10.09.2026, roadmap §1): холдинг ТОО «Hi-Tech
  Group LTD» (`hi-tech-group`, псевдоним `group`) и три ДО под ним — ТОО
  «HI-TECH QAZAQSTAN» (`hi-tech-qazaqstan`/`htq`, строительная), ТОО
  «HI-TECH SYSTEMS» (`hi-tech-systems`/`hts`, IT), ТОО «KAZAKHSTAN
  ENGINEERING GROUP» (`kazakhstan-engineering-group`/`keg`, сервисная).
  Старый состав (UZ/KG/КУП/СЭС), если встречается как текущий, — устарел.

## Review Focus

- **Документ говорит «сделано», а кода нет** (или наоборот: «не сделано /
  заглушка / подпроект N», а блок это уже построил) — самый частый дефект
  живых документов; каждое «✅»/«выполнено»/«не делается» должно иметь
  ссылку на файл или тест.
- **Два документа описывают одно и то же по-разному** (например, порядок
  выкатки в roadmap §7, в `docs/deploy/subdomains-runbook.md` и в `CLAUDE.md`;
  правила поддоменов в `multi-company-tenancy-design.md` §6 и в `CLAUDE.md`) —
  расхождение должно быть устранено ссылкой на один источник, а не
  копированием.
- **Битые ссылки** — на удалённые файлы, на `.superpowers/…`, на разделы,
  которых больше нет (`#якоря` после переименования заголовков).
- **Устаревший состав группы** (UZ/KG/КУП/СЭС, «одна компания HTQ» как
  текущее состояние, «Генеральный директор» у ДО).
- **Сверка, которая доверяет документам, а не коду**: задача 6 проверяет
  каждое требование руководства по коду и тестам, а не по тексту roadmap.

---

## Карта файлов

| Файл | Задача | Что происходит |
|---|---|---|
| `docs/plans/2026-09-14-group-structure-roadmap.md` | 1 | шапка, §4, §5.A/§5.J, §5 пункт I.2, итог «состояние на 23.09» |
| `docs/multi-company-tenancy-design.md` | 2 | статусы подпроектов, реестр, маршрутизация с псевдонимами, читатели холдинга, аутентификация поперёк поддоменов |
| `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` §1.6, §7 | 3 | пометки «выполнено блоком …» / «остаётся» |
| `docs/multi-company-tenancy-stage2-design.md` §10, §14 | 3 | то же |
| `docs/multi-company-tenancy-followups.md` | 4 | закрыть 6, 7; сверить остальные с кодом |
| `CLAUDE.md`, `API.md`, `STRUCTURE.md`, `backend/README.md` | 5 | сквозная сверка по блокам A–I.2 |
| `docs/plans/2026-09-23-group-structure-verification.md` (новый) | 6 | итоговая сверка рефакторинга |

Общая команда проверки ссылок (используется в каждой задаче; запуск из корня
репозитория, аргументы — правленые файлы):

```bash
python - "$@" <<'PY'
import pathlib, re, sys
bad = []
for f in sys.argv[1:]:
    p = pathlib.Path(f)
    text = p.read_text(encoding="utf-8")
    for m in re.finditer(r"\]\(([^)\s#]+)(#[^)]*)?\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (p.parent / target).exists():
            bad.append(f"{f}: битая ссылка -> {target}")
    for m in re.finditer(r"\.superpowers/", text):
        line = text.count("\n", 0, m.start()) + 1
        bad.append(f"{f}:{line}: ссылка на .superpowers/")
print("\n".join(bad) if bad else "ссылки: ok")
PY
```

Отдельным файлом её не сохраняй — вставляй блок целиком, подставив пути
вместо `"$@"` (например `python - docs/a.md docs/b.md <<'PY'`).

---

### Task 1: Roadmap — шапка, сводка, статусы блоков

**Files:**
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` (шапка строки 1–14; §4 строки ~79-92; §5.A заголовок ~98; §5.J ~346; конец файла — перед §9 не вставлять, итог — новым §10)

**Interfaces:**
- Produces: актуальный roadmap, на который ссылаются задачи 2–6 («статус блоков — roadmap §4, §10»).

- [ ] **Step 1: Собрать список устаревших утверждений**

```bash
cd /c/Users/User/Desktop/HTQ-Web
sed -n 1,14p docs/plans/2026-09-14-group-structure-roadmap.md
sed -n 79,93p docs/plans/2026-09-14-group-structure-roadmap.md
grep -nE "^### [A-J]\." docs/plans/2026-09-14-group-structure-roadmap.md
```
Известные с начала: шапка — «Ветка: `structure-refactoring`» (работа шла в
`sanzhar`); §4 строка «Реестр компаний» — «нет HTTP-API и экранов
(`apps.companies` без `urls.py`); переключателя компании нет; спека описывает
старый состав группы (UZ/KG/КУП/СЭС)» — блок A построил API и экраны, блок I.2
— поддомены и экран выбора; §5.A без пометки «(выполнено)»; §5.J без пометки;
блока I.2 в §5 нет.

- [ ] **Step 2: Сверить каждое с кодом**

```bash
ls backend/apps/companies/urls.py backend/apps/companies/views.py
grep -n "path(" backend/apps/companies/urls.py | head
ls frontend/src/components/companies/ frontend/src/pages/CompanyPicker.tsx
grep -n "subdomain" backend/apps/companies/models.py | head -3
git log --oneline --all -- backend/apps/companies/urls.py | tail -1
```
Запиши в отчёт, что подтверждено.

- [ ] **Step 3: Правка**

- Шапка: `**Ветка:** \`sanzhar\`` и строка «**Статус на 23.09.2026:** блоки
  A–I, I.2 выполнены; J — этот план; выкатка — §7 и
  [чеклист поддоменов](../deploy/subdomains-runbook.md)».
- §4, строка «Реестр компаний»: «✅ реестр, HTTP-API и экраны (блок A),
  короткие адреса `htq/hts/keg/group`, экран выбора компании на голом домене
  (блок I.2)» / расхождение — только то, что осталось (архив «только чтение»
  не выполнен — `multi-company-tenancy-design.md` §6; сверь, что это так).
- §4: новая строка «Поддомены компаний» — ✅ `Company.subdomain`,
  `companies.interface.resolve_host_label`, `CompanyPicker`; расхождение —
  «выкатка — одним окном с блоком I, чеклист».
- §5.A: «(выполнено)»; §5.J: «(выполнено — план
  [2026-09-23-block-j-docs.md](2026-09-23-block-j-docs.md))».
- §5: после «### I.» добавить «### I.2 Хвосты блока I и поддомены —
  (выполнено)» — три строки: ссылка на спеку и план I.2, что сделано одной
  фразой, отложенное — §9.
- Конец файла: новый «## 10. Итог рефакторинга (23.09.2026)» — пять-семь
  строк: что построено, что передано второму разработчику (§6), что ждёт
  руководство (§8), что сознательно оставлено (§9), где итоговая сверка
  (`docs/plans/2026-09-23-group-structure-verification.md` — появится в
  задаче 6; ссылку поставь сейчас, проверка ссылок в задаче 1 её ещё не
  найдёт — это ожидаемо, отметь в отчёте).

- [ ] **Step 4: Проверка**

Команда проверки ссылок (из «Карты файлов») на `docs/plans/2026-09-14-group-structure-roadmap.md`.
Ожидание: единственная битая ссылка — на ещё не созданный документ сверки.
`grep -nE "structure-refactoring|нет HTTP-API|переключателя компании нет" docs/plans/2026-09-14-group-structure-roadmap.md` — пусто.

- [ ] **Step 5: Коммит**

```bash
git add docs/plans/2026-09-14-group-structure-roadmap.md
git commit -m "docs(roadmap): статус блоков A–I.2, сводка и итог рефакторинга

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Дизайн мультикомпанейности — под то, что построено

**Files:**
- Modify: `docs/multi-company-tenancy-design.md` (§4 таблица подпроектов ~114-130, §5 реестр ~132-167, §6 маршрутизация ~168-209, §7 холдинг ~210-242, §9 аутентификация ~339-352)

- [ ] **Step 1: Список устаревшего**

```bash
cd /c/Users/User/Desktop/HTQ-Web
grep -nE "подпроект|поддомен|архив|пока|не читается|будет|UZ|KG|КУП|СЭС" docs/multi-company-tenancy-design.md
sed -n 112,131p docs/multi-company-tenancy-design.md
```

- [ ] **Step 2: Сверка с кодом (что построено)**

```bash
grep -nE "^\s+[a-z_]+ = models\." backend/apps/companies/models.py
grep -n "def resolve_host_label\|def public_url\|def get_company\|def is_holding" backend/apps/companies/interface.py
grep -n "resolve_host_label" backend/htqweb/middleware/company_context.py
ls backend/apps/hr/holding_models.py backend/apps/tasks/holding_models.py
ls backend/apps/companies/management/commands/ | grep -E "company_(create|archive|restore|grant)"
grep -n "successor" backend/apps/companies/models.py backend/apps/companies/services/lifecycle.py | head
grep -rn "safe method\|SAFE_METHODS\|только чтение" backend/htqweb/middleware/company_context.py | head
```
Отметь в отчёте по каждому подпроекту 2–4 (таблица §4 документа), что
построено и каким блоком (A: реестр/API/экраны; H: читатели холдинга; I.2:
псевдонимы; `CompanyModule` — подпроект 3 — найди, когда появился:
`git log --oneline --diff-filter=A -- backend/apps/companies/models.py` и
`grep -n "class CompanyModule" backend/apps/companies/models.py`), что — нет
(архив «только чтение», банкротство с переносом людей/техники/договоров —
проверь по коду, не по roadmap).

- [ ] **Step 3: Правка**

- В начало документа (после заголовка) — «**Состояние на 23.09.2026**»: что
  из подпроектов 1–4 выполнено каким блоком, со ссылкой на roadmap §4.
- §4 таблица: колонка/пометка статуса у каждого подпроекта.
- §5: поля реестра, которых нет в тексте (`kind`, `parent`, `status`,
  `successor`, `subdomain`, `show_external_holders` — ровно те, что есть в
  модели), одной строкой каждое; ссылка на `CLAUDE.md` раздел
  «Мультикомпанейность».
- §6: абзац «Короткие адреса» — метка хоста → `resolve_host_label` (сначала
  псевдоним, затем слаг только у компании без псевдонима; один канонический
  хост; адрес по слагу у компании с псевдонимом → 404), дальше по слагу;
  архив — оставить абзац про невыполненное «только чтение», если по коду это
  так.
- §7: читатели появились (блок H) — `holding_models.py`, `use_holding()`,
  экран «Сводка группы»; убрать «не читается»/«пока».
- §9: экран выбора компании на голом домене, восстановление сессии по
  refresh-cookie без второго входа (блок I.2 финальная волна,
  `frontend/src/lib/auth/sessionRestore.ts`) — сверь имя файла.
- Выкатка — только ссылкой на roadmap §7 и `docs/deploy/subdomains-runbook.md`.

- [ ] **Step 4: Проверка**

Проверка ссылок на `docs/multi-company-tenancy-design.md` — «ссылки: ok».
`grep -nE "не читается|переключателя нет" docs/multi-company-tenancy-design.md` — пусто.

- [ ] **Step 5: Коммит**

```bash
git add docs/multi-company-tenancy-design.md
git commit -m "docs(tenancy): дизайн мультикомпанейности — состояние после блоков A–I.2

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Стадия 2 — что из «не делается» выполнено

**Files:**
- Modify: `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` (§1.6 ~379-396, §7 ~844-862)
- Modify: `docs/multi-company-tenancy-stage2-design.md` (§10 «Перевод существующего HR» ~215-234, §14 «Чего стадия не делает» ~278-287)

- [ ] **Step 1: Список**

```bash
cd /c/Users/User/Desktop/HTQ-Web
sed -n '/^### 1.6/,/^### 1.7/p' docs/plans/2026-08-29-stage2-access-and-roles-spec.md
sed -n '/^## 7\. Чего стадия не делает/,/^## 8\./p' docs/plans/2026-08-29-stage2-access-and-roles-spec.md
sed -n '/^## 10\./,/^## 11\./p;/^## 14\./,$p' docs/multi-company-tenancy-stage2-design.md
```

- [ ] **Step 2: Сверка каждого пункта с кодом**

Пункты и где проверять:
- гейт на существующих ручках — `grep -c 'module="' backend/apps/{hr,tasks,users,access,companies}/views.py`, сторож `backend/apps/access/tests/test_gate.py`;
- `junior/middle/senior/lead` → роли — `backend/apps/access/migrations/0005_seed_hr_level_roles.py`;
- адаптер `hr-level` удалён — `grep -rn "hr-level" backend/apps/hr/urls.py` (пусто);
- `useHRLevel` — `frontend/src/hooks/useHRLevel.ts` (жив только для `pages/contracts/*`, сторож `frontend/src/hooks/__tests__/useHRLevelImporters.test.ts`);
- `LevelThreshold` — `backend/apps/hr/migrations/0024_seed_level_thresholds.py`;
- `CompanyModule` — `grep -n "class CompanyModule" backend/apps/companies/models.py`;
- архив «только чтение» — `backend/htqweb/middleware/company_context.py` (архив → 404);
- фильтрация по внешней иерархии и по `scope_kind=site` — `grep -rn "subordinate_companies\|scope_kind.*site\|SITE" backend/apps/tasks backend/apps/hr --include=*.py | grep -v tests | head`;
- третий режим `media_files`/`mail` — сверь, что сказано в документе, с кодом.

- [ ] **Step 3: Правка**

Не переписывать текст пунктов (это журнал решений) — дописать к каждому пункту
пометку в конце строки: «— **выполнено** блоком X ([план](…)), `файл`» или
«— **не выполнено** на 23.09.2026, см. [roadmap §9](2026-09-14-group-structure-roadmap.md#9-блок-i2--решения-по-ходу-исполнения-и-отложенное)» (якорь сверь по
фактическому заголовку). В начале §1.6 и §7 — строка «Статус на 23.09.2026 —
пометки у пунктов».

- [ ] **Step 4: Проверка**

Проверка ссылок на оба файла — «ссылки: ok» (включая якоря: проверь их руками
по заголовкам).

- [ ] **Step 5: Коммит**

```bash
git add docs/plans/2026-08-29-stage2-access-and-roles-spec.md docs/multi-company-tenancy-stage2-design.md
git commit -m "docs(stage2): пометки выполнено/остаётся после блоков B, I, I.2

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Followups мультикомпанейности

**Files:**
- Modify: `docs/multi-company-tenancy-followups.md`

- [ ] **Step 1: Список**

```bash
cd /c/Users/User/Desktop/HTQ-Web
grep -nE "^### |ЗАКРЫТО|ОТЛОЖЕНО|не подключ|не читается" docs/multi-company-tenancy-followups.md
```

- [ ] **Step 2: Сверка**

- п. 6 «`companySwitch` не подключён» — заголовок уже «ЗАКРЫТО блоком A», но
  тело говорит «никто не вызывает», «переключателя нет»:
  `grep -rn "switchCompany\|companyFromHost" frontend/src --include=*.tsx --include=*.ts | grep -v test`.
- п. 7 «Схема `holding` не читается» — блок H: `grep -rn "use_holding()" backend/apps --include=*.py | grep -v tests | head`.
- п. 3 (бизнес-метрики tenant-аппок), п. 4 (архив) — сверь текущее состояние
  с кодом (`backend/apps/*/metrics.py` для tenant-аппок; middleware для архива).
- «Двадцать отложенных мелких находок» — пройди список: каждая ещё актуальна?
  Отметь закрытые с указанием блока/коммита (`git log -S '<ключевое слово>' --oneline | head -3`).

- [ ] **Step 3: Правка**

- п. 6: тело — сократить до фактов после закрытия (кто зовёт `switchCompany`,
  `CompanyPicker`, псевдонимы), исходный текст оставить одной строкой
  «было: …».
- п. 7: заголовок «— ЗАКРЫТО блоком H», тело — читатели и где.
- Остальные — пометки по результатам шага 2.
- В начало — «Состояние на 23.09.2026» одной строкой со ссылкой на roadmap §10.

- [ ] **Step 4: Проверка**

Проверка ссылок — «ссылки: ok».

- [ ] **Step 5: Коммит**

```bash
git add docs/multi-company-tenancy-followups.md
git commit -m "docs(tenancy): followups — закрыты переключатель и читатели холдинга

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Живые документы разработчика — сквозная сверка

**Files:**
- Modify: `CLAUDE.md`, `API.md`, `STRUCTURE.md`, `backend/README.md` (только места, расходящиеся с кодом после блоков A–I.2)

- [ ] **Step 1: Известные расхождения и поиск остальных**

Известное: `CLAUDE.md` (раздел «Мультикомпанейность») упоминает
`.env.production` — проверь `ls .env.production 2>/dev/null; git ls-files | grep -c "^\.env\.production$"`.

Поиск остального:

```bash
cd /c/Users/User/Desktop/HTQ-Web
grep -nE "UZ|KG|КУП|СЭС|structure-refactoring|\.superpowers/|кандидат на снятие|HRAccessLevels|hr-level|require_hr_access|is_elevated" CLAUDE.md API.md STRUCTURE.md backend/README.md
grep -nE "api_view\(" backend/README.md | head
grep -nE "companies/v1" API.md | head -20
```
Для каждой найденной строки: верна ли она сегодня (`is_elevated` законно
встречается в описании областей видимости и платформенных операций — не
всякое упоминание устарело).

- [ ] **Step 2: Сверка с кодом**

- `backend/README.md`: описывает ли `api_view(module=, level=)` и реестр
  самообслуживания (`backend/htqweb/http.py`, `backend/apps/access/self_service.py`)?
  Если нет — один абзац со ссылкой на `CLAUDE.md` «Модель прав — одна».
- `API.md`: таблица ручек `companies/v1` против `backend/apps/companies/urls.py`
  (каждый путь); поле `subdomain`; ручки `access/v1` против
  `backend/apps/access/urls.py`.
- `STRUCTURE.md`: §3.7 (companies) — поля и команды против кода; §4 фронт —
  `CompanyPicker.tsx`, `sessionRestore.ts`, `hrNavAccess.ts`; §6 маршрутизация —
  метка хоста/псевдоним.

- [ ] **Step 3: Правка** — только расхождения; каждое в отчёт строкой «было → стало → чем подтверждено».

- [ ] **Step 4: Проверка**

Проверка ссылок на четыре файла — «ссылки: ok». Сторож документов, если он
смотрит на эти файлы: `cd backend && ../.venv/Scripts/python.exe -m pytest -q apps/core/tests/test_invariants.py` (форграунд, `timeout: 600000`).

- [ ] **Step 5: Коммит**

```bash
git add CLAUDE.md API.md STRUCTURE.md backend/README.md
git commit -m "docs: живые документы сверены с кодом после блоков A–I.2

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
(`git add` только тех из четырёх файлов, что реально менялись.)

---

### Task 6: Итоговая сверка структурного рефакторинга

**Files:**
- Create: `docs/plans/2026-09-23-group-structure-verification.md`

**Interfaces:**
- Consumes: roadmap после задачи 1 (§1 требования руководства, §4, §5 блоки, §6, §8, §9).

- [ ] **Step 1: Список требований**

Из roadmap §1 и §5 выпиши каждое проверяемое требование отдельной строкой.
Минимум: холдинг и три ДО с видами (`kind`) и деревом владения (`parent`);
ОСУ над ГД холдинга; три дирекции холдинга; уровни N-1…N-4 (N-3 в холдинге
пропущен); у ДО руководитель — «Директор»; штатные единицы; пунктирные связи
менеджеров дирекций; внешняя иерархия (правило 4); права холдинга в ДО
(`serves_subsidiaries`); десять кадровых предметов согласования (HR-FRM-004
строки 1–10) с фактами; замещение (HR-FRM-006); реестр/API/экраны компаний;
сводки холдинга; единая модель прав; поддомены. Каждое — с источником (§).

- [ ] **Step 2: Трассировка по коду**

Для каждого требования — где реализовано и чем доказано, командой, например:

```bash
cd /c/Users/User/Desktop/HTQ-Web/backend
grep -n "class CompanyKind" -A10 apps/companies/models.py
grep -n "def ensure_participant" apps/hr/services/participant_service.py
grep -n "SUBJECT_MODELS\|SUBJECT_SPECS" apps/hr/approval_hooks.py | head
grep -n "def substitutes_for" apps/hr/interface.py
grep -n "DIRECTORATE" apps/hr/models.py
grep -rn "Директор" apps/hr/management/group_structures.py | head
grep -n "def test_" apps/hr/tests/test_approval_hooks.py | head
```
и имя теста, который это держит. Требование без реализации или без теста —
строка со статусом «нет» или «частично» и объяснением.

- [ ] **Step 3: Прогоны**

- Бэкенд целиком: `cd backend && ../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
  (форграунд, `timeout: 600000`; прогон ~55 минут — если инструмент переведёт
  его в фон, дождись завершения и ничего параллельно не запускай). Ожидание —
  ровно 8 падений из `backend/ci-known-failures.txt`, поимённо.
- Фронт: `cd frontend && npx vitest run src` (8 известных:
  `CardT2SectionDialog` ×4, `EmployeeFormDialog — секции Т-2` ×4) и
  `npx tsc --noEmit -p tsconfig.app.json 2>&1 | grep -c "error TS"` (148).
- `makemigrations --check --dry-run` с окружением dev-БД из `CLAUDE.md`.

- [ ] **Step 4: Стенд (dev-БД, только чтение)**

С окружением dev-БД из `CLAUDE.md` («Reaching the dev database from the host»):

```bash
cd /c/Users/User/Desktop/HTQ-Web/backend
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py shell -c "
from apps.companies.models import Company
for c in Company.objects.order_by('slug'):
    print(c.slug, c.subdomain, c.kind, c.parent.slug if c.parent_id else None, c.status)
"
```
Плюс по каждой компании: число подразделений-дирекций, наличие должности
«Участник (ОСУ)» в холдинге, пороги уровней, число `PositionRole` — через
`apps.hr.interface`/`use_company(slug)` (только чтение). Сравни с
оргструктурой из roadmap §1.

- [ ] **Step 5: Документ сверки**

`docs/plans/2026-09-23-group-structure-verification.md`:
1. Итог одной фразой (выполнен / выполнен с оговорками / не выполнен).
2. Таблица «требование (источник) → реализация (файл) → доказательство
   (тест/команда) → статус (✅/частично/нет)».
3. Блоки A–I.2: план → статус → коммиты (`git log --oneline` по диапазонам из
   roadmap/планов).
4. Прогоны: числа дословно.
5. Стенд: что увидено.
6. Что не выполнено и чьё это: зона второго разработчика (roadmap §6),
   вопросы руководству (§8), сознательно оставленное (§9), новые расхождения,
   найденные этой сверкой (с оценкой важности).
7. Что НЕ проверялось (браузер, nginx, Cloudflare, боевые данные).

- [ ] **Step 6: Проверка и коммит**

Проверка ссылок на новый документ и на roadmap (ссылка из §10 теперь должна
разрешаться) — «ссылки: ok».

```bash
git add docs/plans/2026-09-23-group-structure-verification.md
git commit -m "docs: итоговая сверка структурного рефакторинга группы

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
