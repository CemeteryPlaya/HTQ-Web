"""Переезд согласования заявок со старого движка графов на ``apps.signoff``.

Одноразовая команда перехода (Фаза 4 плана). По каждому шаблону с текущей
версией переводит ``workflow_json`` в маршрут signoff области
``template:<id>`` (``services/workflow_convert.py``), а заявки, застигнутые
«на согласовании» в старом движке, перезапускает с первого этапа нового
маршрута — решение заказчика: один движок сразу, повторные одобрения лучше
двух очередей «ждёт меня».

Идемпотентна: шаблон, у которого маршрут в области уже есть, пропускается;
заявка, у которой уже идёт процесс signoff, не перезапускается.

    manage.py migrate_workflows_to_signoff --dry-run     # отчёт, без записи
    manage.py migrate_workflows_to_signoff               # прогон
    manage.py migrate_workflows_to_signoff --template 7  # один шаблон

Непереносимый граф — в отчёт с причиной; маршрут для него не создаётся
(отправка даст 409 «не настроен маршрут», пока администратор не настроит его
руками), а его заявки «в пути» возвращаются инициатору (``returned``) с
пояснением в ленте.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.approvals.approval_hooks import scope_for_template
from apps.approvals.models import (
    ApprovalAction,
    ApprovalActionType,
    RequestActivity,
    RequestFormTemplate,
    RequestFormTemplateVersion,
    RequestInstance,
    RequestStatus,
    TemplateStatus,
)
from apps.approvals.services import request_runtime
from apps.approvals.services.workflow_convert import convert_graph
from apps.signoff import interface as signoff

EVENT_MIGRATED = "migrated_to_signoff"


class Command(BaseCommand):
    help = "Перевести маршруты шаблонов и заявки «в пути» на движок signoff"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Только отчёт, без записи в БД")
        parser.add_argument("--template", type=int, default=None,
                            help="Только один шаблон (id)")

    def handle(self, *args, dry_run: bool = False, template: int | None = None, **options):
        self.dry_run = dry_run
        query = (RequestFormTemplate.objects
                 .exclude(status=TemplateStatus.DELETED)
                 .order_by("id"))
        if template is not None:
            query = query.filter(pk=template)

        totals = {"routes": 0, "skipped": 0, "manual": 0,
                  "restarted": 0, "returned": 0}
        for tpl in query:
            self._one_template(tpl, totals)

        self.stdout.write("")
        self.stdout.write(
            f"Итог: маршрутов создано {totals['routes']}, уже были {totals['skipped']}, "
            f"вручную {totals['manual']}; заявок перезапущено {totals['restarted']}, "
            f"возвращено инициатору {totals['returned']}"
            + (" (dry-run, ничего не записано)" if dry_run else ""))

    # ── шаблон ───────────────────────────────────────────────────────────

    def _one_template(self, tpl: RequestFormTemplate, totals: dict) -> None:
        scope = scope_for_template(tpl.pk)
        head = f"[{tpl.pk}] «{tpl.name}»"
        version = (RequestFormTemplateVersion.objects
                   .filter(pk=tpl.current_version_id).first()
                   if tpl.current_version_id else None)

        has_route = signoff.has_active_route(RequestInstance.SIGNOFF_SUBJECT_TYPE, scope)
        if has_route:
            self.stdout.write(f"{head}: маршрут уже есть — пропуск")
            totals["skipped"] += 1
        elif version is None or not version.workflow_json:
            self.stdout.write(f"{head}: нет версии или графа — маршрут настраивается вручную")
            totals["manual"] += 1
            has_route = False
        else:
            has_route = self._convert(tpl, version.workflow_json, scope, head, totals)

        self._restart_pending(tpl, has_route, head, totals)

    def _convert(self, tpl, workflow_json: dict, scope: str, head: str,
                 totals: dict) -> bool:
        result = convert_graph(workflow_json)
        if not result.ok:
            for problem in result.problems:
                self.stdout.write(self.style.WARNING(f"{head}: НЕ переносится — {problem}"))
            totals["manual"] += 1
            return False

        plan = "; ".join(
            f"{spec.order}. {spec.name} [{spec.approver_kind}"
            + (f" {spec.user_ids}" if spec.user_ids else "")
            + (f" {spec.approver_key}" if spec.approver_key else "")
            + (", условие" if spec.condition else "")
            + (", иначе" if spec.is_fallback else "") + "]"
            for spec in result.stages)
        if self.dry_run:
            self.stdout.write(f"{head}: маршрут → {plan}")
            totals["routes"] += 1
            return True

        try:
            signoff.configure_route(
                subject_type=RequestInstance.SIGNOFF_SUBJECT_TYPE, scope=scope,
                name=f"Маршрут «{tpl.name}»",
                stages=[{
                    "order": spec.order, "name": spec.name, "quorum": spec.quorum,
                    "position_ids": spec.position_ids, "condition": spec.condition,
                    "is_fallback": spec.is_fallback, "approver_kind": spec.approver_kind,
                    "user_ids": spec.user_ids, "approver_key": spec.approver_key,
                } for spec in result.stages])
        except signoff.RouteConflict as exc:
            # Например, названный поимённо согласующий уже уволен: маршрут
            # такой signoff не примет — и правильно, его чинит человек.
            self.stdout.write(self.style.WARNING(
                f"{head}: маршрут не принят движком — {exc}"))
            totals["manual"] += 1
            return False

        self.stdout.write(self.style.SUCCESS(f"{head}: маршрут создан → {plan}"))
        totals["routes"] += 1
        return True

    # ── заявки в пути ────────────────────────────────────────────────────

    def _restart_pending(self, tpl, has_route: bool, head: str, totals: dict) -> None:
        pending = list(RequestInstance.objects.filter(
            template=tpl, status=RequestStatus.PENDING).order_by("id"))
        for instance in pending:
            if signoff.get_process_for(RequestInstance.SIGNOFF_SUBJECT_TYPE,
                                       instance.pk) is not None:
                continue  # уже на новом движке
            approved_by = list(ApprovalAction.objects.filter(
                request=instance, action=ApprovalActionType.APPROVE,
                acted_at__isnull=False).values_list("approver_id", flat=True))
            note = {"node": instance.current_node_id, "approved_by": approved_by}

            if self.dry_run:
                verb = "перезапуск с первого этапа" if has_route else "возврат инициатору"
                self.stdout.write(f"{head}: заявка {instance.code} — {verb}"
                                  f" (ранее одобрили: {approved_by or '—'})")
                totals["restarted" if has_route else "returned"] += 1
                continue

            with transaction.atomic():
                ApprovalAction.objects.filter(
                    request=instance, acted_at__isnull=True).update(
                    action=ApprovalActionType.AUTO_SKIP, acted_at=timezone.now())
                if has_route:
                    instance.status = RequestStatus.DRAFT
                    instance.current_node_id = None
                    instance.requires_admin_attention = False
                    instance.save(update_fields=["status", "current_node_id",
                                                 "requires_admin_attention", "updated_at"])
                    RequestActivity.objects.create(
                        request=instance, event_type=EVENT_MIGRATED, actor_id=None,
                        payload={**note, "action": "restarted"})
                    try:
                        request_runtime.submit(instance, actor_id=instance.initiator_id)
                    except (request_runtime.RuntimeConflict,
                            request_runtime.RuntimeRejected) as exc:
                        # Маршрут есть, но заявку он не принял (уволенный
                        # согласующий, несошедшаяся ветка) — возвращаем.
                        self._return(instance, note, str(exc))
                        self.stdout.write(self.style.WARNING(
                            f"{head}: заявка {instance.code} возвращена инициатору — {exc}"))
                        totals["returned"] += 1
                        continue
                    self.stdout.write(f"{head}: заявка {instance.code} перезапущена")
                    totals["restarted"] += 1
                else:
                    self._return(instance, note,
                                 "маршрут шаблона не перенесён — настройте его и "
                                 "отправьте заявку заново")
                    self.stdout.write(f"{head}: заявка {instance.code} возвращена инициатору")
                    totals["returned"] += 1

    @staticmethod
    def _return(instance: RequestInstance, note: dict, reason: str) -> None:
        instance.status = RequestStatus.RETURNED
        instance.approval_state = signoff.ApprovalState.REWORK
        instance.current_node_id = None
        instance.requires_admin_attention = False
        instance.save(update_fields=["status", "approval_state", "current_node_id",
                                     "requires_admin_attention", "updated_at"])
        RequestActivity.objects.create(
            request=instance, event_type=EVENT_MIGRATED, actor_id=None,
            payload={**note, "action": "returned", "reason": reason})
