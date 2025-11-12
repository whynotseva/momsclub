from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from datetime import datetime, timedelta
import logging

from utils.constants import ADMIN_IDS, CLUB_CHANNEL_URL
from utils.admin_permissions import is_admin, can_manage_admins
from utils.group_manager import GroupManager
from utils.helpers import fmt_date, html_kv, admin_nav_back
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_user_by_username,
    get_active_subscription,
    extend_subscription,
    has_active_subscription,
    deactivate_subscription,
    create_subscription,
    create_payment_log,
    get_user_badges,
    grant_user_badge,
    revoke_user_badge,
    send_badge_notification,
    has_user_badge,
)
from database.models import User, Subscription
from loyalty.levels import calc_tenure_days, level_for_days
from loyalty.service import effective_discount
from sqlalchemy import update

logger = logging.getLogger(__name__)

users_router = Router(name="admin_users")


class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()
    waiting_for_end_date = State()


@users_router.callback_query(F.data == "admin_find_user")
async def process_find_user(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    await state.set_state(AdminStates.waiting_for_user_id)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]]
    )

    try:
        await callback.message.delete()
        await callback.message.answer(
            "Введите Telegram ID или Username пользователя для поиска:\n"
            "(ID должен быть числом, username — с символом @)",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения в процессе поиска пользователя: {e}")
        await callback.message.answer(
            "Введите Telegram ID или Username пользователя для поиска:\n"
            "(ID должен быть числом, username — с символом @)",
            reply_markup=keyboard,
        )
    await callback.answer()


@users_router.message(StateFilter(AdminStates.waiting_for_user_id))
async def process_user_id(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not is_admin(user):
            return

    search_term = message.text.strip()

    async with AsyncSessionLocal() as session:
        user = None

        if search_term.startswith("@"):
            username = search_term[1:]
            user = await get_user_by_username(session, username)
        else:
            try:
                user_id = int(search_term)
                user = await get_user_by_telegram_id(session, user_id)
            except ValueError:
                await message.answer("❌ Некорректный формат! Введите числовой ID или username с символом @")
                return

        if user:
            subscription = await get_active_subscription(session, user.id)
            if subscription:
                days_left = (subscription.end_date - datetime.now()).days
                subscription_status = f"✅ Активна до {subscription.end_date.strftime('%d.%m.%Y')} (осталось дней: {days_left})"
            else:
                subscription_status = "❌ Отсутствует или истекла"

            tenure_days = await calc_tenure_days(session, user)
            level = level_for_days(tenure_days)
            discount = effective_discount(user)

            level_emoji = {"none": "", "silver": "🥈", "gold": "🥇", "platinum": "💎"}
            level_display = f"{level_emoji.get(user.current_loyalty_level or 'none', '')} {user.current_loyalty_level or 'none'}"

            if user.first_payment_date:
                first_payment = user.first_payment_date.strftime("%d.%m.%Y")
                discount_lines = []
                if user.one_time_discount_percent > 0:
                    discount_lines.append(f"💰 Разовая скидка: {user.one_time_discount_percent}%")
                if user.lifetime_discount_percent > 0:
                    discount_lines.append(
                        f"💎 Постоянная скидка: {user.lifetime_discount_percent}% ✨ (лояльность)"
                    )
                elif user.one_time_discount_percent == 0:
                    discount_lines.append(f"💎 Постоянная скидка: {user.lifetime_discount_percent}%")
                discount_info = "\n".join(discount_lines) if discount_lines else "💎 Постоянная скидка: 0%"

                loyalty_info = (
                    f"\n<b>💎 Лояльность:</b>\n"
                    f"📅 Первая оплата: {first_payment}\n"
                    f"📊 Стаж: {tenure_days} дней\n"
                    f"⭐ Уровень: {level_display} (рассчитанный: {level})\n"
                    f"🎁 Ожидает бонус: {'Да' if user.pending_loyalty_reward else 'Нет'}\n"
                    f"{discount_info}\n"
                    f"🎁 Подарок: {'Да' if user.gift_due else 'Нет'}\n"
                )
            else:
                loyalty_info = "\n<b>💎 Лояльность:</b>\n❌ Первая оплата не зафиксирована\n"

            created_at_str = (
                user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "Не заполнено"
            )
            updated_at_str = (
                user.updated_at.strftime("%d.%m.%Y %H:%M") if user.updated_at else "Не заполнено"
            )

            autorenewal_status = "Включено" if getattr(user, "is_recurring_active", False) else "Выключено"
            profile_link = (
                f'<a href="https://t.me/{user.username}">@{user.username}</a>' if user.username else "Не указан"
            )
            user_info_lines = [
                "<b>👤 Информация о пользователе:</b>",
                "",
                html_kv("ID в базе", str(user.id)),
                html_kv("Telegram ID", str(user.telegram_id)),
                html_kv("Username", profile_link),
                html_kv("Имя", user.first_name or "Не указано"),
                html_kv("Фамилия", user.last_name or "Не указана"),
                html_kv("Статус", "Активен" if user.is_active else "Неактивен"),
                html_kv("Создан", created_at_str),
                html_kv("Обновлен", updated_at_str),
                "",
                html_kv("🔄 Автопродление", autorenewal_status),
                "",
                html_kv("Подписка", subscription_status),
                loyalty_info,
            ]
            
            # Получаем badges пользователя
            user_badges = await get_user_badges(session, user.id)
            if user_badges:
                badge_names = {
                    'first_payment': '💳 Первая оплата',
                    'referral_1': '🤝 Пригласила друга',
                    'referral_5': '🌟 Пригласила 5 друзей',
                    'referral_10': '✨ Пригласила 10 друзей',
                    'month_in_club': '📅 Месяц в клубе',
                    'half_year_in_club': '💫 Полгода в клубе',
                    'year_in_club': '🏆 Год в клубе',
                    'loyal_customer': '💎 Верный клиент',
                    'platinum_customer': '👑 Платиновый клиент',
                    'active_member': '🔥 Активный участник',
                    'birthday_gift': '🎂 День рождения',
                    # Специальные badges (от админов)
                    'community_helper': '💝 Помощь сообществу',
                    'inspiration': '✨ Источник вдохновения',
                    'early_supporter': '🌱 Первопроходец',
                    'ambassador': '🌟 Амбассадор клуба',
                    'special_thanks': '💖 Особая благодарность',
                    'milestone_celebrator': '🎉 Празднуем вместе',
                    'supportive_friend': '🤗 Поддерживающая подруга',
                    'creative_soul': '🎨 Творческая душа',
                    'motivator': '💪 Мотиватор',
                    'heart_of_club': '💕 Сердце клуба',
                    'creator_special': '💋 Моя сучка от создателя Moms Club',
                }
                badges_list = [badge_names.get(badge.badge_type, badge.badge_type) for badge in user_badges]
                badges_info = f"\n<b>🏆 Достижения ({len(user_badges)}):</b>\n" + "\n".join([f"• {badge}" for badge in badges_list])
                user_info_lines.append("")
                user_info_lines.append(badges_info)
            else:
                user_info_lines.append("")
                user_info_lines.append("<b>🏆 Достижения:</b> Нет")
            
            user_info = "\n".join(user_info_lines)

            # Кнопка автопродления
            autorenew_btn = InlineKeyboardButton(
                text=("🛑 Выключить автопродление" if getattr(user, "is_recurring_active", False) else "🔄 Включить автопродление"),
                callback_data=(f"admin_disable_autorenew:{user.telegram_id}" if getattr(user, "is_recurring_active", False) else f"admin_enable_autorenew:{user.telegram_id}")
            )

            # Проверяем права текущего админа для отображения кнопок
            async with AsyncSessionLocal() as session:
                current_admin = await get_user_by_telegram_id(session, message.from_user.id)
                can_manage = can_manage_admins(current_admin) if current_admin else False
            
            keyboard_buttons = [
                [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data=f"admin_grant:{user.telegram_id}")],
                [
                    InlineKeyboardButton(text="➕ Добавить 30 дней", callback_data=f"admin_add_days:{user.telegram_id}:30"),
                    InlineKeyboardButton(text="➖ Убрать 30 дней", callback_data=f"admin_reduce_days:{user.telegram_id}:30"),
                ],
                [autorenew_btn],
            ]
            
            # Кнопки лояльности - только для создательницы/разработчика
            if can_manage:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text="⭐ Изменить уровень",
                        callback_data=f"admin_loyalty_set_level_from_user:{user.telegram_id}",
                    ),
                    InlineKeyboardButton(
                        text="🎁 Выдать бонус",
                        callback_data=f"admin_loyalty_grant_from_user:{user.telegram_id}",
                    ),
                ])
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text="🏆 Выдать достижение",
                    callback_data=f"admin_grant_badge:{user.telegram_id}",
                ),
                InlineKeyboardButton(
                    text="🗑️ Убрать достижение",
                    callback_data=f"admin_revoke_badge:{user.telegram_id}",
                ),
            ])
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=keyboard_buttons + [
                    [InlineKeyboardButton(
                        text=("🔓 Разблокировать пользователя" if getattr(user, "is_blocked", False) or not user.is_active else "🚫 Забанить пользователя"),
                        callback_data=(f"admin_unban_user:{user.telegram_id}" if getattr(user, "is_blocked", False) or not user.is_active else f"admin_ban_user:{user.telegram_id}")
                    )],
                    [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
                ]
            )

            await message.answer(user_info, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(f"❌ Пользователь '{search_term}' не найден.")

    await state.clear()


async def process_update_user_info(callback: CallbackQuery, telegram_id: int):
    logger.info(f"[admin_users] process_update_user_info начат для telegram_id: {telegram_id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        subscription = await get_active_subscription(session, user.id)
        if subscription:
            days_left = (subscription.end_date - datetime.now()).days
            subscription_status = f"✅ Активна до {subscription.end_date.strftime('%d.%m.%Y')} (осталось дней: {days_left})"
        else:
            subscription_status = "❌ Отсутствует или истекла"
        autorenewal_status = "Включено" if getattr(user, "is_recurring_active", False) else "Выключено"
        created_at_str = user.created_at.strftime('%d.%m.%Y %H:%M') if user.created_at else 'Не заполнено'
        updated_at_str = user.updated_at.strftime('%d.%m.%Y %H:%M') if user.updated_at else 'Не заполнено'

        # Лояльность — как в первичном отображении
        tenure_days = await calc_tenure_days(session, user)
        level = level_for_days(tenure_days)
        discount = effective_discount(user)
        level_emoji = {"none": "", "silver": "🥈", "gold": "🥇", "platinum": "💎"}
        level_display = f"{level_emoji.get(user.current_loyalty_level or 'none', '')} {user.current_loyalty_level or 'none'}"
        loyalty_info = (
            f"<b>Лояльность:</b>\n"
            f"Дата: {user.first_payment_date.strftime('%d.%m.%Y') if getattr(user, 'first_payment_date', None) else 'N/A'}\n"
            f"Стаж: {tenure_days} дней\n"
            f"Уровень: {level_display} (рассчитанный: {level})\n"
            f"Ожидает бонус: {'Да' if getattr(user, 'pending_loyalty_reward', False) else 'Нет'}\n"
            f"Постоянная скидка: {getattr(user, 'lifetime_discount_percent', 0) or 0}%\n"
            f"Подарок: {'Да' if getattr(user, 'gift_due', False) else 'Нет'}\n"
        )

        # Получаем badges пользователя
        user_badges = await get_user_badges(session, user.id)
        badges_info = ""
        if user_badges:
            badge_names = {
                'first_payment': '💳 Первая оплата',
                'referral_1': '🤝 Пригласила друга',
                'referral_5': '🌟 Пригласила 5 друзей',
                'referral_10': '✨ Пригласила 10 друзей',
                'month_in_club': '📅 Месяц в клубе',
                'half_year_in_club': '💫 Полгода в клубе',
                'year_in_club': '🏆 Год в клубе',
                'loyal_customer': '💎 Верный клиент',
                'platinum_customer': '👑 Платиновый клиент',
                'active_member': '🔥 Активный участник',
                'birthday_gift': '🎂 День рождения',
                # Специальные badges (от админов)
                'community_helper': '💝 Помощь сообществу',
                'inspiration': '✨ Источник вдохновения',
                'early_supporter': '🌱 Первопроходец',
                'ambassador': '🌟 Амбассадор клуба',
                'special_thanks': '💖 Особая благодарность',
                'milestone_celebrator': '🎉 Празднуем вместе',
                'supportive_friend': '🤗 Поддерживающая подруга',
                'creative_soul': '🎨 Творческая душа',
                'motivator': '💪 Мотиватор',
                'heart_of_club': '💕 Сердце клуба',
                'creator_special': '💋 Моя сучка от создателя Moms Club',
            }
            badges_list = [badge_names.get(badge.badge_type, badge.badge_type) for badge in user_badges]
            badges_info = f"\n<b>🏆 Достижения ({len(user_badges)}):</b>\n" + "\n".join([f"• {badge}" for badge in badges_list]) + "\n"
        else:
            badges_info = "\n<b>🏆 Достижения:</b> Нет\n"

        user_info = (
            f"<b>👤 Информация о пользователе:</b>\n\n"
            f"<b>ID в базе:</b> {user.id}\n"
            f"<b>Telegram ID:</b> {user.telegram_id}\n"
            f"<b>Username:</b> {user.username or 'Не указан'}\n"
            f"<b>Имя:</b> {user.first_name or 'Не указано'}\n"
            f"<b>Фамилия:</b> {user.last_name or 'Не указана'}\n"
            f"<b>Статус:</b> {'Активен' if user.is_active else 'Неактивен'}\n"
            f"<b>Создан:</b> {created_at_str}\n"
            f"<b>Обновлен:</b> {updated_at_str}\n\n"
            f"<b>🔄 Автопродление:</b> {autorenewal_status}\n\n"
            f"<b>Подписка:</b> {subscription_status}\n"
            f"{loyalty_info}"
            f"{badges_info}"
        )

        keyboard_btn = InlineKeyboardButton(text="🎁 Выдать подписку", callback_data=f"admin_grant:{user.telegram_id}")
        ban_unban_btn = InlineKeyboardButton(
            text=("🔓 Разблокировать пользователя" if getattr(user, "is_blocked", False) or not user.is_active else "🚫 Забанить пользователя"),
            callback_data=(f"admin_unban_user:{user.telegram_id}" if getattr(user, "is_blocked", False) or not user.is_active else f"admin_ban_user:{user.telegram_id}")
        )
        
        # Проверяем права текущего админа для отображения кнопок
        current_admin = await get_user_by_telegram_id(session, callback.from_user.id)
        can_manage = can_manage_admins(current_admin) if current_admin else False
        
        keyboard_buttons = [
            [keyboard_btn],
            [
                InlineKeyboardButton(text="➕ Добавить 30 дней", callback_data=f"admin_add_days:{user.telegram_id}:30"),
                InlineKeyboardButton(text="➖ Убрать 30 дней", callback_data=f"admin_reduce_days:{user.telegram_id}:30"),
            ],
            [
                InlineKeyboardButton(
                    text=("🛑 Выключить автопродление" if getattr(user, "is_recurring_active", False) else "🔄 Включить автопродление"),
                    callback_data=(f"admin_disable_autorenew:{user.telegram_id}" if getattr(user, "is_recurring_active", False) else f"admin_enable_autorenew:{user.telegram_id}")
                )
            ],
        ]
        
        # Кнопки лояльности - только для создательницы/разработчика
        if can_manage:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text="⭐ Изменить уровень",
                    callback_data=f"admin_loyalty_set_level_from_user:{user.telegram_id}",
                ),
                InlineKeyboardButton(
                    text="🎁 Выдать бонус",
                    callback_data=f"admin_loyalty_grant_from_user:{user.telegram_id}",
                ),
            ])
        
        keyboard_buttons.extend([
            [
                InlineKeyboardButton(
                    text="🏆 Выдать достижение",
                    callback_data=f"admin_grant_badge:{user.telegram_id}",
                ),
                InlineKeyboardButton(
                    text="🗑️ Убрать достижение",
                    callback_data=f"admin_revoke_badge:{user.telegram_id}",
                ),
            ],
            [ban_unban_btn],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        try:
            await callback.message.edit_text(user_info, reply_markup=keyboard, parse_mode="HTML")
            logger.info(f"[admin_users] process_update_user_info успешно завершен для telegram_id: {telegram_id}")
            # Не вызываем callback.answer() здесь - он будет вызван в process_user_info_from_callback
        except Exception as e:
            logger.error(f"[admin_users] Ошибка при редактировании сообщения для telegram_id {telegram_id}: {e}")
            # Пытаемся отправить новое сообщение
            try:
                await callback.message.answer(user_info, reply_markup=keyboard, parse_mode="HTML")
                await callback.answer()
                logger.info(f"[admin_users] Отправлено новое сообщение для telegram_id: {telegram_id}")
            except Exception as e2:
                logger.error(f"[admin_users] Ошибка при отправке нового сообщения для telegram_id {telegram_id}: {e2}")
                await callback.answer("❌ Ошибка при отображении информации", show_alert=True)
                raise  # Пробрасываем исключение дальше


@users_router.callback_query(F.data.startswith("admin_enable_autorenew:"))
async def process_enable_autorenew(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    telegram_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        try:
            from database.crud import enable_user_auto_renewal
            await enable_user_auto_renewal(session, user.id)
            await callback.answer("Автопродление включено", show_alert=True)
            await process_update_user_info(callback, telegram_id)
        except Exception as e:
            logger.error(f"Ошибка включения автопродления: {e}")
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_disable_autorenew:"))
async def process_disable_autorenew(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    telegram_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        try:
            from database.crud import disable_user_auto_renewal
            await disable_user_auto_renewal(session, user.id)
            await callback.answer("Автопродление выключено", show_alert=True)
            await process_update_user_info(callback, telegram_id)
        except Exception as e:
            logger.error(f"Ошибка выключения автопродления: {e}")
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_add_days:"))
async def process_add_days(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    parts = callback.data.split(":")
    telegram_id = int(parts[1])
    days = int(parts[2])

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        subscription = await get_active_subscription(session, user.id)
        if subscription:
            new_subscription = await extend_subscription(session, user.id, days, 0, "admin_extension")
            days_left = (new_subscription.end_date - datetime.now()).days
            await callback.answer(f"Подписка продлена на {days} дней", show_alert=True)
            await process_update_user_info(callback, telegram_id)
        else:
            end_date = datetime.now() + timedelta(days=days)
            await create_subscription(session, user.id, end_date, 0, "admin_grant")
            await callback.answer(f"Выдана новая подписка на {days} дней", show_alert=True)
            await process_update_user_info(callback, telegram_id)


@users_router.callback_query(F.data.startswith("admin_reduce_days:"))
async def process_reduce_days(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    parts = callback.data.split(":")
    telegram_id = int(parts[1])
    days = int(parts[2])

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        subscription = await get_active_subscription(session, user.id)
        if subscription:
            new_end_date = subscription.end_date - timedelta(days=days)
            if new_end_date < datetime.now():
                await deactivate_subscription(session, subscription.id)
                await callback.answer("Подписка деактивирована, т.к. новая дата окончания в прошлом", show_alert=True)
            else:
                query = update(Subscription).where(Subscription.id == subscription.id).values(end_date=new_end_date)
                await session.execute(query)
                await session.commit()
                await callback.answer(f"Срок подписки уменьшен на {days} дней", show_alert=True)
            await process_update_user_info(callback, telegram_id)
        else:
            await callback.answer("У пользователя нет активной подписки", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_ban_user:"))
async def process_ban_user(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    telegram_id = int(callback.data.split(":")[1])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_ban_confirm:{telegram_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_user_info:{telegram_id}"),
        ]]
    )

    await callback.message.edit_text(
        f"⚠️ <b>Вы действительно хотите забанить пользователя ID {telegram_id}?</b>\n\n"
        f"Это действие исключит пользователя из группы и деактивирует его подписку.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@users_router.callback_query(F.data.startswith("admin_user_info:"))
async def process_user_info_from_callback(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    try:
        telegram_id = int(callback.data.split(":")[1])
        logger.info(f"[admin_users] Обработчик admin_user_info вызван для telegram_id: {telegram_id}")
    except Exception as e:
        logger.error(f"[admin_users] Ошибка при парсинге admin_user_info: {e}, data: {callback.data}")
        await callback.answer("Некорректные данные", show_alert=True)
        return

    # НЕ вызываем callback.answer() здесь - это может блокировать edit_text
    # Вызовем его в конце после успешного редактирования
    
    try:
        await process_update_user_info(callback, telegram_id)
        # Вызываем answer только после успешного редактирования
        await callback.answer()
        logger.info(f"[admin_users] admin_user_info успешно обработан для telegram_id: {telegram_id}")
    except Exception as e:
        logger.error(f"[admin_users] Ошибка в process_update_user_info для telegram_id {telegram_id}: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке информации о пользователе", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_ban_confirm:"))
async def process_ban_confirm(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    telegram_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        try:
            group_manager = GroupManager(callback.bot)
            kicked = await group_manager.kick_user(telegram_id)

            subscription = await get_active_subscription(session, user.id)
            if subscription:
                await deactivate_subscription(session, subscription.id)

            query = update(User).where(User.id == user.id).values(is_active=False)
            await session.execute(query)
            await session.commit()

            status_text = (
                "Пользователь успешно забанен и исключен из группы." if kicked else
                "Пользователь забанен в системе, но возникла ошибка при исключении из группы."
            )
            await callback.answer(status_text, show_alert=True)
            await process_update_user_info(callback, telegram_id)
        except Exception as e:
            logger.error(f"Ошибка при бане пользователя {telegram_id}: {e}", exc_info=True)
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_unban_user:"))
async def process_unban_user(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    telegram_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        try:
            # Снимаем блокировку и возвращаем активность
            query = update(User).where(User.id == user.id).values(is_active=True, is_blocked=False)
            await session.execute(query)
            await session.commit()

            # Пытаемся вернуть в группу
            try:
                from database.crud import add_user_to_club_channel
                await add_user_to_club_channel(callback.bot, telegram_id)
            except Exception as e:
                logger.warning(f"Не удалось вернуть пользователя {telegram_id} в группу: {e}")

            await callback.answer("Пользователь разблокирован", show_alert=True)
            await process_update_user_info(callback, telegram_id)
        except Exception as e:
            logger.error(f"Ошибка при разблокировке пользователя {telegram_id}: {e}")
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_grant:"))
async def process_grant_specific(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    user_id = int(callback.data.split(":")[1])
    await state.update_data(telegram_id=user_id)
    await state.set_state(AdminStates.waiting_for_days)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="30 дней", callback_data="admin_days:30"),
                InlineKeyboardButton(text="60 дней", callback_data="admin_days:60"),
                InlineKeyboardButton(text="90 дней", callback_data="admin_days:90"),
            ],
            [
                InlineKeyboardButton(text="✨ Пожизненно", callback_data="admin_lifetime"),
                InlineKeyboardButton(text="🗓 Указать дату", callback_data="admin_set_date"),
            ],
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")],
        ]
    )

    await callback.message.edit_text(
        f"На сколько дней выдать подписку пользователю ID {user_id}?\n"
        "Выберите из предложенных вариантов или введите количество дней:",
        reply_markup=keyboard,
    )
    await callback.answer()


@users_router.callback_query(F.data.startswith("admin_days:"))
async def process_preset_days(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    days = int(callback.data.split(":")[1])
    user_data = await state.get_data()
    telegram_id = user_data.get("telegram_id")
    await grant_subscription(callback.message, telegram_id, days)
    await state.clear()
    await callback.answer()


@users_router.message(StateFilter(AdminStates.waiting_for_days))
async def process_days_input(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not is_admin(user):
            return

    try:
        days = int(message.text.strip())
        if days <= 0:
            await message.answer("Количество дней должно быть положительным числом. Попробуйте еще раз:")
            return

        user_data = await state.get_data()
        telegram_id = user_data.get("telegram_id")
        await grant_subscription(message, telegram_id, days)
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректное количество дней (только цифры)")


@users_router.callback_query(F.data == "admin_lifetime")
async def process_lifetime_subscription(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    user_data = await state.get_data()
    telegram_id = user_data.get("telegram_id")
    await grant_subscription(callback.message, telegram_id, days=0, is_lifetime=True)
    await state.clear()
    await callback.answer()


@users_router.callback_query(F.data == "admin_set_date")
async def process_set_date(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    await state.set_state(AdminStates.waiting_for_end_date)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]])
    current_date = datetime.now().strftime("%d_%m_%Y")
    await callback.message.edit_text(
        "Введите дату окончания подписки в формате ДД_ММ_ГГГГ\n"
        f"Например: {current_date}",
        reply_markup=keyboard,
    )
    await callback.answer()


@users_router.message(StateFilter(AdminStates.waiting_for_end_date))
async def process_end_date_input(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not is_admin(user):
            return

    date_input = message.text.strip()
    try:
        day, month, year = map(int, date_input.split("_"))
        end_date = datetime(year, month, day, 23, 59, 59)
        if end_date < datetime.now():
            await message.answer("❌ Нельзя установить дату окончания в прошлом. Пожалуйста, введите корректную дату:")
            return
        user_data = await state.get_data()
        telegram_id = user_data.get("telegram_id")
        await grant_subscription(message, telegram_id, days=0, is_lifetime=False, end_date=end_date)
        await state.clear()
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Пожалуйста, введите дату в формате ДД_ММ_ГГГГ\n"
            "Например: 31_12_2025",
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при обработке даты: {str(e)}")


async def grant_subscription(message, telegram_id, days, is_lifetime=False, end_date=None):
    bot = message.bot

    if is_lifetime:
        details = "Бессрочная подписка, выдана администратором"
    elif end_date:
        details = f"Подписка до {end_date.strftime('%d.%m.%Y')}, выдана администратором"
    else:
        details = f"Подписка на {days} дней, выдана администратором"

    if not end_date and not is_lifetime:
        end_date = datetime.now() + timedelta(days=days)
    elif is_lifetime:
        end_date = datetime.now() + timedelta(days=36500)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="admin_back")]])

    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await message.answer(f"❌ Пользователь с ID {telegram_id} не найден", reply_markup=keyboard)
                return False

            has_sub = await has_active_subscription(session, user.id)
            if has_sub:
                if is_lifetime:
                    active_sub = await get_active_subscription(session, user.id)
                    if active_sub:
                        await deactivate_subscription(session, active_sub.id)
                        new_sub = await create_subscription(session, user.id, end_date, 0, "admin_lifetime")
                    else:
                        new_sub = await create_subscription(session, user.id, end_date, 0, "admin_lifetime")
                elif end_date:
                    active_sub = await get_active_subscription(session, user.id)
                    if active_sub:
                        query = update(Subscription).where(Subscription.id == active_sub.id).values(end_date=end_date)
                        await session.execute(query)
                        await session.commit()
                        await session.refresh(active_sub)
                        new_sub = active_sub
                    else:
                        new_sub = await create_subscription(session, user.id, end_date, 0, "admin_date")
                else:
                    new_sub = await extend_subscription(session, user.id, days, 0, "admin_extend")

                await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=new_sub.id,
                    amount=0,
                    status="success",
                    payment_method="admin",
                    transaction_id=None,
                    details=details,
                )

                days_text = "бессрочно" if is_lifetime else f"до {new_sub.end_date.strftime('%d.%m.%Y')}"
                await message.answer(
                    f"✅ Пользователю {user.first_name or ''} {user.last_name or ''} (@{user.username or str(user.telegram_id)}) успешно обновлена подписка!\n\n"
                    f"Подписка активна {days_text}.",
                    reply_markup=keyboard,
                )

                try:
                    user_notification = (
                        "🎁 Администратор продлил вашу подписку на Mom's Club!\n\n"
                        f"Ваша подписка теперь активна {days_text}.\n\n"
                        "Вы можете перейти в закрытый канал по кнопке ниже:"
                    )
                    user_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)]])
                    await bot.send_message(user.telegram_id, user_notification, reply_markup=user_keyboard)
                except Exception as e:
                    logger.error(f"Ошибка уведомления пользователя {user.telegram_id}: {e}")
                    await message.answer(
                        f"⚠️ Подписка успешно продлена, но не удалось отправить уведомление пользователю: {str(e)}",
                        reply_markup=keyboard,
                    )
                return True
            else:
                new_sub = await create_subscription(session, user.id, end_date, 0, "admin_grant")
                await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=new_sub.id,
                    amount=0,
                    status="success",
                    payment_method="admin",
                    transaction_id=None,
                    details=details,
                )
                days_text = "бессрочно" if is_lifetime else f"до {new_sub.end_date.strftime('%d.%m.%Y')}"
                await message.answer(
                    f"✅ Пользователю {user.first_name or ''} {user.last_name or ''} (@{user.username or str(user.telegram_id)}) успешно выдана подписка!\n\n"
                    f"Подписка активна {days_text}.",
                    reply_markup=keyboard,
                )
                try:
                    user_notification = (
                        "🎁 Администратор выдал вам подписку на Mom's Club!\n\n"
                        f"Ваша подписка активна {days_text}.\n\n"
                        "Вы можете перейти в закрытый канал по кнопке ниже:"
                    )
                    user_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)]])
                    await bot.send_message(user.telegram_id, user_notification, reply_markup=user_keyboard)
                except Exception as e:
                    logger.error(f"Ошибка уведомления пользователя {user.telegram_id}: {e}")
                    await message.answer(
                        f"⚠️ Подписка успешно выдана, но не удалось отправить уведомление пользователю: {str(e)}",
                        reply_markup=keyboard,
                    )
                return True
    except Exception as e:
        logger.error(f"Ошибка при выдаче подписки пользователю {telegram_id}: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при выдаче подписки: {str(e)}", reply_markup=keyboard)
        return False


