"""
Рассылка «Контент-марафон межсезонье» от 10.11.2025: картинка + текст + кнопка.
Запуск: python3 broadcast_marathon_20251110.py [admins|all]

- admins (по умолчанию): отправка только ADMIN_IDS для теста
- all: отправка всем активным пользователям (User.is_blocked == 0)

По завершении автоматически отправляется отчёт администраторам:
- время выполнения, счётчики отправлено/пропущено/заблокировано/ошибок,
- процент успешности,
- краткие списки заблокированных и пользователей с ошибками,
- путь к лог-файлу.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from config import BOT_TOKEN
from database.config import AsyncSessionLocal
from database.models import User
from database.crud import mark_user_as_blocked
from utils.constants import ADMIN_IDS

logger = logging.getLogger("broadcast_marathon")
logger.setLevel(logging.INFO)
log_filename = f"broadcast_marathon_20251110_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_fh = logging.FileHandler(log_filename)
_fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.handlers = []
logger.addHandler(_fh)
logger.addHandler(_sh)

bot = Bot(token=BOT_TOKEN)

IMAGE_PATH = Path("media/broadcast10112025.JPG")

# Текст с форматированием как на скриншоте
BROADCAST_TEXT_HTML = (
    "<b>ДОРОГИЕ, ДОБРО ПОЖАЛОВАТЬ В НОВЫЙ КОНТЕНТ-МАРАФОН ПОСВЯЩЕННЫЙ МЕЖСЕЗОНЬЮ ❄️</b>\n\n"
    "📸 Контент-марафон — это челлендж по созданию контента в блог. \n"
    "Ой, девочки, готовьтесь🤗 Мы будем много снимать, креативить, \n"
    "учиться замечать и подготовим ваши блоги к новому сезону🎄\n\n"
    "<b>Что вас ждет:</b>\n\n"
    "1. 3 контент задания\n"
    "2. подборки референсов > бери & повторяй\n"
    "3. обратная связь на каждую работу > учимся снимать\n\n"
    "🏆 в конце мы выберем победителя нашего марафона с 🎁"
)


def build_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🤎 Приобрести подписку", callback_data="subscribe")]]
    )


async def send_to_users(user_ids: Iterable[int]):
    if not IMAGE_PATH.exists():
        logger.error(f"Изображение не найдено: {IMAGE_PATH} (pwd={Path.cwd()})")
    photo = FSInputFile(str(IMAGE_PATH)) if IMAGE_PATH.exists() else None

    sent, skipped, blocked_count, error_count = 0, 0, 0, 0
    error_details: dict[str, int] = {}
    blocked_users: list[dict] = []
    error_users: list[dict] = []

    async with AsyncSessionLocal() as session:
        for tg_id in user_ids:
            user = None
            try:
                result = await session.execute(select(User).where(User.telegram_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    skipped += 1
                    continue

                kb = build_keyboard()
                # 1) Фото без кнопки
                if photo:
                    await bot.send_photo(chat_id=tg_id, photo=photo)
                # 2) Текст с кнопкой
                await bot.send_message(
                    chat_id=tg_id,
                    text=BROADCAST_TEXT_HTML,
                    reply_markup=kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                msg = str(e)
                if "bot was blocked by the user" in msg or "USER_IS_BLOCKED" in msg:
                    blocked_count += 1
                    try:
                        if user:
                            await mark_user_as_blocked(session, user.id)
                    except Exception:
                        pass
                    logger.warning(f"Пользователь {tg_id} заблокировал бота")
                    blocked_users.append({
                        "telegram_id": tg_id,
                        "username": getattr(user, "username", None) if user else None,
                        "id": getattr(user, "id", None) if user else None,
                    })
                else:
                    error_count += 1
                    if "user is deactivated" in msg:
                        error_details["user is deactivated"] = error_details.get("user is deactivated", 0) + 1
                    else:
                        error_details["other"] = error_details.get("other", 0) + 1
                    logger.error(f"Ошибка отправки пользователю {tg_id}: {e}")
                    error_users.append({
                        "telegram_id": tg_id,
                        "username": getattr(user, "username", None) if user else None,
                        "id": getattr(user, "id", None) if user else None,
                        "error": msg,
                    })
                await asyncio.sleep(0.05)

    logger.info(
        f"ИТОГО: отправлено={sent}, пропущено={skipped}, заблокировано={blocked_count}, ошибок={error_count}"
    )
    return {
        "sent": sent,
        "skipped": skipped,
        "blocked": blocked_count,
        "errors": error_count,
        "error_details": error_details,
        "blocked_users": blocked_users,
        "error_users": error_users,
    }


def _format_report(stats: dict, total: int, start: datetime, end: datetime) -> str:
    duration: timedelta = end - start
    minutes, seconds = divmod(int(duration.total_seconds()), 60)
    err_details = stats.get("error_details") or {}
    err_lines = []
    for k, v in err_details.items():
        err_lines.append(f"— {k}: {v}")
    err_section = "\n".join(err_lines) if err_lines else "— нет"

    def fmt_user(u: dict) -> str:
        uname = u.get("username")
        uname_part = f" (@{uname})" if uname else ""
        return f"ID: {u.get('telegram_id')}" + uname_part

    blocked_list = stats.get("blocked_users") or []
    error_list = stats.get("error_users") or []
    blocked_preview = "\n".join([fmt_user(u) for u in blocked_list[:30]]) or "— нет"
    if len(blocked_list) > 30:
        blocked_preview += f"\n… и ещё {len(blocked_list) - 30}"
    errors_preview = "\n".join(
        [f"ID: {u.get('telegram_id')} ({u.get('error')})" for u in error_list[:20]]
    ) or "— нет"
    if len(error_list) > 20:
        errors_preview += f"\n… и ещё {len(error_list) - 20}"

    sent = stats.get("sent", 0)
    success_rate = (sent / total * 100) if total else 0.0
    report = (
        "<b>ОТЧЁТ О РАССЫЛКЕ</b>\n"
        f"Файл лога: <code>{log_filename}</code>\n\n"
        f"🧮 <b>ОБЩАЯ СТАТИСТИКА</b>:\n"
        f"Всего пользователей: {total}\n"
        f"✅ Отправлено: {sent}\n"
        f"⏭️ Пропущено: {stats['skipped']}\n"
        f"⛔ Заблокированы: {stats['blocked']}\n"
        f"❌ Ошибок: {stats['errors']}\n"
        f"📈 Успешность: {success_rate:.1f}%\n"
        f"⏱️ Время выполнения: {minutes:02d}:{seconds:02d}\n\n"
        f"🧩 Детали ошибок:\n{err_section}\n\n"
        f"⛔ <b>ЗАБЛОКИРОВАННЫЕ ПОЛЬЗОВАТЕЛИ</b>:\n{blocked_preview}\n\n"
        f"❌ <b>ОШИБКИ ОТПРАВКИ</b>:\n{errors_preview}"
    )
    return report


async def notify_admins_report(stats: dict, total: int, start: datetime, end: datetime):
    text = _format_report(stats, total, start, end)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось отправить отчёт админу {admin_id}: {e}")


async def send_to_admins():
    logger.info("Тестовая рассылка администраторам")
    start = datetime.now()
    total = len(ADMIN_IDS)
    stats = {"sent": 0, "skipped": 0, "blocked": 0, "errors": 0, "error_details": {}, "blocked_users": [], "error_users": []}
    try:
        stats = await send_to_users(ADMIN_IDS)
    except Exception as e:
        logger.exception(f"Fatal error during admins send: {e}")
    finally:
        end = datetime.now()
        await notify_admins_report(stats, total, start, end)


async def send_to_all():
    logger.info("Боевая рассылка всем пользователям")
    start = datetime.now()
    ids: list[int] = []
    total = 0
    stats = {"sent": 0, "skipped": 0, "blocked": 0, "errors": 0, "error_details": {}, "blocked_users": [], "error_users": []}
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User.telegram_id).where(User.is_blocked == 0))
            ids = [tg_id for (tg_id,) in result]
        total = len(ids)
        stats = await send_to_users(ids)
    except Exception as e:
        # Ловим любые фатальные ошибки и всё равно шлём отчёт
        logger.exception(f"Fatal error during all-users send: {e}")
    finally:
        end = datetime.now()
        await notify_admins_report(stats, total, start, end)


async def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "admins"
    if mode == "all":
        await send_to_all()
    else:
        await send_to_admins()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())