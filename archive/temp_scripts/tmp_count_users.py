#!/usr/bin/env python3
"""
Временный отчёт по пользователям для рассылки.
Печатает агрегированные метрики из БД, без отправки сообщений.

Запуск локально: python3 tmp_count_users.py
На сервере: ./venv/bin/python3 tmp_count_users.py
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select, func

from database.config import AsyncSessionLocal
from database.models import User
from utils.constants import ADMIN_IDS


async def main():
    async with AsyncSessionLocal() as s:
        total = (await s.execute(select(func.count()).select_from(User))).scalar() or 0
        active = (
            await s.execute(select(func.count()).select_from(User).where(User.is_blocked == 0))
        ).scalar() or 0
        blocked = total - active

        admins_total = (
            await s.execute(select(func.count()).select_from(User).where(User.telegram_id.in_(ADMIN_IDS)))
        ).scalar() or 0

        admins_blocked = (
            await s.execute(
                select(func.count())
                .select_from(User)
                .where(User.telegram_id.in_(ADMIN_IDS), User.is_blocked == 1)
            )
        ).scalar() or 0

        # Недавно обновлённые блокировки (предполагаем, что рассылка могла обновить флаг)
        window_start = datetime.now() - timedelta(hours=1)
        recent_blocked = (
            await s.execute(
                select(func.count())
                .select_from(User)
                .where(User.is_blocked == 1, User.updated_at != None, User.updated_at >= window_start)
            )
        ).scalar() or 0

        print("=== USERS BROADCAST SUMMARY ===")
        print(f"TOTAL_USERS={total}")
        print(f"ACTIVE_NONBLOCKED={active}")
        print(f"BLOCKED_FLAGGED={blocked}")
        print(f"ADMINS_IN_DB={admins_total} (blocked={admins_blocked})")
        print(f"RECENT_BLOCKED_LAST_1H={recent_blocked}")


if __name__ == "__main__":
    asyncio.run(main())