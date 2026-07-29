"""HTTP-слой ``/api/contracts/v1/*`` — class-based вьюхи.

Вьюхи тонкие: разбор запроса, вызов сервиса, форма ответа. Вся доменная
логика — в ``apps.contracts.services.*``.

**Почему CBV, когда остальные домены функциональные.** Остальные аппки
пришли из FastAPI-поколения и сохранили его форму: функция на эндпоинт плюс
рукописный диспетчер по ``request.method`` под каждым URL, где чтение и
запись живут вместе. Здесь вместо этого ``htqweb.http.ApiView`` (обычная
django-вьюха ``View``): ``dispatch`` разводит методы сам, диспетчеры не
нужны. Контракт ответов при этом ТОТ ЖЕ — ``api_view`` навешивается
пометодно через ``method_decorator``, потому что режим авторизации у
методов одного URL разный (GET — любой токен, POST/PATCH/DELETE — админ).

Права. Читать — любой аутентифицированный пользователь (``auth="jwt"``).
С записью два уровня:

- **Создание и отправка на согласование** бюджета, контрагента и договора —
  ``auth="jwt"``. Контролем служит согласование, а не админский флаг: если
  завести бюджет может только администратор, маршрут из трёх этапов над
  бюджетами нечего согласовывать. Заявку подаёт сотрудник, решение принимают
  названные в маршруте люди (``apps.signoff``).
- **Загрузка скана договора** — ``auth="jwt"`` с проверкой по данным: автор,
  пока договор черновик, либо администратор всегда. Заводить договор без
  права приложить к нему файл бессмысленно — на согласование уходит договор
  со сканом.
- **Правка, удаление, смена статуса и весь справочный слой** (страны,
  программы, администраторы бюджета) — по-прежнему ``admin=True``.

Более тонкой ролевой модели («финансист», «инициатор») в платформе нет:
``htqweb.authn.rbac.require_admin`` — единственный существующий уровень.
Появятся роли — правится только этот файл.
"""

from __future__ import annotations

from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator

from apps.signoff import interface as signoff
from htqweb.http import ApiView, api_view, json_error

from . import schemas
from .models import AgreementStatus, BudgetStatus, CounterpartyStatus, PaymentType
from .services import agreement_service as agr_svc
from .services import budget_calc
from .services import budget_service as budget_svc
from .services import counterparty_service as cp_svc
from .services import reference_service as ref_svc
from .services.agreement_service import AgreementRuleViolation
from .services.budget_calc import BudgetExceeded
from .services.reference_service import ReferenceConflict

# Конфликты доменного уровня, которые вьюха переводит в 409. Собраны в один
# кортеж, чтобы каждый `except` не перечислял их заново и не разъезжался с
# соседними при добавлении четвёртого.
#
# ``signoff.SignoffError`` — сюда же: «маршрут не настроен», «объект уже на
# согласовании», «в этапе не осталось активных согласующих» — это ровно
# такие же конфликты состояния, и различать их для фронтенда незачем, ему
# нужен текст. Импортируется из signoff.interface (правило границ).
CONFLICTS = (ReferenceConflict, AgreementRuleViolation, BudgetExceeded,
             signoff.SignoffError, signoff.UnknownSubject)


