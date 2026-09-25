"""Шаблон «Заявка на закуп» — тот, что просил CFO, одной командой.

Форма собрана по его записке: **Админ бюджета** и **Программа бюджета** —
это один виджет ``budget_line_ref`` (строка бюджета и есть «администратор ×
программа», каскад рисует фронт), ниже повторяемая группа позиций **ТРУ /
кол-во / ед. / дата потребности** с кнопками «+»/«−».

Зачем командой, а не «соберите в конструкторе»: форма из шести полей, в
которой важен КАЖДЫЙ тип (строка бюджета — виджет, а не текст; единицы —
список, а не свободный ввод), собирается мышью минут пятнадцать и ровно так
же легко собирается неправильно. Команда идемпотентна и безопасна на проде:
шаблон опознаётся по ``slug``, повторный запуск ничего не дублирует.

    manage.py seed_purchase_request_template                     # шаблон + форма
    manage.py seed_purchase_request_template --buyer 3 --cfo 7   # ещё и маршрут
    manage.py seed_purchase_request_template --slug zakup-hq --name "Закуп ГО"

**Маршрут — три шага закупщика подряд, затем финансовый директор.**

Закуп — работа на дни, и один этап «закупщик проверил» прятал бы её целиком:
заявка неделю висела бы в очереди без признаков движения. Поэтому у
закупщика два этапа — его чек-лист, по которому и он, и инициатор видят, на
чём дело стоит: **Подбор поставщика** → **Счёт на оплату**.

Каждый шаг закрывается результатом, который движок проверяет до записи
решения. На первом — **сравнительная таблица**: предложения поставщиков с
ценами по позициям и отметкой выбранного; из неё СЛЕДУЕТ сумма
(``quotes.total`` считает сервер), поэтому отдельных полей «поставщик» и
«согласованная сумма» нет — два места для одного числа рано или поздно
разойдутся. На втором — реквизиты счёта и файл PDF, причём **сумма по счёту
обязана равняться выбранному предложению** (``must_equal: quotes.total``):
иначе CFO утверждает одно, а платят другое.

Таблицу и блок счёта закупщик заполняет прямо на карточке согласования —
инициатор их не видит и знать не может. Поставщик здесь не контрагент из
«Договоров»: разовая закупка не должна тянуть карточку с БИН и
согласованием. CFO утверждает по сумме и счёту; счёт видит ссылкой в «Ходе
согласования».

Отказ на любом шаге до CFO не доходит (у signoff любое отрицательное
решение закрывает круг); «на доработку» возвращает заявку инициатору.

Согласующие называются **должностями HR**, а не людьми: сменился сотрудник
— маршрут править не нужно, движок находит текущего на запуске.
``--buyer``/``--cfo`` принимают id должности (``hr_position``).

**Без этих аргументов маршрут НЕ создаётся.** Пустой маршрут (без этапов)
хуже, чем его отсутствие: отправка отвечала бы «в маршруте нет ни одного
этапа» вместо внятного «маршрут не настроен». Настроить его можно и руками
— в редакторе шаблона, вкладка «Маршрут».

``--buyer-user``/``--cfo-user`` — запасной вариант, когда должности в HR
ещё не заведены (тест, демо): те же два этапа, но согласующие названы
поимённо. На проде так делать не стоит по причине выше.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.approvals.approval_hooks import scope_for_template
from apps.approvals.models import (
    RequestFormTemplate,
    RequestFormTemplateVersion,
    RequestInstance,
    TemplateStatus,
)
from apps.approvals.services.template_data_table import (
    ensure_source_for_template,
    sync_columns_for_template,
)
from apps.hr import interface as hr
from apps.signoff import interface as signoff

DEFAULT_SLUG = "zayavka-na-zakup"
DEFAULT_NAME = "Заявка на закуп"

# Названия этапов маршрута. Именно они видны согласующему в «Ждёт меня»,
# поэтому говорят о РОЛИ, а не о человеке: кто именно на должности сегодня,
# движок разрешает сам.
#
# У закупщика этапов ТРИ, а не один, и это его чек-лист, а не бюрократия.
# Закуп — работа на дни, и один этап «закупщик проверил» показывал бы
# заявку в очереди неделю без единого признака движения — ни закупщику («на
# чём я остановился по этой?»), ни инициатору («где моя заявка?»). Два этапа
# подряд превращают «Ход согласования» в трекер: видно, какой шаг сделан,
# какой идёт, что осталось.
#
# Каждый шаг закрывается результатом, который движок проверяет ДО записи
# решения (``engine.act``), поэтому пропустить шаг «на глазок» нельзя:
#   1. поставщик подобран  → в таблице есть предложения с ценами и отмечен
#                            выбранный (из него следует сумма заявки);
#   2. счёт получен        → заполнен блок «Счёт на оплату» + файл PDF,
#                            и сумма по счёту РАВНА выбранному предложению.
# Сравнение поставщиков и реквизиты счёта — поля заявки (``filled_by =
# approver`` в схеме), а не строки комментария: по ним CFO видит, из чего
# выбирали, у кого, за сколько и по какому счёту, а не читает переписку.
#
# Кортеж: (название, нужен документ, нужно пояснение, требование к заявке).
BUYER_STAGES: list[tuple[str, bool, bool, str]] = [
    ("Подбор поставщика", False, False, "field:quotes"),
    ("Счёт на оплату", True, False, "field:invoice"),
]
STAGE_CFO = "Утверждение финансовым директором"

# Единицы измерения — фиксированным списком (решение по записке CFO):
# отдельного справочника под них не заводим, расширяется правкой здесь.
UNITS = ["шт", "кг", "т", "м", "м²", "м³", "л", "компл.", "усл.", "ч"]

SCHEMA = {
    "fields": [
        {
            "key": "budget_line",
            "type": "budget_line_ref",
            "label": "Бюджет (администратор → программа)",
            "required": True,
        },
        {
            "key": "items",
            "type": "group",
            "label": "Позиции закупа",
            "required": True,
            "repeatable": True,
            # Что суммировать по позициям в личной аналитике («сколько
            # ноутбуков я запросил за год»): колонка количества.
            "summarize_keys": ["quantity"],
            "fields": [
                {"key": "name", "type": "text", "label": "ТРУ (товар, работа, услуга)",
                 "required": True, "max": 500},
                {"key": "quantity", "type": "number", "label": "Кол-во",
                 "required": True, "min": 0},
                {"key": "unit", "type": "dropdown", "label": "Ед. изм.",
                 "required": True, "options": UNITS},
                {"key": "needed_by", "type": "date", "label": "Дата потребности",
                 "required": True},
            ],
        },
        {"key": "purpose", "type": "paragraph", "label": "Обоснование потребности",
         "max": 2000},

        # ── Заполняет ЗАКУПЩИК на своих шагах, не инициатор ──────────────
        #
        # Сравнительная таблица — то, что закупщик и так сводит в Excel:
        # строки = позиции заявки, колонки = поставщики, в клетках цена ЗА
        # ЕДИНИЦУ. Из неё следует и поставщик, и сумма, поэтому отдельных
        # блоков «Поставщик» и «Согласованные условия» здесь нет.
        #
        # Поставщик тут — НЕ контрагент из «Договоров»: разовая закупка не
        # должна тянуть карточку с БИН и согласованием. Понадобится
        # постоянный — его заводят в реестре отдельно.
        #
        # ``contributes_to_total`` — это и есть сумма заявки: сервер кладёт
        # итог выбранного предложения в ``quotes.total``
        # (``services/quotes.py``), и по нему считаются личная аналитика,
        # роллапы и сверка со счётом.
        {"key": "quotes", "type": "supplier_quotes",
         "label": "Сравнение поставщиков", "filled_by": "approver",
         "items_field": "items", "quantity_key": "quantity",
         "currency": "KZT", "contributes_to_total": True},
        # Условия поставки и оплаты — словами: в таблице только цены, а
        # сроки и порядок оплаты CFO читает здесь.
        {"key": "terms", "type": "paragraph", "filled_by": "approver",
         "label": "Условия поставки и оплаты", "max": 2000},
        # Сам счёт — файлом (PDF) на задаче этапа; здесь — его реквизиты,
        # чтобы CFO и бухгалтерия не открывали PDF ради номера и суммы.
        {"key": "invoice", "type": "group", "label": "Счёт на оплату",
         "repeatable": False, "filled_by": "approver", "fields": [
             {"key": "number", "type": "text", "label": "Номер счёта",
              "required": True, "max": 100},
             {"key": "date", "type": "date", "label": "Дата счёта"},
             # Главная проверка шага: счёт — ровно на согласованную сумму.
             # Иначе CFO утверждает одно, а платят другое; расхождение —
             # либо ошибка поставщика, либо пересогласование условий, и в
             # обоих случаях шаг не должен закрыться молча.
             {"key": "amount", "type": "money", "label": "Сумма по счёту",
              "required": True, "currency": "KZT", "must_equal": "quotes.total"},
         ]},
    ],
}


class Command(BaseCommand):
    help = "Завести шаблон «Заявка на закуп» (форма из записки CFO)"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default=DEFAULT_SLUG)
        parser.add_argument("--name", default=DEFAULT_NAME)
        parser.add_argument("--buyer", type=int, default=None,
                            help="id должности HR закупщика (этап 1)")
        parser.add_argument("--cfo", type=int, default=None,
                            help="id должности HR финансового директора (этап 2)")
        parser.add_argument("--buyer-user", type=int, default=None,
                            help="user_id закупщика — когда должностей в HR ещё нет")
        parser.add_argument("--cfo-user", type=int, default=None,
                            help="user_id финдиректора — когда должностей в HR ещё нет")

    @transaction.atomic
    def handle(self, *args, slug: str, name: str, buyer: int | None,
               cfo: int | None, buyer_user: int | None, cfo_user: int | None,
               **options):
        template = RequestFormTemplate.objects.filter(slug=slug).first()
        if template is None:
            template = RequestFormTemplate.objects.create(
                slug=slug, name=name, status=TemplateStatus.ACTIVE,
                description="Закуп ТРУ по строке бюджета: администратор → "
                            "программа, позиции с количеством и сроком.",
                icon="shopping-cart", color="#0ea5e9",
                # Форму видят все: подаёт заявку тот, кому нужен закуп.
                config_json={"who_can_submit": "all", "show_on_workplace": True},
            )
            self.stdout.write(self.style.SUCCESS(
                f"Шаблон создан: [{template.pk}] «{template.name}» (slug={slug})"))
        else:
            self.stdout.write(f"Шаблон уже есть: [{template.pk}] «{template.name}»")

        version = self._publish_if_changed(template)
        ensure_source_for_template(template)
        sync_columns_for_template(template, SCHEMA)

        self._route(template, buyer=buyer, cfo=cfo,
                    buyer_user=buyer_user, cfo_user=cfo_user)

        self.stdout.write("")
        self.stdout.write(f"Форма: версия {version.version}, "
                          f"полей верхнего уровня {len(SCHEMA['fields'])}, "
                          f"единиц в списке {len(UNITS)}")
        self.stdout.write(
            "Подача заявки: «Запросы» → «Создать запрос» → "
            f"«{template.name}». Маршрут — в редакторе шаблона, вкладка «Маршрут».")

    # ── форма ────────────────────────────────────────────────────────────

    def _publish_if_changed(self, template: RequestFormTemplate) -> RequestFormTemplateVersion:
        """Версия публикуется, только если форма отличается от текущей.

        Версии неизменяемы, и каждая новая перепривязывает заявки к другому
        снимку схемы — плодить их повторным запуском команды незачем.
        """
        current = (RequestFormTemplateVersion.objects
                   .filter(pk=template.current_version_id).first()
                   if template.current_version_id else None)
        if current is not None and current.schema_json == SCHEMA:
            self.stdout.write("Форма не изменилась — новая версия не нужна")
            return current

        next_number = (RequestFormTemplateVersion.objects
                       .filter(template=template)
                       .order_by("-version")
                       .values_list("version", flat=True).first() or 0) + 1
        version = RequestFormTemplateVersion.objects.create(
            template=template, version=next_number,
            schema_json=SCHEMA, workflow_json={},
        )
        template.current_version_id = version.pk
        template.save(update_fields=["current_version_id", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Опубликована версия формы {next_number}"))
        return version

    # ── маршрут ──────────────────────────────────────────────────────────

    def _route(self, template: RequestFormTemplate, *, buyer: int | None,
               cfo: int | None, buyer_user: int | None,
               cfo_user: int | None) -> None:
        scope = scope_for_template(template.pk)
        subject_type = RequestInstance.SIGNOFF_SUBJECT_TYPE

        if signoff.has_active_route(subject_type, scope):
            self.stdout.write("Маршрут согласования уже настроен")
            return

        stages = self._stages(buyer=buyer, cfo=cfo, buyer_user=buyer_user,
                              cfo_user=cfo_user)
        if stages is None:
            self.stdout.write(self.style.WARNING(
                "Маршрут не настроен — отправка заявки будет отвечать «не "
                "настроен маршрут согласования». Задайте согласующих: "
                "--buyer <position_id> --cfo <position_id> (или настройте "
                "маршрут в редакторе шаблона, вкладка «Маршрут»)."))
            return

        try:
            signoff.configure_route(
                subject_type=subject_type, scope=scope,
                name=f"Маршрут «{template.name}»", stages=stages,
            )
        except signoff.RouteConflict as exc:
            # Чаще всего: должности с таким id в HR нет. Маршрут, который
            # заведомо не настроится, движок не принимает — и правильно.
            raise CommandError(f"Маршрут не принят движком: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            "Маршрут создан: " + " → ".join(
                f"{stage['order']}. {stage['name']}" for stage in stages)))
        self.stdout.write(
            "  Шаги закупщика закрываются результатом: сравнительная таблица с "
            "отмеченным поставщиком, затем реквизиты счёта и файл PDF на ту же "
            "сумму; без этого движок решение не примет.")
        self._warn_about_empty_positions(stages)

    def _warn_about_empty_positions(self, stages: list[dict]) -> None:
        """Предупредить о должности, на которой некому согласовывать.

        Движок проверяет это на ЗАПУСКЕ, а не при сохранении маршрута — и
        правильно: между настройкой и первой заявкой проходят недели, за
        которые человека и принимают, и увольняют. Но у разовой команды
        настройки другая задача: сказать администратору сейчас, пока он
        здесь, а не устами сотрудника, который через месяц упрётся в
        «на этапе нет активного сотрудника».
        """
        position_ids = [pid for stage in stages for pid in stage.get("position_ids", [])]
        if not position_ids:
            return
        resolved = hr.resolve_position_users(position_ids)
        empty = [pid for pid in position_ids if not resolved.get(pid)]
        if empty:
            self.stdout.write(self.style.WARNING(
                "⚠ На должностях " + ", ".join(map(str, empty)) + " нет активного "
                "сотрудника с учётной записью платформы — отправка заявки по "
                "этому маршруту откажет, пока это не исправлено в HR."))

    @staticmethod
    def _stages(*, buyer: int | None, cfo: int | None,
                buyer_user: int | None, cfo_user: int | None) -> list[dict] | None:
        """Три шага закупщика подряд, затем CFO. По должностям — если заданы
        обе; поимённо — если заданы обе учётные записи; иначе маршрута нет.

        Обе или ни одной намеренно: маршрут из одного закупщика без CFO (или
        наоборот) — не «половина настройки», а другой процесс, и молча
        завести его вместо заказанного нельзя.
        """
        if buyer is not None and cfo is not None:
            buyer_side = {"approver_kind": "position", "position_ids": [buyer]}
            cfo_side = {"approver_kind": "position", "position_ids": [cfo]}
            quorum = "any"
        elif buyer_user is not None and cfo_user is not None:
            buyer_side = {"approver_kind": "users", "user_ids": [buyer_user]}
            cfo_side = {"approver_kind": "users", "user_ids": [cfo_user]}
            quorum = "all"
        else:
            return None

        stages = [
            {"order": order, "name": name, "quorum": quorum,
             "requires_attachment": needs_file,
             "requires_comment": needs_note,
             "requirement_key": requirement, **buyer_side}
            for order, (name, needs_file, needs_note, requirement)
            in enumerate(BUYER_STAGES, start=1)
        ]
        stages.append({"order": len(BUYER_STAGES) + 1, "name": STAGE_CFO,
                       "quorum": quorum, **cfo_side})
        return stages
