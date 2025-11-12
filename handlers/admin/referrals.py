from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from utils.constants import ADMIN_IDS
from utils.admin_permissions import is_admin
from utils.helpers import html_kv, fmt_date, admin_nav_back
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)

# Отдельный роутер для реферальных функций админки
referrals_router = Router()


class AdminReferralsStates(StatesGroup):
    waiting_user = State()


def register_admin_referrals_handlers(dp):
    dp.include_router(referrals_router)


@referrals_router.callback_query(F.data == "admin_referral_info")
async def admin_referral_info_start(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[referrals] admin_referral_info by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return

    page = 0
    page_size = 10
    from database.models import User, PaymentLog, Subscription

    async with AsyncSessionLocal() as session:
        total_q = await session.execute(select(User).where(User.referrer_id.isnot(None)))
        all_referees = total_q.scalars().all()

        # Показываем только пользователей с начисленными реферальными бонусами
        eligible_users = []
        for user in all_referees:
            ref_q = await session.execute(select(User).where(User.id == user.referrer_id))
            referrer = ref_q.scalars().first()
            if not referrer:
                continue

            ref_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == referrer.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_for_{user.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            ref_bonus = ref_bonus_q.scalars().first()

            self_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == user.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_self_from_{referrer.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            self_bonus = self_bonus_q.scalars().first()

            if ref_bonus or self_bonus:
                eligible_users.append(user)

        total = len(eligible_users)
        start = page * page_size
        end = start + page_size
        page_items = eligible_users[start:end]

        lines = ["<b>🤝 Реферальные связи</b>"]
        if total == 0:
            lines.append("Нет реферальных связей.")
        else:
            lines.append(html_kv("Всего", f"{total} (показаны {start+1}–{min(end, total)})"))

        # Кнопки выбора пользователей
        user_buttons = []
        for u in page_items:
            btn_text = f"👤 @{u.username or 'без никнейма'} (ID: {u.telegram_id})"
            user_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_referral_user_compact:{u.id}:{page}")])

        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"admin_referrals_page:{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"- {page+1}/{total_pages} -", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️ След.", callback_data=f"admin_referrals_page:{page+1}"))

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                *user_buttons,
                nav_row,
                [InlineKeyboardButton(text="🔎 Поиск по пользователю", callback_data="admin_referral_search")],
                [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]
            ]
        )

        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@referrals_router.callback_query(F.data.startswith("admin_referrals_page:"))
async def admin_referrals_paginate(callback: CallbackQuery):
    logger.info(f"[referrals] admin_referrals_page: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return

    try:
        page = int(callback.data.split(":")[1])
    except Exception:
        page = 0

    page_size = 10
    from database.models import User, PaymentLog
    async with AsyncSessionLocal() as session:
        total_q = await session.execute(select(User).where(User.referrer_id.isnot(None)))
        all_referees = total_q.scalars().all()

        eligible_users = []
        for user in all_referees:
            ref_q = await session.execute(select(User).where(User.id == user.referrer_id))
            referrer = ref_q.scalars().first()
            if not referrer:
                continue
            ref_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == referrer.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_for_{user.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            ref_bonus = ref_bonus_q.scalars().first()
            self_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == user.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_self_from_{referrer.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            self_bonus = self_bonus_q.scalars().first()
            if ref_bonus or self_bonus:
                eligible_users.append(user)

        total = len(eligible_users)
        start = page * page_size
        end = start + page_size
        page_items = eligible_users[start:end]

        lines = ["<b>🤝 Реферальные связи</b>"]
        if total == 0:
            lines.append("Нет реферальных связей.")
        else:
            lines.append(html_kv("Всего", f"{total} (показаны {start+1}–{min(end, total)})"))

        user_buttons = []
        for u in page_items:
            btn_text = f"👤 @{u.username or 'без никнейма'} (ID: {u.telegram_id})"
            user_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_referral_user_compact:{u.id}:{page}")])

        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"admin_referrals_page:{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"- {page+1}/{total_pages} -", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️ След.", callback_data=f"admin_referrals_page:{page+1}"))

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                *user_buttons,
                nav_row,
                [InlineKeyboardButton(text="🔎 Поиск по пользователю", callback_data="admin_referral_search")],
                [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]
            ]
        )

        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@referrals_router.callback_query(F.data == "admin_referral_search")
async def admin_referral_search(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[referrals] admin_referral_search by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    await state.set_state(AdminReferralsStates.waiting_user)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]])
    await callback.message.answer("Введите Telegram ID или @username пользователя:", reply_markup=keyboard)
    await callback.answer()


