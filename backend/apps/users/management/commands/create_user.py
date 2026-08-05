"""Завести одну платформенную учётку из командной строки.

Зачем: публичная регистрация (``POST /api/users/v1/register/``) создаёт
пользователя в статусе ``PENDING``, а войти с ним нельзя, пока админ не
одобрит заявку — ``auth_service`` отдаёт 401 «Account is not activated».
Для разовых сценариев (гость на время теста, разработчик без учётки) это
лишний круг: нужен работающий логин прямо сейчас, без веб-интерфейса и без
admin-токена.

Пароль хеширует ``apps.users.services.admin_service.create_user`` — та же
функция, что стоит за ``POST admin/users/``, поэтому проверки уникальности
email/username и допустимости статуса здесь ровно те же, что в API.

По умолчанию ``must_change_password`` НЕ ставится: учётка заводится для
немедленного входа, а не для передачи сотруднику под смену пароля.
"""
from __future__ import annotations

import secrets
import string

from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User
from apps.users.services import admin_service

# Достаточно длинный, чтобы пройти минимум в 8 символов и не подбираться,
# и без похожих символов — пароль диктуют голосом или шлют в мессенджер.
_PASSWORD_ALPHABET = string.ascii_letters.replace("l", "").replace("O", "") + string.digits.replace("0", "").replace("1", "")
_GENERATED_PASSWORD_LENGTH = 14


def _generate_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_GENERATED_PASSWORD_LENGTH))


class Command(BaseCommand):
    help = (
        "Создать платформенную учётку, готовую к входу (status=active). "
        "Пароль можно задать явно или получить сгенерированный."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", required=True, help="E-mail, он же логин по умолчанию")
        parser.add_argument(
            "--username",
            default=None,
            help="Имя пользователя (по умолчанию — e-mail в нижнем регистре)",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Пароль (минимум 8 символов). Без него будет сгенерирован и напечатан",
        )
        parser.add_argument(
            "--name",
            default="",
            help='Отображаемое имя, например "Иван Петров"',
        )
        parser.add_argument(
            "--staff",
            action="store_true",
            help="Выдать права сотрудника платформы (is_staff)",
        )
        parser.add_argument(
            "--reset-if-exists",
            action="store_true",
            help=(
                "Если учётка с таким e-mail уже есть — не падать, а сбросить ей "
                "пароль и вернуть в status=active. Нужно для повторных запусков "
                "скриптов: сгенерированный пароль нигде не хранится, и без "
                "сброса второй запуск оставил бы учётку, в которую не войти"
            ),
        )

    def handle(self, *args, **options) -> None:
        email = (options["email"] or "").strip().lower()
        if "@" not in email:
            raise CommandError(f"Похоже, это не e-mail: {email!r}")

        password = options["password"] or _generate_password()
        if len(password) < 8:
            raise CommandError("Пароль короче 8 символов — такой не примет и API")

        username = (options["username"] or email).strip()
        full_name = (options["name"] or "").strip()
        first_name, _, last_name = full_name.partition(" ")

        try:
            user = admin_service.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                display_name=full_name,
                status="active",
                is_staff=options["staff"],
                must_change_password=False,
            )
        except admin_service.DuplicateEmail:
            if not options["reset_if_exists"]:
                raise CommandError(f"Пользователь с e-mail {email} уже существует")
            user = self._reset_existing(email=email, password=password)
        except admin_service.DuplicateUsername:
            raise CommandError(f"Пользователь с именем {username} уже существует")
        else:
            self.stdout.write(self.style.SUCCESS(f"Учётка создана (id={user.id}, status=active)"))

        self.stdout.write(f"  логин:  {user.username}")
        self.stdout.write(f"  пароль: {password}")
        if options["password"] is None:
            self.stdout.write("  (пароль сгенерирован — сохраните, повторно он не покажется)")

    def _reset_existing(self, *, email: str, password: str) -> User:
        """Вернуть существующую учётку в пригодное для входа состояние.

        Статус выставляем не через ``setattr``: ``update_user`` валидирует
        значение, а ``CharField(choices=...)`` на ``.save()`` этого не делает
        и молча записал бы мусор, заблокировав вход.
        """
        user = User.objects.get(email=email)
        admin_service.set_password(user, new_password=password, must_change_password=False)
        if user.status != "active":
            user = admin_service.update_user(user, {"status": "active"})
        self.stdout.write(self.style.SUCCESS(f"Учётка уже была (id={user.id}) — пароль сброшен, status=active"))
        return user
