"""``manage.py onec_check`` — диагностика связи с 1С (A7.3, D-38, D-S7-5).

Печатает конфигурацию (без пароля), проверяет связь и читает ОДНУ запись
справочников контрагентов и проектов. Ничего не пишет. Без адреса —
«выключено» (код 0). Имена наборов сущностей — предположение до ответа
администратора 1С (Q-S7-2), меняются опциями.

    manage.py onec_check [--counterparties Catalog_Контрагенты]
                         [--projects Catalog_Проекты]
"""
from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from htqweb.integrations import onec


class Command(BaseCommand):
    help = "Проверить связь с 1С (OData): конфигурация без пароля и чтение одной записи."

    def add_arguments(self, parser):
        parser.add_argument("--counterparties", default="Catalog_Контрагенты")
        parser.add_argument("--projects", default="Catalog_Проекты")

    def handle(self, *args, **opts):
        url = settings.ONEC_ODATA_URL
        host = urlsplit(url).hostname if url else ""
        self.stdout.write(f"ONEC_ODATA_URL: {'задан, сервер ' + str(host) if url else 'не задан'}")
        self.stdout.write(f"ONEC_USER: {settings.ONEC_USER or 'не задан'}")
        self.stdout.write(f"ONEC_PASSWORD: {'задан' if settings.ONEC_PASSWORD else 'не задан'}")
        self.stdout.write(f"ONEC_TIMEOUT: {settings.ONEC_TIMEOUT}")
        try:
            client = onec.OneCClient.from_settings()
        except onec.OneCDisabled:
            self.stdout.write("Интеграция с 1С выключена (адрес не задан).")
            return
        except onec.OneCConfigError as exc:
            raise CommandError(str(exc)) from None
        failed = False
        try:
            for title, entity in (("контрагенты", opts["counterparties"]),
                                  ("проекты", opts["projects"])):
                try:
                    row = client.read_one(entity)
                except onec.OneCODataError as exc:
                    failed = True
                    self.stdout.write(f"  [FAIL] {title} ({entity}): ошибка OData {exc.code}: {exc}")
                except onec.OneCUnavailable as exc:
                    failed = True
                    self.stdout.write(f"  [FAIL] {title} ({entity}): {exc}")
                else:
                    state = "запись прочитана" if row else "набор пуст"
                    self.stdout.write(f"  [ ok ] {title} ({entity}): {state}")
        finally:
            client.close()
        if failed:
            raise CommandError("Проверка связи с 1С не пройдена.")