@users_router.callback_query(F.data.startswith("admin_grant_badge:"))
async def process_grant_badge_menu(callback: CallbackQuery):
    """Показывает меню выбора badge для выдачи"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        telegram_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем текущие badges
        current_badges = await get_user_badges(session, user.id)
        current_badge_types = {badge.badge_type for badge in current_badges}
        
        # Список всех доступных badges
        # Автоматические badges
        automatic_badges = [
            ('first_payment', '💳 Первая оплата'),
            ('referral_1', '🤝 Пригласила друга'),
            ('referral_5', '🌟 Пригласила 5 друзей'),
            ('referral_10', '✨ Пригласила 10 друзей'),
            ('month_in_club', '📅 Месяц в клубе'),
            ('half_year_in_club', '💫 Полгода в клубе'),
            ('year_in_club', '🏆 Год в клубе'),
            ('loyal_customer', '💎 Верный клиент'),
            ('platinum_customer', '👑 Платиновый клиент'),
            ('active_member', '🔥 Активный участник'),
            ('birthday_gift', '🎂 День рождения'),
        ]
        
        # Специальные badges (только от админов)
        special_badges = [
            ('community_helper', '💝 Помощь сообществу'),
            ('inspiration', '✨ Источник вдохновения'),
            ('early_supporter', '🌱 Первопроходец'),
            ('ambassador', '🌟 Амбассадор клуба'),
            ('special_thanks', '💖 Особая благодарность'),
            ('milestone_celebrator', '🎉 Празднуем вместе'),
            ('supportive_friend', '🤗 Поддерживающая подруга'),
            ('creative_soul', '🎨 Творческая душа'),
            ('motivator', '💪 Мотиватор'),
            ('heart_of_club', '💕 Сердце клуба'),
            ('creator_special', '💋 Моя сучка от создателя Moms Club'),
        ]
        
        all_badges = automatic_badges + special_badges
        
        # Формируем клавиатуру с разделением на категории
        keyboard_buttons = []
        
        # Автоматические badges
        if automatic_badges:
            keyboard_buttons.append([InlineKeyboardButton(
                text="📋 Автоматические достижения",
                callback_data="ignore"
            )])
            for badge_type, badge_name in automatic_badges:
                if badge_type in current_badge_types:
                    button_text = f"✅ {badge_name} (есть)"
                    callback_data = f"admin_badge_already:{telegram_id}:{badge_type}"
                else:
                    button_text = badge_name
                    callback_data = f"admin_badge_grant_confirm:{telegram_id}:{badge_type}"
                
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=callback_data
                )])
        
        # Специальные badges
        if special_badges:
            keyboard_buttons.append([InlineKeyboardButton(
                text="⭐ Специальные достижения (только от админов)",
                callback_data="ignore"
            )])
            for badge_type, badge_name in special_badges:
                if badge_type in current_badge_types:
                    button_text = f"✅ {badge_name} (есть)"
                    callback_data = f"admin_badge_already:{telegram_id}:{badge_type}"
                else:
                    button_text = badge_name
                    callback_data = f"admin_badge_grant_confirm:{telegram_id}:{badge_type}"
                
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=callback_data
                )])
        
        keyboard_buttons.append([InlineKeyboardButton(
            text="« Назад",
            callback_data=f"admin_user_info:{telegram_id}"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(
            f"<b>🏆 Выдача достижения</b>\n\n"
            f"Пользователь: {user.first_name or ''} {user.last_name or ''} (@{user.username or 'нет username'})\n\n"
            f"<b>📋 Автоматические достижения</b> — выдаются автоматически при выполнении условий\n"
            f"<b>⭐ Специальные достижения</b> — выдаются только администраторами в знак особой благодарности\n\n"
            f"Выберите достижение для выдачи:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()


@users_router.callback_query(F.data.startswith("admin_badge_already:"))
async def process_badge_already(callback: CallbackQuery):
    """Обработчик для badges, которые уже есть"""
    await callback.answer("Это достижение уже выдано пользователю", show_alert=True)


@users_router.callback_query(F.data.startswith("admin_badge_grant_confirm:"))
async def process_badge_grant_confirm(callback: CallbackQuery):
    """Подтверждение выдачи badge"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        badge_type = parts[2]
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Проверяем, есть ли уже такой badge
        if await has_user_badge(session, user.id, badge_type):
            await callback.answer("Это достижение уже выдано пользователю", show_alert=True)
            await process_grant_badge_menu(callback)
            return
        
        # Выдаем badge
        admin = await get_user_by_telegram_id(session, callback.from_user.id)
        badge = await grant_user_badge(
            session,
            user.id,
            badge_type,
            from_admin=True,
            admin_id=callback.from_user.id
        )
        
        if badge:
            # Отправляем уведомление пользователю
            try:
                await send_badge_notification(
                    callback.bot,
                    user,
                    badge_type,
                    from_admin=True
                )
                await callback.answer("✅ Достижение выдано! Пользователь получил уведомление.", show_alert=True)
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о badge: {e}")
                await callback.answer("✅ Достижение выдано, но не удалось отправить уведомление.", show_alert=True)
        else:
            await callback.answer("❌ Не удалось выдать достижение", show_alert=True)
        
        # Возвращаемся к меню выбора badge
        await process_grant_badge_menu(callback)