class ContractsView(ApiView):
    """База вьюх домена: разбор query-параметров + единая форма 409.

    ``self.request`` проставляет ``View.setup`` до ``dispatch``, поэтому
    геттеры ниже не требуют передавать request руками.
    """

    def conflict(self, exc: Exception):
        """409 — запрос корректен по форме, но противоречит состоянию данных.

        Отдельно от 422 (его отдаёт ``api_view`` на нарушение схемы) и от
        400: «бюджет уже существует» / «сумма не помещается в остаток» — не
        ошибки синтаксиса запроса, и фронтенду важно их различать, чтобы
        показать пользователю текст, а не «проверьте поля».
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


# Декораторы читаются лучше короткими алиасами: они повторяются на каждом
# методе, и в развёрнутом виде описание прав тонет в синтаксисе.
read = method_decorator(api_view(methods=("GET",), auth="jwt"))


def write(method: str, body=None, status: int = 200, admin: bool = True):
    """Пишущий метод. ``admin=True`` по умолчанию — снимается точечно там,
    где заявку подаёт сотрудник, а решение принимает согласование."""
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     body=body, status=status, admin=admin))


# DELETE отдаёт 204 без тела — конвенция репозитория (apps/cms/views.py).
# Ответ строится в каждом методе заново, а не берётся из общей константы:
# HttpResponse — объект с состоянием, и один экземпляр на все запросы
# рано или поздно утёк бы модифицированным.

# ═══════════════════════════════════════════════════════════════════════
# Страны
# ═══════════════════════════════════════════════════════════════════════

class CountryCollectionView(ContractsView):
    @read
    def get(self, request):
        return [schemas.CountryRead.model_validate(row)
                for row in ref_svc.list_countries()]

    @write("POST", body=schemas.CountryCreate, status=201)
    def post(self, request, data: schemas.CountryCreate):
        try:
            row = ref_svc.create_country(**data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.CountryRead.model_validate(row)


class CountryDetailView(ContractsView):
    @read
    def get(self, request, country_id: int):
        return schemas.CountryRead.model_validate(
            ref_svc.get_country_or_404(country_id))

    @write("PATCH", body=schemas.CountryUpdate)
    def patch(self, request, country_id: int, data: schemas.CountryUpdate):
        try:
            row = ref_svc.update_country(country_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.CountryRead.model_validate(row)

    @write("DELETE")
    def delete(self, request, country_id: int):
        try:
            ref_svc.delete_country(country_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


# ═══════════════════════════════════════════════════════════════════════
# Программы (+ статья расходов)
# ═══════════════════════════════════════════════════════════════════════

class ProgramCollectionView(ContractsView):
    @read
    def get(self, request):
        rows = ref_svc.list_programs(is_active=self.bool_param("is_active"))
        return [schemas.ProgramRead.model_validate(row) for row in rows]

    @write("POST", body=schemas.ProgramCreate, status=201)
    def post(self, request, data: schemas.ProgramCreate):
        try:
            row = ref_svc.create_program(**data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.ProgramRead.model_validate(row)


class ProgramDetailView(ContractsView):
    @read
    def get(self, request, program_id: int):
        return schemas.ProgramRead.model_validate(
            ref_svc.get_program_or_404(program_id))

    @write("PATCH", body=schemas.ProgramUpdate)
    def patch(self, request, program_id: int, data: schemas.ProgramUpdate):
        try:
            row = ref_svc.update_program(program_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.ProgramRead.model_validate(row)

    @write("DELETE")
    def delete(self, request, program_id: int):
        try:
            ref_svc.delete_program(program_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


# ═══════════════════════════════════════════════════════════════════════
# Администраторы бюджета
# ═══════════════════════════════════════════════════════════════════════

class AdministratorCollectionView(ContractsView):
    @read
    def get(self, request):
        rows = ref_svc.list_administrators(
            is_active=self.bool_param("is_active"),
            country_id=self.int_param("country_id"),
        )
        return [schemas.AdministratorRead.model_validate(row) for row in rows]

    @write("POST", body=schemas.AdministratorCreate, status=201)
    def post(self, request, data: schemas.AdministratorCreate):
        row = ref_svc.create_administrator(**data.model_dump())
        return schemas.AdministratorRead.model_validate(row)


class AdministratorDetailView(ContractsView):
    @read
    def get(self, request, administrator_id: int):
        return schemas.AdministratorRead.model_validate(
            ref_svc.get_administrator_or_404(administrator_id))

    @write("PATCH", body=schemas.AdministratorUpdate)
    def patch(self, request, administrator_id: int,
              data: schemas.AdministratorUpdate):
        try:
            row = ref_svc.update_administrator(administrator_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.AdministratorRead.model_validate(row)

    @write("DELETE")
    def delete(self, request, administrator_id: int):
        try:
            ref_svc.delete_administrator(administrator_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


# ═══════════════════════════════════════════════════════════════════════
# Бюджетные строки
# ═══════════════════════════════════════════════════════════════════════

class BudgetCollectionView(ContractsView):
    @read
    def get(self, request):
        rows = budget_svc.list_budgets(
            administrator_id=self.int_param("administrator_id"),
            program_id=self.int_param("program_id"),
            period_year=self.int_param("period_year"),
            status=self.str_param("status"),
            approval_state=self.str_param("approval_state"),
        )
        return [schemas.BudgetRead.model_validate(row) for row in rows]

    @write("POST", body=schemas.BudgetCreate, status=201, admin=False)
    def post(self, request, data: schemas.BudgetCreate):
        try:
            budget = budget_svc.create_budget(**data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.BudgetRead.model_validate(budget_svc.serialize_budget(budget))


class BudgetFullCreateView(ContractsView):
    """Заявка на бюджет вместе со справочниками — то, что шлёт форма.

    Отдельный маршрут, а не флаг на ``POST /budgets``: у обычного создания
    плоское тело со ссылками (``administrator_id``/``program_id``), у этого
    — вложенное, и склеивать их в одну схему значило бы получить объект,
    половина полей которого всегда пустая.
    """

    @write("POST", body=schemas.BudgetFullCreate, status=201, admin=False)
    def post(self, request, data: schemas.BudgetFullCreate):
        try:
            # Схемы передаются объектами, а не через model_dump(): сервис
            # читает вложенные administrator/program как модели (.id, .name),
            # и dump превратил бы их в словари.
            budget = budget_svc.create_budget_full(
                administrator=data.administrator, program=data.program,
                amount=data.amount, period_year=data.period_year,
                currency=data.currency, note=data.note,
            )
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.BudgetRead.model_validate(budget_svc.serialize_budget(budget))


class BudgetDetailView(ContractsView):
    @read
    def get(self, request, budget_id: int):
        budget = budget_svc.get_budget_or_404(budget_id)
        return schemas.BudgetRead.model_validate(budget_svc.serialize_budget(budget))

    @write("PATCH", body=schemas.BudgetUpdate)
    def patch(self, request, budget_id: int, data: schemas.BudgetUpdate):
        try:
            budget = budget_svc.update_budget(budget_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.BudgetRead.model_validate(budget_svc.serialize_budget(budget))

    @write("DELETE")
    def delete(self, request, budget_id: int):
        try:
            budget_svc.delete_budget(budget_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


class SubmitView(ContractsView):
    """База трёх эндпоинтов «отправить на согласование».

    Отдельная база, потому что все три отличаются одной строкой — какой
    сервис позвать, — а общего у них ровно то, что важно: права
    (``admin=False``, заявку подаёт сотрудник), перевод доменных конфликтов
    в 409 и форма ответа — карточка процесса из ``apps.signoff``, а не
    предметный объект. Фронтенду после отправки нужно показать «на каком
    этапе и кто согласует», и это знает signoff.
    """

    def submitted(self, call):
        try:
            return call(actor_id=self.request.token.user_id)
        except CONFLICTS as exc:
            return self.conflict(exc)


class BudgetSubmitView(SubmitView):
    @write("POST", status=201, admin=False)
    def post(self, request, budget_id: int):
        return self.submitted(
            lambda **kw: budget_svc.submit_for_approval(budget_id, **kw))


class CounterpartySubmitView(SubmitView):
    @write("POST", status=201, admin=False)
    def post(self, request, counterparty_id: int):
        return self.submitted(
            lambda **kw: cp_svc.submit_for_approval(counterparty_id, **kw))


class AgreementSubmitView(SubmitView):
    @write("POST", status=201, admin=False)
    def post(self, request, agreement_id: int):
        return self.submitted(
            lambda **kw: agr_svc.submit_for_approval(agreement_id, **kw))


class BudgetAgreementsView(ContractsView):
    """Договоры одной бюджетной строки — то, из чего сложился её остаток."""

    @read
    def get(self, request, budget_id: int):
        budget_svc.get_budget_or_404(budget_id)  # 404, а не пустой список
        rows = agr_svc.list_agreements(budget_id=budget_id)
        return [schemas.AgreementRead.model_validate(agr_svc.serialize_agreement(row))
                for row in rows]


# ═══════════════════════════════════════════════════════════════════════
# Реестр контрактов (контрагенты)
# ═══════════════════════════════════════════════════════════════════════

class CounterpartyCollectionView(ContractsView):
    @read
    def get(self, request):
        rows = cp_svc.list_counterparties(
            search=self.str_param("search"),
            status=self.str_param("status"),
            country_id=self.int_param("country_id"),
            approval_state=self.str_param("approval_state"),
        )
        return [schemas.CounterpartyRead.model_validate(row) for row in rows]

    @write("POST", body=schemas.CounterpartyCreate, status=201, admin=False)
    def post(self, request, data: schemas.CounterpartyCreate):
        try:
            row = cp_svc.create_counterparty(**data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.CounterpartyRead.model_validate(row)


class CounterpartyFullCreateView(ContractsView):
    """Карточка контрагента вместе со страной — то, что шлёт форма."""

    @write("POST", body=schemas.CounterpartyFullCreate, status=201, admin=False)
    def post(self, request, data: schemas.CounterpartyFullCreate):
        try:
            row = cp_svc.create_counterparty_full(
                bin_iin=data.bin_iin, name=data.name, country=data.country,
                vat=data.vat, contacts=data.contacts, address=data.address,
                status=data.status,
            )
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.CounterpartyRead.model_validate(row)


class CounterpartyDetailView(ContractsView):
    @read
    def get(self, request, counterparty_id: int):
        return schemas.CounterpartyRead.model_validate(
            cp_svc.get_counterparty_or_404(counterparty_id))

    @write("PATCH", body=schemas.CounterpartyUpdate)
    def patch(self, request, counterparty_id: int,
              data: schemas.CounterpartyUpdate):
        try:
            row = cp_svc.update_counterparty(counterparty_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.CounterpartyRead.model_validate(row)

    @write("DELETE")
    def delete(self, request, counterparty_id: int):
        try:
            cp_svc.delete_counterparty(counterparty_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


# ═══════════════════════════════════════════════════════════════════════
# Договоры
# ═══════════════════════════════════════════════════════════════════════

class AgreementCollectionView(ContractsView):
    @read
    def get(self, request):
        rows = agr_svc.list_agreements(
            budget_id=self.int_param("budget_id"),
            counterparty_id=self.int_param("counterparty_id"),
            administrator_id=self.int_param("administrator_id"),
            program_id=self.int_param("program_id"),
            period_year=self.int_param("period_year"),
            status=self.str_param("status"),
        )
        return [schemas.AgreementRead.model_validate(agr_svc.serialize_agreement(row))
                for row in rows]

    @write("POST", body=schemas.AgreementCreate, status=201, admin=False)
    def post(self, request, data: schemas.AgreementCreate):
        try:
            agreement = agr_svc.create_agreement(created_by=request.token.user_id,
                                                 **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.AgreementRead.model_validate(
            agr_svc.serialize_agreement(agreement))


class AgreementDetailView(ContractsView):
    @read
    def get(self, request, agreement_id: int):
        return schemas.AgreementRead.model_validate(
            agr_svc.serialize_agreement(agr_svc.get_agreement_or_404(agreement_id)))

    @write("PATCH", body=schemas.AgreementUpdate)
    def patch(self, request, agreement_id: int, data: schemas.AgreementUpdate):
        try:
            agreement = agr_svc.update_agreement(agreement_id, **data.model_dump())
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.AgreementRead.model_validate(
            agr_svc.serialize_agreement(agreement))

    @write("DELETE")
    def delete(self, request, agreement_id: int):
        try:
            agr_svc.delete_agreement(agreement_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return HttpResponse(status=204)


class AgreementStatusView(ContractsView):
    """Единственный путь смены статуса — здесь проверяется допустимость
    перехода (``agreement_service.ALLOWED_TRANSITIONS``). PATCH договора
    статус не принимает, иначе таблица переходов обходилась бы одним полем."""

    @write("POST", body=schemas.AgreementStatusChange)
    def post(self, request, agreement_id: int, data: schemas.AgreementStatusChange):
        try:
            agreement = agr_svc.change_status(agreement_id, data.status,
                                              actor_id=request.token.user_id)
        except CONFLICTS as exc:
            return self.conflict(exc)
        return schemas.AgreementRead.model_validate(
            agr_svc.serialize_agreement(agreement))


class AgreementFileView(ContractsView):
    """Загрузка скана договора (multipart, поле ``file``).

    ``body=`` у ``api_view`` здесь неприменим — это не JSON-запрос, файл
    приходит из ``request.FILES``.

    ``admin=False``: договор без приложенного скана отправлять на
    согласование нечего, поэтому право заводить договор без права приложить
    к нему файл — половина права. Но проверка тоньше, чем у создания, и по
    данным, а не декоратором (ср. ``signoff.ProcessCancelView``):

    - **автор** прикладывает файл, пока договор ЧЕРНОВИК. Дальше нельзя:
      повторная загрузка ЗАМЕЩАЕТ ссылку (``agreement_service.attach_file``),
      и подмена скана у договора, который уже ушёл на согласование, означала
      бы, что согласующие одобрили не тот документ, который в итоге лежит в
      карточке;
    - **администратор** — всегда, включая исправление уже подписанного
      договора: это тот же случай, что и правка статуса из django-admin.
    """

    @write("POST", admin=False)
    def post(self, request, agreement_id: int):
        agreement = agr_svc.get_agreement_or_404(agreement_id)
        if not request.token.is_elevated:
            if agreement.created_by != request.token.user_id:
                return json_error(
                    "Приложить файл может автор договора или администратор", 403)
            if agreement.status != AgreementStatus.DRAFT:
                return json_error(
                    f"Договор в статусе «{agreement.get_status_display()}» — "
                    f"заменить скан может только администратор", 403)

        upload = request.FILES.get("file")
        if upload is None:
            return json_error("Файл не передан (ожидается поле «file»)", 422)

        agreement = agr_svc.attach_file(
            agreement_id,
            data=upload.read(),
            filename=upload.name,
            mime=upload.content_type or "application/octet-stream",
            owner_id=request.token.user_id,
        )
        return schemas.AgreementRead.model_validate(
            agr_svc.serialize_agreement(agreement))


class AgreementFileUrlView(ContractsView):
    """Подписанная ссылка на скан договора."""

    @read
    def get(self, request, agreement_id: int):
        agreement = agr_svc.get_agreement_or_404(agreement_id)
        url = agr_svc.file_url(agreement)
        if url is None:
            raise Http404("К договору не приложен файл")
        return {"url": url}


# ═══════════════════════════════════════════════════════════════════════
# Служебное
# ═══════════════════════════════════════════════════════════════════════

class EnumsView(ContractsView):
    """Справочник choice-полей для фронтенда — чтобы подписи статусов и типов
    оплаты не дублировались во фронтовом словаре и не расходились с моделью
    при первом же изменении."""

    @read
    def get(self, request):
        def pairs(choices):
            return [{"value": value, "label": label} for value, label in choices]

        return {
            "agreement_status": pairs(AgreementStatus.choices),
            "budget_status": pairs(BudgetStatus.choices),
            "counterparty_status": pairs(CounterpartyStatus.choices),
            "payment_type": pairs(PaymentType.choices),
            # Из каких статусов договор занимает бюджет — фронтенду нужно,
            # чтобы объяснить пользователю, почему остаток не изменился после
            # сохранения черновика.
            "committing_statuses": sorted(budget_calc.COMMITTING_STATUSES),
            "transitions": {
                current: sorted(targets)
                for current, targets in agr_svc.ALLOWED_TRANSITIONS.items()
            },
        }
