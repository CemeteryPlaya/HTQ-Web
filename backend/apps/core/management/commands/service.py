from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import KNOWN_SERVICES, ServiceStatus


class Command(BaseCommand):
    help = "Включить/выключить сервис в реестре ServiceStatus (рубильник для операторов)."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Имя сервиса (app_label), например: cms, hr, users")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--on", action="store_true", help="Включить сервис")
        group.add_argument("--off", action="store_true", help="Выключить сервис")
        parser.add_argument(
            "--message",
            default=None,
            help="Сообщение, которое увидят клиенты, пока сервис выключен",
        )

    def handle(self, *args, **options):
        name = options["name"]
        if name not in KNOWN_SERVICES:
            raise CommandError(
                f"Неизвестный сервис '{name}'. Допустимые имена: "
                f"{', '.join(KNOWN_SERVICES)}"
            )
        enabled = bool(options["on"])
        message = options.get("message")

        defaults = {"enabled": enabled}
        if message is not None:
            defaults["message"] = message

        status, created = ServiceStatus.objects.update_or_create(
            app_label=name, defaults=defaults
        )

        cache.delete(f"svc-status:{name}")

        state = "включён" if status.enabled else "выключен"
        self.stdout.write(self.style.SUCCESS(
            f"Сервис '{name}' {state} ({'создан' if created else 'обновлён'})."
        ))