@users_router.callback_query(F.data.startswith("admin_revoke_badge:"))
async def process_revoke_badge_menu(callback: CallbackQuery):
    """Показывает меню выбора badge для удаления"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        telegram_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем текущие badges пользователя
        current_badges = await get_user_badges(session, user.id)
        
        if not current_badges:
            await callback.answer("У пользователя нет достижений для удаления", show_alert=True)
            await process_update_user_info(callback, telegram_id)
            return
        
        # Словарь для отображения названий badges
        badge_names = {
            'first_payment': '💳 Первая оплата',
            'referral_1': '🤝 Пригласила друга',
            'referral_5': '🌟 Пригласила 5 друзей',
            'referral_10': '✨ Пригласила 10 друзей',
            'month_in_club': '📅 Месяц в клубе',
            'half_year_in_club': '💫 Полгода в клубе',
            'year_in_club': '🏆 Год в клубе',
            'loyal_customer': '💎 Верный клиент',
            'platinum_customer': '👑 Платиновый клиент',
            'active_member': '🔥 Активный участник',
            'birthday_gift': '🎂 День рождения',
            'community_helper': '💝 Помощь сообществу',
            'inspiration': '✨ Источник вдохновения',
            'early_supporter': '🌱 Первопроходец',
            'ambassador': '🌟 Амбассадор клуба',
            'special_thanks': '💖 Особая благодарность',
            'milestone_celebrator': '🎉 Празднуем вместе',
            'supportive_friend': '🤗 Поддерживающая подруга',
            'creative_soul': '🎨 Творческая душа',
            'motivator': '💪 Мотиватор',
            'heart_of_club': '💕 Сердце клуба',
            'creator_special': '💋 Моя сучка от создателя Moms Club',
        }
        
        # Формируем клавиатуру с текущими badges
        keyboard_buttons = []
        
        for badge in current_badges:
            badge_name = badge_names.get(badge.badge_type, badge.badge_type)
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"🗑️ {badge_name}",
                callback_data=f"admin_badge_revoke_confirm:{telegram_id}:{badge.badge_type}"
            )])
        
        keyboard_buttons.append([InlineKeyboardButton(
            text="« Назад",
            callback_data=f"admin_user_info:{telegram_id}"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(
            f"<b>🗑️ Удаление достижения</b>\n\n"
            f"Пользователь: {user.first_name or ''} {user.last_name or ''} (@{user.username or 'нет username'})\n\n"
            f"<b>⚠️ Внимание:</b> Достижение будет удалено без уведомления пользователя.\n\n"
            f"Выберите достижение для удаления:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()


@users_router.callback_query(F.data.startswith("admin_badge_revoke_confirm:"))
async def process_badge_revoke_confirm(callback: CallbackQuery):
    """Подтверждение удаления badge"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        badge_type = parts[2]
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Проверяем, есть ли такой badge
        if not await has_user_badge(session, user.id, badge_type):
            await callback.answer("У пользователя нет этого достижения", show_alert=True)
            await process_revoke_badge_menu(callback)
            return
        
        # Удаляем badge (БЕЗ уведомления пользователю)
        success = await revoke_user_badge(
            session,
            user.id,
            badge_type,
            admin_id=callback.from_user.id
        )
        
        if success:
            await callback.answer("✅ Достижение удалено (пользователь не получил уведомление)", show_alert=True)
        else:
            await callback.answer("❌ Не удалось удалить достижение", show_alert=True)
        
        # Возвращаемся к меню удаления badge
        await process_revoke_badge_menu(callback)


def register_admin_users_handlers(dp):
    dp.include_router(users_router)
    logger.info("[users] Админ-обработчики поиска и карточки пользователя зарегистрированы")