@referrals_router.message(StateFilter(AdminReferralsStates.waiting_user))
async def admin_referral_info_show(message: types.Message, state: FSMContext):
    logger.info(f"[referrals] referral_waiting_user text='{message.text}' by {message.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not is_admin(user):
            return

    search = message.text.strip()
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_username, get_user_by_telegram_id
        from database.models import User, PaymentLog, Subscription

        user = None
        if search.startswith('@'):
            user = await get_user_by_username(session, search[1:])
        else:
            try:
                tid = int(search)
                user = await get_user_by_telegram_id(session, tid)
            except ValueError:
                await message.answer("❌ Некорректный формат! Введите числовой ID или username с символом @")
                return

        if not user:
            await message.answer(f"❌ Пользователь не найден: {search}")
            await state.clear()
            return

        sub_q = await session.execute(
            select(Subscription).where(Subscription.user_id == user.id, Subscription.is_active == 1).order_by(Subscription.end_date.desc())
        )
        user_sub = sub_q.scalars().first()
        user_end = user_sub.end_date.strftime('%d.%m.%Y') if user_sub else 'N/A'

        referrer = None
        if user.referrer_id:
            ref_q = await session.execute(select(User).where(User.id == user.referrer_id))
            referrer = ref_q.scalars().first()

        ref_bonus_log = None
        self_bonus_log = None
        if referrer:
            ref_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == referrer.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_for_{user.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            ref_bonus_log = ref_bonus_q.scalars().first()

            self_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == user.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_self_from_{referrer.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            self_bonus_log = self_bonus_q.scalars().first()

        import re
        def extract_days(log):
            try:
                m = re.search(r"(\d+)\s*дн", getattr(log, 'details', '') or '')
                return int(m.group(1)) if m else None
            except Exception:
                return None
        ref_days = extract_days(ref_bonus_log) if ref_bonus_log else None
        self_days = extract_days(self_bonus_log) if self_bonus_log else None

        lines = ["<b>🤝 Реферальная информация</b>"]
        lines.append(html_kv("Пользователь", f"{user.first_name or ''} (@{user.username or 'без никнейма'})"))
        if referrer:
            lines.append(html_kv("Пригласил", f"{referrer.first_name or ''} (@{referrer.username or 'без никнейма'})"))

        if referrer:
            ref_sub_q = await session.execute(select(Subscription).where(Subscription.user_id == referrer.id, Subscription.is_active == 1).order_by(Subscription.end_date.desc()))
            ref_sub = ref_sub_q.scalars().first()
            ref_end = ref_sub.end_date.strftime('%d.%m.%Y') if ref_sub else 'N/A'
            lines.append(html_kv("📆 Сроки", f"реферер до {ref_end}, реферал до {user_end}"))
        else:
            lines.append(html_kv("📆 Срок реферала", f"до {user_end}"))

        if referrer:
            lines.append(html_kv("🎁 Бонусы", f"рефереру +{ref_days or 7} дней, рефералу +{self_days or 7} дней"))

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✖️ Закрыть", callback_data=f"admin_close")]])
        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
        await state.clear()


@referrals_router.callback_query(F.data.startswith("admin_referral_user_compact:"))
async def admin_referral_user_details_compact(callback: CallbackQuery):
    logger.info(f"[referrals] admin_referral_user_compact: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    parts = callback.data.split(":")
    try:
        user_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    from database.models import User, PaymentLog, Subscription
    async with AsyncSessionLocal() as session:
        user_q = await session.execute(select(User).where(User.id == user_id))
        user = user_q.scalars().first()
        if not user:
            await callback.message.answer("Пользователь не найден")
            await callback.answer()
            return

        sub_q = await session.execute(select(Subscription).where(Subscription.user_id == user.id, Subscription.is_active == 1).order_by(Subscription.end_date.desc()))
        user_sub = sub_q.scalars().first()
        user_end = user_sub.end_date.strftime('%d.%m.%Y') if user_sub else 'N/A'

        referrer = None
        if user.referrer_id:
            ref_q = await session.execute(select(User).where(User.id == user.referrer_id))
            referrer = ref_q.scalars().first()

        ref_bonus_log = None
        self_bonus_log = None
        if referrer:
            ref_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == referrer.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_for_{user.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            ref_bonus_log = ref_bonus_q.scalars().first()

            self_bonus_q = await session.execute(
                select(PaymentLog).where(
                    PaymentLog.user_id == user.id,
                    PaymentLog.payment_method == 'bonus',
                    PaymentLog.details.like(f"%referral_bonus_self_from_{referrer.id}%")
                ).order_by(PaymentLog.id.desc())
            )
            self_bonus_log = self_bonus_q.scalars().first()

        import re
        def extract_days(log):
            try:
                m = re.search(r"(\d+)\s*дн", getattr(log, 'details', '') or '')
                return int(m.group(1)) if m else None
            except Exception:
                return None
        ref_days = extract_days(ref_bonus_log) if ref_bonus_log else None
        self_days = extract_days(self_bonus_log) if self_bonus_log else None

        lines = ["<b>🤝 Реферальная информация</b>"]
        lines.append(html_kv("Пользователь", f"{user.first_name or ''} (@{user.username or 'без никнейма'})"))
        if referrer:
            lines.append(html_kv("Пригласил", f"{referrer.first_name or ''} (@{referrer.username or 'без никнейма'})"))
        if referrer:
            ref_sub_q = await session.execute(select(Subscription).where(Subscription.user_id == referrer.id, Subscription.is_active == 1).order_by(Subscription.end_date.desc()))
            ref_sub = ref_sub_q.scalars().first()
            ref_end = ref_sub.end_date.strftime('%d.%m.%Y') if ref_sub else 'N/A'
            lines.append(html_kv("📆 Сроки", f"реферер до {ref_end}, реферал до {user_end}"))
        else:
            lines.append(html_kv("📆 Срок реферала", f"до {user_end}"))
        if referrer:
            lines.append(html_kv("🎁 Бонусы", f"рефереру +{ref_days or 7} дней, рефералу +{self_days or 7} дней"))

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« К списку", callback_data=f"admin_referrals_page:{page}")],
                [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]
            ]
        )
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()