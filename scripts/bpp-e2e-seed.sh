#!/usr/bin/env bash
# Подготовка пилотной компании тестового стенда под сценарии приёмки модуля
# БЗО SC-001…SC-006 (этап 6 A, задача 7; D-S6-6).
#
#   docker compose -f docker-compose.test-local.yml up -d --build
#   ./scripts/bpp-e2e-seed.sh
#   cd frontend && npx playwright test tests/e2e/3*_bpp_* --project=msedge
#
# Что делает (всё идемпотентно — повтор ничего не дублирует):
#   0. migrate_companies — схемы компаний на актуальной версии.
#   1. seed_group_demo --skip-tasks — четыре компании группы, оргструктуры, учётки
#      сотрудников (пароль demo12345) и членства. Пилот — холдинг hi-tech-group
#      («управляющая компания», у неё есть ФД/ТД/ОД/ГД/СН/ПМ/БУХ).
#   2. Справочники: статьи бюджета (в refdata их ведёт управляющая компания; МРП 4325
#      и ставки НДС сеет миграция refdata/0002) и счёт организации с шаблоном выписки 1С
#      (нужны SC-006).
#   3. bpp_assign_roles — роли bpp-* должностям.
#   4. bpp_configure_routes — маршруты согласования заявки, договора, счёта.
#   5. seed_bpp_demo — демо-проекты ДЕМО-01/02 и документы во всех статусах
#      (сценарии на них НЕ опираются — у каждого свой проект и свои номера, — но
#      сид даёт стенду «живой» вид и заодно проверяет, что маршруты собраны верно).
#
# Только для локального стенда: seed_hr_demo и seed_employee_accounts сами
# отказываются работать с неместной БД.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.test-local.yml}"
SERVICE="${BACKEND_SERVICE:-backend-web}"
COMPANY="${E2E_COMPANY:-hi-tech-group}"
E2E_HOST_LABEL="${E2E_HOST_LABEL:-group}"

cd "$(dirname "$0")/.."

# Сид пишет демо-данные и заводит учётки с известным паролем — только локальный
# стек с Postgres в контейнере. test-env не годится: его БД берётся из .env и может
# оказаться боевой, а migrate_companies и правка псевдонима ниже идут до гардов команд.
case "$COMPOSE_FILE" in
  docker-compose.test-local.yml) ;;
  *) echo "Отказ: COMPOSE_FILE=$COMPOSE_FILE — сид допустим только на docker-compose.test-local.yml" >&2; exit 1 ;;
esac

manage() {
  docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" python manage.py "$@"
}

echo "== 0. Схемы компаний на актуальной версии =="
# Старт контейнера гонит только migrate_shared; тенантные схемы (hr, signoff, bpp…)
# доводит migrate_companies — на стенде со старой базой без него нет таблиц
# новых версий (например hr_actingassignment).
manage migrate_companies

echo "== 1. Компании, оргструктуры, учётки =="
manage seed_group_demo --skip-tasks

echo "== 1b. Короткий адрес пилота =="
# У компании с псевдонимом ОДИН канонический хост (слаг-адрес отвечает 404), а на
# базе, где компании заводились старой командой, псевдоним уже стоит ('group').
# Приводим к одному виду: пилот живёт на http://group.localhost:3000 везде.
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" python manage.py shell <<PY
from apps.companies.models import Company
n = Company.objects.filter(slug="${COMPANY}", subdomain__in=["", None]).update(subdomain="${E2E_HOST_LABEL:-group}")
print("псевдоним выставлен" if n else "псевдоним уже есть")
PY

echo "== 2. Справочники: статьи, счёт организации, шаблон выписки 1С =="
# IBAN — с верной контрольной суммой (ISO 13616); тот же зашит в
# frontend/tests/e2e/bpp_fixtures.ts (ORG_IBAN) — выписка SC-006 строится по нему.
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" python manage.py shell <<PY
from apps.refdata.models import Article, ArticleGroup
from apps.bpp.models.bank import OrgBankAccount, StatementTemplate
from apps.bpp.services.bank import settings as bank_settings
from htqweb.tenancy.db import use_company

ARTICLES = (
    ("E2E-MET", "Металлопрокат", "supply"),
    ("E2E-ELE", "Электрооборудование", "supply"),
    ("E2E-DES", "Проектные работы", "pm"),
)
for code, name, group_code in ARTICLES:
    group = ArticleGroup.objects.get(code=group_code)
    _, created = Article.objects.get_or_create(
        code=code, defaults={"name": name, "group": group})
    print(("статья заведена: " if created else "статья есть: ") + code)

IBAN = "KZ869980000000000001"
with use_company("${COMPANY}"):
    if OrgBankAccount.objects.filter(iban=IBAN).exists():
        print("счёт организации есть: " + IBAN)
    else:
        tpl = StatementTemplate.objects.filter(name="E2E Шаблон 1С").first()
        if tpl is None:
            tpl = bank_settings.create_template(
                {"name": "E2E Шаблон 1С", "format": "onec", "columns": {}}, actor_id=None)
        bank_settings.create_account(
            {"iban": IBAN, "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
             "currency": "KZT", "template_id": str(tpl.pk)}, actor_id=None)
        print("счёт организации заведён: " + IBAN)
PY

echo "== 3. Роли bpp-* должностям =="
manage bpp_assign_roles --company "$COMPANY"

echo "== 4. Маршруты согласования =="
manage bpp_configure_routes --company "$COMPANY"

echo "== 5. Демо-данные модуля =="
manage seed_bpp_demo --company "$COMPANY"

echo
echo "Готово. Пилот: $COMPANY (http://$E2E_HOST_LABEL.localhost:3000), пароль учёток demo12345."
