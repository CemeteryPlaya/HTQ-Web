"""HTTP-слой ``/api/signoff/v1/*`` — class-based вьюхи.

Стиль тот же, что в ``apps.contracts`` (``htqweb.http.ApiView``,
``method_decorator`` пометодно): ``dispatch`` разводит методы сам,
рукописные диспетчеры по ``request.method`` не нужны.

**Права.** Разделены по слоям домена, и разделены не так, как в contracts:

* **Маршруты** — настройка платформы: читать может любой аутентифицированный
  (фронтенду надо показать «кто будет согласовать» до отправки), править —
  только администратор.
* **Решения** (``/tasks/...``) — НЕ администраторские. В этом весь смысл
  модуля: согласует названный в маршруте человек, а не тот, у кого есть
  ``is_staff``. Кто именно вправе решить, проверяет ``engine.act`` по
  самому запросу, а не декоратор.
* **Запуск процесса** (``POST /processes``) — администраторский, и это
  осознанно узко. Обычная отправка на согласование идёт через ЭНДПОИНТ
  ПРЕДМЕТНОЙ АППКИ (``POST /api/contracts/v1/budgets/{id}/submit`` в фазе
  3), которая только и знает, кому её объект разрешено отправлять. Общий
  эндпоинт принимает ``subject_id`` любого объекта любого типа, и отдавать
  его всем подряд значило бы обойти доменные права мимо их владельца.
  Здесь он остаётся как операторский инструмент.
"""

from __future__ import annotations

import logging

from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator

from htqweb.http import ApiView, api_view, json_error

from . import schemas
from .models import (
    ApprovalProcess,
    ApprovalRoute,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from .services import engine, presentation, registry
from .services import route_service as routes
from .services.engine import SignoffError
from .services.registry import UnknownSubject
from .services.route_service import RouteConflict

logger = logging.getLogger(__name__)

# Конфликты доменного уровня, которые вьюха переводит в 409. Собраны в один
# кортеж, чтобы каждый `except` не перечислял их заново.
CONFLICTS = (SignoffError, RouteConflict, UnknownSubject)


class SignoffView(ApiView):
    """База вьюх домена: разбор query-параметров + единая форма 409."""

    def conflict(self, exc: Exception):
        """409 — запрос корректен по форме, но противоречит состоянию данных.

        Отдельно от 422 (нарушение схемы) и 403 (нехватка прав): «этот
        запрос адресован другому согласующему» и «согласование уже
        завершено» — состояние данных, и фронтенду важно показать текст, а
        не «проверьте поля».
        """
        return json_error(str(exc), 409)

    def int_param(self, name: str) -> int | None:
        raw = self.request.GET.get(name)
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def bool_param(self, name: str) -> bool | None:
        raw = self.request.GET.get(name)
        if raw in (None, ""):
            return None
        return raw.lower() in ("1", "true", "yes")

    def str_param(self, name: str) -> str | None:
        return self.request.GET.get(name) or None


read = method_decorator(api_view(methods=("GET",), auth="jwt"))


def write(method: str, body=None, status: int = 200, admin: bool = True):
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     body=body, status=status, admin=admin))


# ═══════════════════════════════════════════════════════════════════════
# Маршруты
# ═══════════════════════════════════════════════════════════════════════

