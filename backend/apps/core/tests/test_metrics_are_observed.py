"""Метрика, на которую никто не смотрит, не существует.

Мотив ровно тот же, что у ``test_invariants.py``: инвариант держится на
дисциплине автора, и однажды он уже не удержался. Шесть гейджей
``apps/conference/metrics.py`` — весь конвейер записи встреч, включая
«записи застряли» и «протоколы не готовы», — не были упомянуты НИ В ОДНОМ
дашборде и НИ В ОДНОМ правиле алертов. Модуль при этом честно считал их
каждую минуту, а докстринг рядом объяснял, что конвейер ломается молча.
Метрика была, наблюдения не было, и ни один тест этого не заметил.

Проверка идёт в обе стороны, потому что дрейф бывает двух видов:

1. **Метрика есть в коде, но её никто не рисует** — новая ``metrics.py``
   доменной аппки становится седьмой сиротой.
2. **Панель ссылается на метрику, которой нет** — переименовали в коде или
   опечатались в JSON; панель остаётся пустой навсегда и выглядит как
   «значение ноль», а не как поломка.

Обе стороны опираются на рефлексию (``metrics.collect_all()`` обходит реестр
приложений), а не на список имён здесь: аппка, добавленная завтра, попадает
под проверку в тот же день без правок этого файла.

Граница покрытия: только семейство ``htqweb_*``. Метрики SFU (``sfu_*``,
``sfu/src/metrics.ts``) и экспортеров сюда не попадают — их имена живут в
чужих рантаймах, и достоверно перечислить их из Python нечем. Цена этого
известна на примере: панель просила ``sfu_process_resident_memory_bytes``,
а ``collectDefaultMetrics({prefix: 'sfu_process_'})`` отдаёт
``sfu_process_process_resident_memory_bytes`` — двойной ``process``, панель
пустая, тест бы промолчал. Такие имена проверяются только запросом к живому
Prometheus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from django.conf import settings

from apps.core import metrics


# BASE_DIR — это backend/, поэтому корень репозитория на уровень выше.
INFRA = Path(settings.BASE_DIR).parent / "infra" / "logging"
DASHBOARDS = INFRA / "grafana-dashboards"
RULES = INFRA / "grafana-provisioning" / "alerting" / "rules.yml"

PREFIX = metrics.PREFIX + "_"

# Намеренно тупой регексп по сырому тексту, а не разбор JSON и PromQL: он
# ловит имена и внутри селекторов вида {__name__=~"htqweb_fallback_total|..."},
# где никакой парсер выражений их бы не увидел. Отрицательный просмотр вперёд
# отсекает `htqweb_conference_*` из прозаических описаний панелей — это ссылка
# на семейство метрик, а не на конкретную.
_METRIC_RE = re.compile(r"\b" + PREFIX + r"[a-z_]+\b(?!\*)")

# Считается в htqweb/fallback.py, а не в metrics.py какой-либо аппки: это
# единственный настоящий Counter платформы и единственная метрика мимо
# BusinessMetricsCollector. В collect_all() её нет и быть не должно.
_DEFINED_OUTSIDE_APPS = {PREFIX + "fallback_total"}

# Условные метрики: аппка не отдаёт их, пока нет ни одной строки-источника
# (ни одного ежедневного отчёта; ни одной синхронизации почты). На пустой
# базе collect_all() их не вернёт, поэтому в проверке «код → инфра» они не
# участвуют, но для обратной проверки они полностью валидны.
_CONDITIONAL = {
    PREFIX + "daily_report_staleness_days",        # apps/tasks/metrics.py
    PREFIX + "mail_sync_lag_seconds",              # apps/mail/metrics.py
    PREFIX + "signoff_oldest_pending_seconds",     # apps/signoff/metrics.py
    PREFIX + "messenger_last_message_age_seconds", # apps/messenger/metrics.py
}

# Метрики, которые сознательно нигде не наблюдаются. Пусто — и должно таким
# остаться: каждая запись здесь это дыра, а не исключение. Если запись
# появляется, рядом обязан стоять TODO с тем, что её закроет.
_KNOWN_UNOBSERVED: set[str] = set()


def _infra_text() -> str:
    """Всё, что Grafana реально читает: дашборды и файл правил, одной строкой."""
    parts = [RULES.read_text(encoding="utf-8")]
    parts += [p.read_text(encoding="utf-8") for p in sorted(DASHBOARDS.glob("*.json"))]
    return "\n".join(parts)


def _skip_without_infra():
    """pytest гоняют с ХОСТА (backend/README-tests.md), где каталог на месте.

    В контейнер смонтирован только /app, поэтому там теста быть не может — и
    молчаливый пропуск здесь честнее ложного падения.
    """
    if not DASHBOARDS.is_dir() or not RULES.is_file():
        pytest.skip("infra/logging не смонтирован (запуск не с хоста)")


@pytest.mark.django_db
def test_every_collected_metric_is_observed():
    """Каждая считаемая метрика попадает на дашборд или в правило алерта."""
    _skip_without_infra()

    collected = {
        PREFIX + name
        for app_values in metrics.collect_all().values()
        for name in app_values
    }
    assert collected, "collect_all() не вернул ничего — сломан сам сбор метрик"

    referenced = set(_METRIC_RE.findall(_infra_text()))
    orphans = collected - referenced - _KNOWN_UNOBSERVED

    assert not orphans, (
        "метрики считаются, но их не рисует ни один дашборд и не проверяет ни "
        "одно правило: %s. Добавьте панель в infra/logging/grafana-dashboards/ "
        "(и правило, если у метрики есть осмысленный порог) либо внесите имя в "
        "_KNOWN_UNOBSERVED с TODO." % sorted(orphans)
    )


@pytest.mark.django_db
def test_every_referenced_metric_exists_in_code():
    """Каждая упомянутая в конфигах метрика существует в коде.

    Опечатка или переименование оставляют панель пустой навсегда, и пустая
    панель неотличима от честного нуля.
    """
    _skip_without_infra()

    defined = {
        PREFIX + name
        for app_values in metrics.collect_all().values()
        for name in app_values
    } | _DEFINED_OUTSIDE_APPS | _CONDITIONAL

    referenced = set(_METRIC_RE.findall(_infra_text()))
    unknown = referenced - defined

    assert not unknown, (
        "дашборды/правила ссылаются на несуществующие метрики: %s. Панель по "
        "такому имени останется пустой навсегда и будет выглядеть как «ноль»."
        % sorted(unknown)
    )


def test_alert_dashboard_links_resolve():
    """``__dashboardUid__``/``__panelId__`` обязаны указывать на живую панель.

    Эти две аннотации — единственное, из чего Grafana строит ``.DashboardURL``
    и ``.PanelURL`` в уведомлении; без них строка со ссылкой не выводится
    вовсе (так и было: в шаблоне она стояла, а ни одно правило её не питало).

    Проверка нужна потому, что связь держится на ЧИСЛОВОМ id панели: перетасуй
    панели в JSON — и ссылка из Telegram молча уведёт на чужой график. Неверная
    ссылка хуже отсутствующей: дежурный смотрит не туда и делает вывод.

    Заодно ловится вторая тихая ошибка — ``__panelId__`` числом вместо строки:
    аннотации Grafana это ``map[string]string``, и голое число отвергается
    провижинингом так же, как числовой chatid роняет контакт-пойнт.
    """
    _skip_without_infra()

    yaml = pytest.importorskip("yaml")

    known: dict[str, set[int]] = {}
    for path in sorted(DASHBOARDS.glob("*.json")):
        dash = json.loads(path.read_text(encoding="utf-8"))
        ids: set[int] = set()

        def collect_ids(panels):
            for panel in panels:
                if isinstance(panel.get("id"), int):
                    ids.add(panel["id"])
                # Панели внутри свёрнутого ряда лежат вложенно.
                collect_ids(panel.get("panels") or [])

        collect_ids(dash.get("panels") or [])
        known[dash["uid"]] = ids

    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    broken: list[str] = []

    for group in rules["groups"]:
        for rule in group["rules"]:
            annotations = rule.get("annotations") or {}
            uid = annotations.get("__dashboardUid__")
            panel = annotations.get("__panelId__")
            if uid is None and panel is None:
                continue
            if uid is None or panel is None:
                broken.append("%s: аннотации нужны парой" % rule["uid"])
                continue
            if not isinstance(panel, str):
                broken.append("%s: __panelId__ должен быть строкой, а не %s"
                              % (rule["uid"], type(panel).__name__))
                continue
            if uid not in known:
                broken.append("%s: нет дашборда с uid %r" % (rule["uid"], uid))
            elif int(panel) not in known[uid]:
                broken.append("%s: в дашборде %s нет панели %s"
                              % (rule["uid"], uid, panel))

    assert not broken, (
        "ссылки из уведомлений ведут в никуда: %s" % sorted(broken)
    )


def test_dashboards_use_provisioned_datasource_uids():
    """Datasource в дашборде должен совпадать с провижиненным uid.

    Регистр имеет значение: htqweb-services-overview годами ссылался на uid
    «Loki» при провижиненном «loki» — дашборд открывался, но не рисовал
    ничего. Ошибка тихая, поэтому проверяется отдельно.
    """
    _skip_without_infra()

    allowed = {"prometheus", "loki", "__expr__", "grafana", "-- Mixed --", "datasource"}
    bad: list[str] = []

    for path in sorted(DASHBOARDS.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))

        def walk(node):
            if isinstance(node, dict):
                ds = node.get("datasource")
                if isinstance(ds, dict) and "uid" in ds:
                    uid = ds["uid"]
                    # ${var} — ссылка на переменную дашборда, она валидна.
                    if not uid.startswith("$") and uid not in allowed:
                        bad.append("%s: %r" % (path.name, uid))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(raw)

    assert not bad, (
        "datasource uid не совпадает с провижиненными (см. "
        "grafana-provisioning/datasources/): %s" % sorted(set(bad))
    )
