"""План/факт с прогнозом: SPI, отставание, дата финиша по фактическому темпу.

Новый домен. Методика взята из SPEC §4 — она соответствует принятой в
компании практике план/факт по СЭС.

Всё считается **на отчётную дату D** (data date). Это не украшение: «мы
отстаём» без даты — не утверждение, а настроение. Прогноз, темп и проценты
на 5 июня и на 20 июня отвечают на разные вопросы, и оба должны быть
доступны, а не только «сегодня».

Три правила, которые здесь соблюдаются везде и которые легко нарушить
незаметно:

* **Не врать нулём.** Там, где сравнивать не с чем — плана нет, темпа нет,
  задач нет, — отдаётся ``None``, а не ``0``. Ноль означает «посчитали и
  вышло ноль»; для «не с чем сравнивать» у нас есть ``None``, и на фронте
  для него отдельный тон (``varianceTone('neutral')``).
* **Единицы не складываются.** 250 валов и 40 тонн нельзя сложить, поэтому
  агрегат по разным видам работ — это среднее ОТНОШЕНИЙ, а не отношение
  сумм. Тот же приём, что в ``block_service.block_progress``.
* **Мера длительности одна на проект.** Календарные дни по умолчанию
  (стройка идёт 7/7), рабочие — по флагу ``Project.use_production_calendar``.
  Считать план в одной мере, а факт в другой значит показать расхождение
  там, где его нет.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db.models import Sum
from django.http import Http404

from ..models import (Project, ProjectSite, Roadmap, Site, SiteBlock, Task,
                      TaskVolume)
from . import calendar_service
from . import daily_report_service

# Окно, по которому меряется фактический темп. Две недели — компромисс из
# спеки: неделя шумит на выходных и срывах поставок, месяц не замечает, что
# бригаду сняли позавчера.
RATE_WINDOW_DAYS = 14

# Пороги SPI. Ниже 0.95 — предупреждение, ниже 0.90 — нужен
# восстановительный график. Значения из SPEC §4, не выдуманные.
SPI_WARNING = 0.95
SPI_CRITICAL = 0.90

# Во сколько раз требуемый темп может превышать фактический, прежде чем
# план считается нереалистичным без добавления ресурсов.
REQUIRED_RATE_ALARM = 1.5


# ── элементарные величины ───────────────────────────────────────────────

def plan_percent(start: dt.date | None, end: dt.date | None, on: dt.date, *,
                 working: bool) -> float | None:
    """Сколько ПО ПЛАНУ должно быть сделано к дате ``on``, долей от 0 до 1.

    Линейно по интервалу: 0 до старта, 1 после конца. Линейность — сознательное
    упрощение: S-образный разгон работ мы не моделируем, потому что для этого
    нужны нормативы по видам работ, которых в системе нет. Прямая честнее
    выдуманной кривой.

    ``None``, когда плановых дат нет: без них «сколько должно быть сделано»
    не определено, и подставлять сюда ноль значило бы объявить пакет
    просроченным с первого дня.
    """
    if start is None or end is None or end < start:
        return None
    if on < start:
        return 0.0
    if on >= end:
        return 1.0
    total = calendar_service.days_between(start, end, working=working)
    passed = calendar_service.days_between(start, on, working=working)
    if not total:
        return None
    return min(passed / total, 1.0)


def _rate(series: list[dict], on: dt.date) -> tuple[float | None, int]:
    """Фактический темп (единиц в день) по последнему окну и его ширина.

    Окно — ``RATE_WINDOW_DAYS`` дней до ``on``, но не раньше первого отчёта:
    делить недельную выработку на 14 дней значило бы вдвое занизить темп
    команды, которая только вышла на объект.

    ``None``, если отчётов нет вовсе: «темп неизвестен» и «темп нулевой» —
    разные вещи, и вторая ниже трактуется как остановка.
    """
    reported = [row for row in series if row["date"] <= on]
    if not reported:
        return None, 0

    first = min(row["date"] for row in reported)
    window_start = max(first, on - dt.timedelta(days=RATE_WINDOW_DAYS - 1))
    width = (on - window_start).days + 1
    total = sum(float(row["quantity"]) for row in reported
                if row["date"] >= window_start)
    return (total / width if width else None), width


def forecast_end(remaining: float, rate: float | None,
                 on: dt.date) -> dt.date | None:
    """Когда закончим при текущем темпе. ``None`` — если темп неизвестен
    или нулевой при непустом остатке (это и есть «стоим»).

    Пустой остаток даёт ``on``: это честный ответ, когда о работе известно
    только «доделана». Когда известно БОЛЬШЕ — есть отчёты и по ним видна
    настоящая дата закрытия, — вызывающий подставляет её сам
    (``_completed_on``), а не спрашивает эту функцию.
    """
    if remaining <= 0:
        return on
    if not rate or rate <= 0:
        return None
    return on + dt.timedelta(days=remaining / rate)


def _completed_on(series: list[dict], on: dt.date) -> dt.date:
    """Дата последней работы по отчётам — фактический финиш.

    ``on`` как запасной вариант нужен для задач, закрытых без единого
    отчёта: объём у них плановый, факта нет, и датировать закрытие нечем.
    """
    dates = [row["date"] for row in series if row["date"] <= on]
    return max(dates) if dates else on


# ── узел дерева ─────────────────────────────────────────────────────────

def _node(*, kind: str, node_id: int, name: str,
          plan_start: dt.date | None, plan_end: dt.date | None,
          on: dt.date, working: bool,
          fact_pct: float | None, plan_pct: float | None,
          forecast: dt.date | None = None,
          forecast_plan_rate: dt.date | None = None,
          extra: dict | None = None) -> dict:
    """Собрать узел ответа: проценты, SPI, отставание, флаги.

    Одна функция на все уровни: правило «SPI = факт/план» и «отставание =
    прогноз − план» не зависит от того, задача это или проект, а пять копий
    разъехались бы.
    """
    spi = (round(fact_pct / plan_pct, 3)
           if plan_pct not in (None, 0) and fact_pct is not None else None)

    lag_days = ((forecast - plan_end).days
                if forecast is not None and plan_end is not None else None)
    duration = calendar_service.days_between(plan_start, plan_end,
                                             working=working)
    lag_pct = (round(lag_days / duration * 100, 1)
               if lag_days is not None and duration else None)

    flags = []
    if spi is not None:
        if spi < SPI_CRITICAL:
            flags.append("critical")
        elif spi < SPI_WARNING:
            flags.append("warning")
        elif spi > 1.05:
            # Опережение тоже помечаем: обычно оно означает, что ресурсы
            # ушли сюда с критического фронта, а не что здесь молодцы.
            flags.append("ahead")

    return {
        "kind": kind,
        "id": node_id,
        "name": name,
        "plan_start_date": plan_start,
        "plan_end_date": plan_end,
        "plan_pct": None if plan_pct is None else round(plan_pct * 100, 1),
        "fact_pct": None if fact_pct is None else round(fact_pct * 100, 1),
        "spi": spi,
        "forecast_end": forecast,
        "forecast_end_plan_rate": forecast_plan_rate,
        "lag_days": lag_days,
        "lag_pct": lag_pct,
        "flags": flags,
        **(extra or {}),
    }


def _task_node(task: Task, *, on: dt.date, working: bool,
               planned: dict[int, Decimal], completed: dict[int, Decimal],
               series: list[dict]) -> dict:
    """Узел задачи. Факт — из отчётов; при отсутствии объёмов — по проценту.

    ``progress_percent`` как запасная мера не «на всякий случай»: у
    согласования или приёмки измеримого объёма нет, и субъективная оценка
    исполнителя — единственное, что о них известно.
    """
    plan_total = float(sum(planned.values()))
    fact_total = float(sum(completed.values()))

    if plan_total > 0:
        fact_pct = min(fact_total / plan_total, 1.0)
        remaining = max(plan_total - fact_total, 0.0)
        rate, window = _rate(series, on)
        plan_duration = calendar_service.days_between(
            task.start_date, task.due_date, working=working)
        plan_rate = plan_total / plan_duration if plan_duration else None
        if remaining <= 0:
            # Работа закончена, и «прогноз финиша» для неё — дата, КОГДА её
            # закончили, а не сегодня. Разница не косметическая: с «сегодня»
            # пакет, сданный в срок два месяца назад, показывал бы отставание
            # в 60 дней и назавтра в 61 — прогноз полз бы за текущей датой,
            # пока плановая стоит на месте.
            forecast = forecast_by_plan = _completed_on(series, on)
        else:
            forecast = forecast_end(remaining, rate, on)
            forecast_by_plan = forecast_end(remaining, plan_rate, on)
        required = _required_rate_ratio(remaining, task.due_date, on, rate)
    else:
        fact_pct = (task.progress_percent or 0) / 100
        remaining = 0.0
        rate, window, forecast, forecast_by_plan, required = (
            None, 0, None, None, None)

    node = _node(
        kind="task", node_id=task.id, name=task.summary,
        plan_start=task.start_date, plan_end=task.due_date, on=on,
        working=working, fact_pct=fact_pct,
        plan_pct=plan_percent(task.start_date, task.due_date, on,
                              working=working),
        forecast=forecast, forecast_plan_rate=forecast_by_plan,
        extra={
            "key": task.key,
            "status": str(task.status),
            "planned_quantity": plan_total or None,
            "fact_quantity": fact_total or None,
            "rate_per_day": None if rate is None else round(rate, 2),
            "rate_window_days": window,
            "required_rate_ratio": required,
        },
    )
    if rate is not None and rate <= 0 and remaining > 0:
        node["flags"].append("stalled")
    if required is not None and required >= REQUIRED_RATE_ALARM:
        node["flags"].append("unrealistic")
    return node


def _required_rate_ratio(remaining: float, plan_end: dt.date | None,
                         on: dt.date, rate: float | None) -> float | None:
    """Во сколько раз надо ускориться, чтобы успеть к плановой дате.

    ``None``, когда сравнивать не с чем: нет плановой даты, нет остатка, нет
    измеренного темпа — или срок уже прошёл (тогда «ускориться» нельзя ни во
    сколько раз, и число было бы бессмысленным).
    """
    if plan_end is None or remaining <= 0 or not rate or rate <= 0:
        return None
    days_left = (plan_end - on).days
    if days_left <= 0:
        return None
    return round((remaining / days_left) / rate, 2)


# ── свёртка вверх ───────────────────────────────────────────────────────

def _weight(child: dict, working: bool) -> float:
    """Вес ребёнка в среднем родителя — плановая длительность в днях.

    Длительность, а не объём: объёмы разных видов работ несравнимы (валы
    против тонн), а дни сравнимы всегда. Ребёнок без плановых дат получает
    вес 1 — иначе он выпал бы из среднего целиком, и пакет из одних
    бездатных задач показал бы ``None`` вместо реального прогресса.
    """
    duration = calendar_service.days_between(
        child.get("plan_start_date"), child.get("plan_end_date"),
        working=working)
    return float(duration or 1)


def _rollup(children: list[dict], *, kind: str, node_id: int, name: str,
            plan_start: dt.date | None, plan_end: dt.date | None,
            on: dt.date, working: bool, extra: dict | None = None) -> dict:
    """Узел-родитель: проценты взвешенным средним, прогноз — по худшему ребёнку.

    Прогноз именно максимум, а не среднее: узел закончен тогда, когда
    закончилась ПОСЛЕДНЯЯ его работа. Ребёнок без прогноза (стоит или темп
    неизвестен) не обнуляет родителя, но и не улучшает его — он просто не
    участвует, а его состояние видно по собственным флагам.
    """
    def weighted(field: str) -> float | None:
        pairs = [(child[field], _weight(child, working)) for child in children
                 if child.get(field) is not None]
        if not pairs:
            return None
        total_weight = sum(weight for _, weight in pairs)
        if not total_weight:
            return None
        return sum(value * weight for value, weight in pairs) / total_weight / 100

    forecasts = [child["forecast_end"] for child in children
                 if child.get("forecast_end")]
    plan_rate_forecasts = [child["forecast_end_plan_rate"] for child in children
                           if child.get("forecast_end_plan_rate")]

    node = _node(
        kind=kind, node_id=node_id, name=name,
        plan_start=plan_start, plan_end=plan_end, on=on, working=working,
        fact_pct=weighted("fact_pct"), plan_pct=weighted("plan_pct"),
        forecast=max(forecasts) if forecasts else None,
        forecast_plan_rate=(max(plan_rate_forecasts)
                            if plan_rate_forecasts else None),
        extra={
            # Вес возвращается в ответе: правило взвешивания — предметное
            # решение, и потребитель вправе знать, по какому его считали.
            "weighting": "duration",
            "children": children,
            **(extra or {}),
        },
    )
    if any("stalled" in child["flags"] for child in children):
        node["flags"].append("has_stalled")
    return node


# ── публичные точки входа ───────────────────────────────────────────────

def roadmap_plan_fact(roadmap: Roadmap, on: dt.date) -> dict:
    """Пакет работ: узел + его задачи + серии по дням для S-кривой."""
    working = roadmap.project.use_production_calendar
    tasks = list(Task.objects.filter(roadmap_id=roadmap.id, is_deleted=False)
                 .order_by("start_date", "id"))

    children = _task_nodes(tasks, on=on, working=working)
    node = _rollup(children, kind="roadmap", node_id=roadmap.id,
                   name=roadmap.name,
                   plan_start=roadmap.planned_start_date,
                   plan_end=roadmap.planned_end_date, on=on, working=working)
    node["series"] = cumulative_series(
        roadmap=roadmap, tasks=tasks, on=on, working=working)
    return node


def _task_nodes(tasks: list[Task], *, on: dt.date, working: bool) -> list[dict]:
    """Узлы задач одной пачкой: три запроса на весь список, не на задачу."""
    if not tasks:
        return []
    ids = [task.id for task in tasks]

    planned: dict[int, dict[int, Decimal]] = {}
    for row in (TaskVolume.objects.filter(task_id__in=ids)
                .values("task_id", "volume_type_id", "planned_quantity")):
        planned.setdefault(row["task_id"], {})[row["volume_type_id"]] = \
            row["planned_quantity"]

    completed_raw = daily_report_service.completed_by_volume_type(
        task_ids=ids, upto=on)
    completed: dict[int, dict[int, Decimal]] = {}
    for (task_id, type_id), total in completed_raw.items():
        completed.setdefault(task_id, {})[type_id] = total

    series_by_task: dict[int, list[dict]] = {}
    for task_id in ids:
        series_by_task[task_id] = []
    for row in daily_report_service.daily_series_by_task(task_ids=ids, upto=on):
        series_by_task[row["task_id"]].append(
            {"date": row["date"], "quantity": row["quantity"]})

    return [_task_node(task, on=on, working=working,
                       planned=planned.get(task.id, {}),
                       completed=completed.get(task.id, {}),
                       series=series_by_task.get(task.id, []))
            for task in tasks]


def project_plan_fact(project: Project, on: dt.date) -> dict:
    """Дерево проект → площадки → блоки → роудмапы.

    Задачи в дерево НЕ разворачиваются: на уровне проекта их сотни, и
    отдавать их все ради процента родителя — это мегабайты ответа ради
    четырёх чисел. За задачами есть ``plan-fact/roadmap/<id>``.
    """
    working = project.use_production_calendar
    roadmaps = list(Roadmap.objects.filter(project_id=project.id)
                    .select_related("site_block", "site_block__site")
                    .order_by("order", "name"))

    roadmap_nodes: dict[int, dict] = {}
    for roadmap in roadmaps:
        tasks = list(Task.objects.filter(roadmap_id=roadmap.id,
                                         is_deleted=False))
        children = _task_nodes(tasks, on=on, working=working)
        node = _rollup(
            children, kind="roadmap", node_id=roadmap.id, name=roadmap.name,
            plan_start=roadmap.planned_start_date,
            plan_end=roadmap.planned_end_date, on=on, working=working,
            extra={"task_count": len(tasks)})
        # Задачи участвовали в расчёте, но в ОТВЕТ не уходят: на уровне
        # проекта их сотни, и отдавать их все ради четырёх чисел родителя —
        # мегабайты полезной нагрузки впустую. За ними есть
        # ``plan-fact/roadmap/<id>``; ``task_count`` говорит, сколько их.
        node["children"] = []
        roadmap_nodes[roadmap.id] = node

    # Блоки и площадки — из тех же роудмапов: заводить лишние запросы ради
    # пустых узлов незачем, а блок без пакетов работ на дашборде плана
    # показывать нечем.
    blocks: dict[int, list[dict]] = {}
    block_meta: dict[int, SiteBlock] = {}
    for roadmap in roadmaps:
        blocks.setdefault(roadmap.site_block_id, []).append(
            roadmap_nodes[roadmap.id])
        block_meta[roadmap.site_block_id] = roadmap.site_block

    sites: dict[int, list[dict]] = {}
    site_meta: dict[int, Site] = {}
    for block_id, children in blocks.items():
        block = block_meta[block_id]
        node = _rollup(children, kind="block", node_id=block_id,
                       name=block.name, plan_start=block.start_date,
                       plan_end=block.end_date, on=on, working=working)
        sites.setdefault(block.site_id, []).append(node)
        site_meta[block.site_id] = block.site

    site_nodes = []
    for site_id, children in sites.items():
        link = (ProjectSite.objects
                .filter(project_id=project.id, site_id=site_id)
                .values("start_date", "end_date").first()) or {}
        site_nodes.append(_rollup(
            children, kind="site", node_id=site_id,
            name=site_meta[site_id].name,
            plan_start=link.get("start_date"), plan_end=link.get("end_date"),
            on=on, working=working))

    root = _rollup(site_nodes, kind="project", node_id=project.id,
                   name=project.name, plan_start=project.start_date,
                   plan_end=project.end_date, on=on, working=working,
                   extra={"use_production_calendar": working})
    root["series"] = cumulative_series(project=project, on=on, working=working)
    return root


# ── S-кривая ────────────────────────────────────────────────────────────

def cumulative_series(*, on: dt.date, working: bool,
                      roadmap: Roadmap | None = None,
                      project: Project | None = None,
                      tasks: list[Task] | None = None) -> list[dict]:
    """Накопительные план и факт по дням: ``[{date, plan_cum, fact_cum}]``.

    Факт — нарастающий итог отчётов по ``work_date``. План — линейный
    разгон от плановой даты старта к плановому финишу, посчитанный тем же
    ``plan_percent``, что и проценты узлов: две разные формулы для одной
    линии на одном графике разъехались бы на первом же изменении.

    Ряд строится по объединению дней, где что-то происходило, а не по
    каждому календарному дню: месячный пакет это 30 точек, годовой проект —
    365, и рисовать их все незачем. Точки плановых границ добавляются
    всегда, иначе линия плана начиналась бы с первого отчёта.
    """
    if roadmap is not None:
        plan_start, plan_end = (roadmap.planned_start_date,
                                roadmap.planned_end_date)
        fact_rows = daily_report_service.daily_series(roadmap_id=roadmap.id,
                                                      upto=on)
        planned_total = float(
            TaskVolume.objects.filter(task__roadmap_id=roadmap.id,
                                      task__is_deleted=False)
            .aggregate(total=Sum("planned_quantity"))["total"] or 0)
    else:
        plan_start, plan_end = project.start_date, project.end_date
        fact_rows = daily_report_service.daily_series(project_id=project.id,
                                                      upto=on)
        planned_total = float(
            TaskVolume.objects.filter(task__project_id=project.id,
                                      task__is_deleted=False)
            .aggregate(total=Sum("planned_quantity"))["total"] or 0)

    days = {row["date"] for row in fact_rows}
    for boundary in (plan_start, plan_end, on):
        if boundary is not None:
            days.add(boundary)
    if not days:
        return []

    fact_by_day = {row["date"]: float(row["quantity"]) for row in fact_rows}
    running = 0.0
    out = []
    for day in sorted(days):
        running += fact_by_day.get(day, 0.0)
        share = plan_percent(plan_start, plan_end, day, working=working)
        out.append({
            "date": day,
            # План в тех же единицах, что и факт: доля × общий объём. Если
            # объёмов нет, плановой линии тоже нет — рисовать проценты
            # против штук на одной оси нельзя.
            "plan_cum": (round(share * planned_total, 2)
                         if share is not None and planned_total else None),
            # Факт после отчётной даты не рисуем: там его физически нет, и
            # обрыв линии честнее её продолжения по горизонтали.
            "fact_cum": round(running, 2) if day <= on else None,
        })
    return out


# ── загрузка целей ──────────────────────────────────────────────────────

def get_project_for_plan_fact(project_id: int) -> Project:
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    return project


__all__ = [
    "RATE_WINDOW_DAYS", "SPI_WARNING", "SPI_CRITICAL", "REQUIRED_RATE_ALARM",
    "plan_percent", "forecast_end", "roadmap_plan_fact", "project_plan_fact",
    "cumulative_series", "get_project_for_plan_fact",
]