class RouteCollectionView(SignoffView):
    @read
    def get(self, request):
        rows = routes.list_routes(subject_type=self.str_param("subject_type"),
                                  is_active=self.bool_param("is_active"))
        return [schemas.RouteRead.model_validate(routes.serialize_route(row))
                for row in rows]

    @write("POST", body=schemas.RouteCreate, status=201)
    def post(self, request, data: schemas.RouteCreate):
        try:
            route = routes.create_route(**data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.RouteRead.model_validate(routes.serialize_route(route))


class RouteDetailView(SignoffView):
    @read
    def get(self, request, route_id: int):
        # ``gaps=True`` только здесь: карточка одного маршрута — это экран
        # редактора, ради которого подсказка и считается.
        return schemas.RouteRead.model_validate(
            routes.serialize_route(routes.get_route_or_404(route_id), gaps=True))

    @write("PATCH", body=schemas.RouteUpdate)
    def patch(self, request, route_id: int, data: schemas.RouteUpdate):
        try:
            route = routes.update_route(route_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.RouteRead.model_validate(routes.serialize_route(route))

    @write("DELETE")
    def delete(self, request, route_id: int):
        routes.delete_route(route_id)
        return HttpResponse(status=204)


class RouteStagesView(SignoffView):
    """Добавление этапа в маршрут."""

    @write("POST", body=schemas.StageCreate, status=201)
    def post(self, request, route_id: int, data: schemas.StageCreate):
        try:
            stage = routes.add_stage(route_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.StageRead.model_validate(routes.serialize_stage(stage))


class StageDetailView(SignoffView):
    @read
    def get(self, request, stage_id: int):
        return schemas.StageRead.model_validate(
            routes.serialize_stage(routes.get_stage_or_404(stage_id)))

    @write("PATCH", body=schemas.StageUpdate)
    def patch(self, request, stage_id: int, data: schemas.StageUpdate):
        try:
            # exclude_unset: у списка согласующих None («не трогать») и
            # пустой список («стереть») — разные намерения, и model_dump()
            # без этого флага их не различает.
            stage = routes.update_stage(
                stage_id, **data.model_dump(exclude_unset=True))
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.StageRead.model_validate(routes.serialize_stage(stage))

    @write("DELETE")
    def delete(self, request, stage_id: int):
        try:
            routes.delete_stage(stage_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


# ═══════════════════════════════════════════════════════════════════════
# Процессы
# ═══════════════════════════════════════════════════════════════════════

class ProcessCollectionView(SignoffView):
    @read
    def get(self, request):
        query = ApprovalProcess.objects.prefetch_related("stages__tasks")
        subject_type = self.str_param("subject_type")
        subject_id = self.int_param("subject_id")
        state = self.str_param("state")
        initiator_id = self.int_param("initiator_id")
        if subject_type is not None:
            query = query.filter(subject_type=subject_type)
        if subject_id is not None:
            query = query.filter(subject_id=subject_id)
        if state is not None:
            query = query.filter(state=state)
        if initiator_id is not None:
            query = query.filter(initiator_id=initiator_id)
        return [
            schemas.ProcessRead.model_validate(
                presentation.serialize_process(row, enrich=True))
            for row in query
        ]

    @write("POST", body=schemas.ProcessStart, status=201)
    def post(self, request, data: schemas.ProcessStart):
        """Операторский запуск. Штатный путь — эндпоинт предметной аппки
        (см. докстринг модуля)."""
        try:
            process = engine.start(
                subject_type=data.subject_type, subject_id=data.subject_id,
                initiator_id=data.initiator_id or request.token.user_id,
            )
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.ProcessRead.model_validate(
            presentation.serialize_process(process, enrich=True))


class ProcessDetailView(SignoffView):
    @read
    def get(self, request, process_id: int):
        process = ApprovalProcess.objects.filter(pk=process_id).first()
        if process is None:
            raise Http404("Процесс согласования не найден")
        return schemas.ProcessRead.model_validate(
            presentation.serialize_process(process, enrich=True))


class ProcessCancelView(SignoffView):
    """Отзыв согласования — инициатором или администратором.

    ``admin=False``: инициатор обязан иметь возможность отозвать СВОЮ
    заявку, не будучи администратором платформы. Проверка «свой ли это
    процесс» — ниже, по данным, а не декоратором.
    """

    @write("POST", admin=False)
    def post(self, request, process_id: int):
        process = ApprovalProcess.objects.filter(pk=process_id).first()
        if process is None:
            raise Http404("Процесс согласования не найден")

        is_initiator = process.initiator_id == request.token.user_id
        if not (is_initiator or request.token.is_elevated):
            return json_error("Отозвать согласование может только инициатор "
                              "или администратор", 403)

        try:
            process = engine.cancel(process_id=process_id,
                                    actor_id=request.token.user_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.ProcessRead.model_validate(
            presentation.serialize_process(process, enrich=True))


# ═══════════════════════════════════════════════════════════════════════
# Решения
# ═══════════════════════════════════════════════════════════════════════

class InboxView(SignoffView):
    """«Ждёт моего решения» — всегда про того, кто спрашивает.

    Чужой список намеренно не отдаётся ни по какому параметру: это персональная
    очередь, и подсматривать её незачем. Администратору для надзора есть
    ``GET /processes``.
    """

    @read
    def get(self, request):
        return [schemas.InboxItem.model_validate(row)
                for row in presentation.list_inbox(request.token.user_id)]


class TaskDecisionView(SignoffView):
    """Единственный путь принять решение.

    ``admin=False`` — принципиально: согласует названный в маршруте человек.
    Право проверяет ``engine.act`` по самому запросу.
    """

    @write("POST", body=schemas.Decision, admin=False)
    def post(self, request, task_id: int, data: schemas.Decision):
        try:
            process = engine.act(task_id=task_id,
                                 actor_id=request.token.user_id,
                                 decision=data.decision, comment=data.comment)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.ProcessRead.model_validate(
            presentation.serialize_process(process, enrich=True))


# ═══════════════════════════════════════════════════════════════════════
# Служебное
# ═══════════════════════════════════════════════════════════════════════

class SubjectsView(SignoffView):
    """Какие типы объектов вообще согласуемы — список для настройки маршрута.

    Наполняется реестром, то есть тем, что предметные аппки зарегистрировали
    на старте. Захардкоженного списка здесь нет и быть не может: новая
    согласуемая модель появляется без правок signoff.

    Вместе с типом отдаются и его ``fields`` — факты, по которым разрешено
    ветвить маршрут, со справочниками значений. Отсюда редактор и узнаёт, что
    у бюджета бывает «страна администратора» и какие страны существуют:
    signoff этого не знает, он лишь передаёт то, что сказала предметная аппка.
    """

    @read
    def get(self, request):
        configured = set(ApprovalRoute.objects.filter(is_active=True)
                         .values_list("subject_type", flat=True))
        return [
            schemas.SubjectRead.model_validate({
                "subject_type": subject.subject_type,
                "label": subject.label,
                "has_active_route": subject.subject_type in configured,
                "fields": self._fields(subject.subject_type),
            })
            for subject in registry.registered_subjects()
        ]

    def _fields(self, subject_type: str) -> list[dict]:
        """Схема фактов одного типа, не роняющая список остальных.

        ``fact_fields()`` — чужой код, ходящий в чужую БД: сломанный
        справочник в одной аппке не должен лишать администратора возможности
        настроить маршруты всех прочих типов.
        """
        try:
            return registry.fields_for(subject_type)
        except Exception:
            logger.warning("signoff: fact_fields() для %s упал",
                           subject_type, exc_info=True)
            return []


class EnumsView(SignoffView):
    """Справочник choice-полей — чтобы подписи не дублировались во фронтовом
    словаре и не расходились с моделью при первом же изменении."""

    @read
    def get(self, request):
        def pairs(choices):
            return [{"value": value, "label": label} for value, label in choices]

        return {
            "quorum": pairs(Quorum.choices),
            "process_state": pairs(ProcessState.choices),
            "stage_state": pairs(StageState.choices),
            "task_state": pairs(TaskState.choices),
        }
