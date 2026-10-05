"""Снять блокировку входа по логину (D-S7-3) — для дежурного.

``manage.py auth_unlock <логин>``: сбрасывает счётчик неудач и действующую
блокировку. Логин — как его вводят на входе (имя пользователя или e-mail);
если такая учётка есть, сбрасываются оба её логина (имя и e-mail).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from apps.users.services import auth_service
from htqweb import ratelimit


class Command(BaseCommand):
    help = "Снять блокировку входа по логину (имя пользователя или e-mail)."

    def add_arguments(self, parser):
        parser.add_argument("login", help="логин, как его вводят на входе")

    def handle(self, *args, **options):
        login = options["login"]
        logins = {login}
        user = auth_service.find_user(login)
        if user is not None:
            logins |= {user.username, user.email}
        for item in logins:
            if item:
                ratelimit.reset_login(item)
        self.stdout.write(self.style.SUCCESS(f"Блокировка входа снята: {login}"))
