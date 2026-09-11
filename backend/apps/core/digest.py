"""Утренняя сводка по бизнес-метрикам — форматирование.

Здесь НЕТ ни сети, ни кэша, ни запросов к базе: функция получает два снимка и
возвращает строку. Так её можно проверить тестом без Telegram, без Redis и без
Postgres, а всё остальное — чтение кэша, отправка, обработка отказа — живёт в
``apps/core/tasks.py::send_daily_digest`` и проверяется отдельно.

Почему сводку вообще пишем сами, хотя инцидентные оповещения принципиально
отданы Grafana: это противоположная задача по всем осям. Алерт — про
СОСТОЯНИЕ («сейчас плохо»), сводка — про СРАВНЕНИЕ («стало хуже, чем вчера»),
а у правил Grafana нет памяти о вчера. У алерта есть firing/resolved,
дедупликация и silence — у сводки нечего дедуплицировать. И, наконец, в
Grafana OSS отчётов нет вовсе, то есть альтернатива не «встроенная функция», а
«ничего». Написать своё оповещение об авариях значило бы переписать
Alertmanager; написать свою сводку — занять пустую нишу.

Строки описываются ТАБЛИЦЕЙ, а не кодом: добавить домен в сводку — это
дописать кортеж, а не трогать форматирование.
"""
from __future__ import annotations

import datetime as dt

# (раздел, аппка, метрика, подпись, формат)
#   "n"     — штуки
#   "money" — сумма, разряды тонкой шпацией
#
# Метрика, которой в снимке НЕТ (домен выключен, аппка упала при сборе,
# условная метрика без данных), строку просто не рисует. Ноль вместо неё был
# бы враньём: «ноль обращений» и «cms не отвечает» обязаны выглядеть
# по-разному ровно так же, как в /metrics.
LINES: tuple[tuple[str, str, str, str, str], ...] = (
    ("Деньги", "contracts", "contracts_awaiting_accounting",
     "ждут бухгалтерию", "n"),
    ("Деньги", "contracts", "contracts_awaiting_accounting_amount",
     "на сумму", "money"),
    ("Деньги", "contracts", "contracts_accountable_funds_outstanding",
     "под отчётом у сотрудников", "money"),
    ("Согласования", "signoff", "signoff_pending_stale",
     "стоят дольше трёх суток", "n"),
    ("Задачи", "tasks", "tasks_overdue", "просрочено", "n"),
    ("Задачи", "tasks", "daily_reports_today", "отчётов за сегодня", "n"),
    ("Люди", "hr", "hr_active_without_account",
     "работают без учётной записи", "n"),
    ("Люди", "users", "users_pending_stale",
     "регистраций ждут модерации", "n"),
    ("Сайт и почта", "cms", "cms_contact_requests_unhandled",
     "обращений без ответа", "n"),
    ("Сайт и почта", "mail", "mail_accounts_failing",
     "почтовых ящиков с ошибкой", "n"),
)

# U+2212 MINUS SIGN, а не дефис: в пропорциональном шрифте Telegram дефис
# рядом с цифрами читается как перенос.
_MINUS = "−"
_THIN = " "


def total(snapshot: dict, app: str, metric: str) -> float | None:
    """Сумма по всем сериям метрики. ``None`` — метрики в снимке нет."""
    spec = (snapshot.get(app) or {}).get(metric)
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec)
    return float(sum(n for _labels, n in spec.get("values", [])))


def _fmt_number(value: float, kind: str) -> str:
    if kind == "money":
        return "{:,.0f}".format(value).replace(",", _THIN) + " ₸"
    return "{:,.0f}".format(value).replace(",", _THIN)


def _fmt_delta(current: float, previous: float | None, kind: str) -> str:
    """Изменение со вчера — и ТОЛЬКО оно.

    Молчание означает «не изменилось». Помечать неизменившиеся строки словами
    («без изменений», «=») пробовали на глаз: в сводке из десяти строк такая
    пометка стоит у восьми и забивает ровно то, ради чего сводку читают. Тот
    же довод, по которому отсутствие метрики не рисуется нулём.

    Отсутствие базовой линии (первый выпуск, вытесненный кэш) выглядит так же,
    как отсутствие изменений, и это осознанный размен: цифра слева верна в
    обоих случаях, а отличать их читателю незачем.
    """
    if previous is None:
        return ""
    diff = current - previous
    if abs(diff) < 0.5:
        return ""
    sign = "+" if diff > 0 else _MINUS
    return " (%s%s)" % (sign, _fmt_number(abs(diff), kind))


def render(current: dict, previous: dict | None, *,
           now: dt.datetime, base_url: str = "") -> str:
    """Текст сводки. Единственная точка, которую покрывает тест."""
    header = "📅 HTQWeb — сводка на %s" % now.strftime("%d.%m.%Y")
    body: list[str] = []
    section = None

    for group, app, metric, caption, kind in LINES:
        value = total(current, app, metric)
        if value is None:
            continue
        if group != section:
            body.append("")
            body.append(group)
            section = group
        delta = _fmt_delta(value, total(previous or {}, app, metric), kind)
        body.append("  • %s: %s%s" % (caption, _fmt_number(value, kind), delta))

    if not body:
        # Пустой снимок — это не «всё по нулям», а «считать не из чего».
        # Ровно то же различение, что и в экспорте метрик.
        return (header + "\n\nДанных нет: сборщик бизнес-метрик не отработал.\n"
                "Проверьте backend-beat и backend-worker.")

    footer = ""
    if base_url:
        footer = "\n\nПодробности: %s/grafana/d/htqweb-domains" % base_url.rstrip("/")

    return header + "\n" + "\n".join(body) + footer
