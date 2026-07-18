r"""Seed demo data for HR sidebar pages: Уровни / Должности / Оргструктура / PMO.

Тонкая CLI-обёртка над ``app.services.demo_seed_service``. Логика и
референсные данные живут в сервисе — этот файл ничего своего не создаёт,
только вызывает соответствующие функции и комитит транзакцию.

Запуск (локальный dev, БД доступна по DSN из settings):

    python -m pip install -r requirements.txt     # один раз, если в venv нет SQLAlchemy
    python -m scripts.seed_demo                   # из services/hr/

Docker из корня репозитория:

    docker compose build hr-service               # один раз после добавления scripts/
    docker compose run --rm --no-deps hr-service python -m scripts.seed_demo

В обычном dev-режиме скрипт можно вообще не запускать: при старте сервиса в
не-production окружении lifespan-хук в ``app/main.py`` сам зальёт данные
один раз. Этот скрипт нужен, когда хочется (а) явно запустить seed на
локальной машине без поднятия сервиса или (б) принудительно пересоздать
демо-записи флагом ``--force`` / ``--reset``.

Флаги:

    --force   Перезалить даже если демо-данные уже присутствуют (upsert).
    --reset   Сначала снести демо-записи (`@hitech.demo`, `PMO-*`,
              seed-должности, seed-департаменты), потом залить заново.
              Реальные строки не трогаются.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python services/hr/scripts/seed_demo.py` and `python -m scripts.seed_demo`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import async_session_factory  # noqa: E402
from app.services.demo_seed_service import (  # noqa: E402
    reset_demo_data,
    seed_demo_data,
)


async def _run(*, force: bool, reset: bool) -> None:
    async with async_session_factory() as session:
        try:
            if reset:
                await reset_demo_data(session)
                # Reset clears the marker, so the seed proceeds without --force.
            result = await seed_demo_data(session, force=force or reset)
            await session.commit()
            print(f"Seed result: {result}")
        except Exception:
            await session.rollback()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезалить даже если демо уже есть (upsert).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Снести демо перед заливкой. Реальные данные не трогает.",
    )
    args = parser.parse_args()
    asyncio.run(_run(force=args.force, reset=args.reset))


if __name__ == "__main__":
    main()
