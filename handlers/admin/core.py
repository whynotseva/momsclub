from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
import os
import logging
from utils.constants import ADMIN_IDS
from utils.admin_permissions import is_admin, can_view_revenue, get_admin_group_display, can_manage_admins
from database.crud import get_user_by_telegram_id
from database.config import AsyncSessionLocal
from database.crud import (
    get_total_users_count,
    get_active_subscriptions_count,
    get_expired_subscriptions_count,
    get_total_payments_amount,
    get_total_promo_code_uses_count,
    get_new_users_by_date,
    get_new_subscriptions_by_date,
    get_conversion_rate,
    get_average_ltv,
    get_revenue_by_month,
    get_retention_rate_by_month,
    get_top_referral_sources,
    export_analytics_data,
    get_user_by_telegram_id,
)
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

core_router = Router()


def register_admin_core_handlers(dp):
    dp.include_router(core_router)


@core_router.message(Command("admin"), F.chat.type == "private")
async def cmd_admin_check(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"[core] Команда /admin от ID: {user_id}, username: @{message.from_user.username}")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, user_id)
        logger.info(f"[core] Пользователь {user_id}: user={user}, admin_group={user.admin_group if user else None}, is_admin={is_admin(user) if user else False}")
        if not is_admin(user):
            logger.warning(f"[core] Пользователь {user_id} (@{message.from_user.username}) не имеет прав админа. user={user}, admin_group={user.admin_group if user else None}")
            await message.answer("У вас нет прав доступа к этой команде.")
            return

        # Используем общую функцию формирования клавиатуры
        keyboard = _admin_menu_keyboard(user)

    banner_path = os.path.join(os.getcwd(), "media", "админка.jpg")
    banner_photo = FSInputFile(banner_path)
    await message.answer_photo(photo=banner_photo, caption="Панель администратора Mom's Club:", reply_markup=keyboard)


@core_router.callback_query(F.data == "admin_stats")
async def process_admin_stats(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_view_revenue(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    try:
        await callback.answer("Загрузка статистики...", show_alert=False)
        async with AsyncSessionLocal() as session:
            total_users = await get_total_users_count(session)
            active_subs = await get_active_subscriptions_count(session)
            expired_subs = await get_expired_subscriptions_count(session)
            total_payments = await get_total_payments_amount(session)
            total_promo_uses = await get_total_promo_code_uses_count(session)
            
            # Получаем данные за последние периоды для трендов
            from sqlalchemy import select, func
            from database.models import User, Subscription, PaymentLog
            from datetime import timedelta
            
            now = datetime.now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            week_ago = today_start - timedelta(days=7)
            
            # Новые пользователи за сегодня
            result = await session.execute(
                select(func.count(User.id)).where(User.created_at >= today_start)
            )
            new_users_today = result.scalar() or 0
            
            # Новые пользователи вчера
            result = await session.execute(
                select(func.count(User.id)).where(
                    User.created_at >= yesterday_start,
                    User.created_at < today_start
                )
            )
            new_users_yesterday = result.scalar() or 0
            
            # Платежи за сегодня
            result = await session.execute(
                select(func.sum(PaymentLog.amount)).where(
                    PaymentLog.created_at >= today_start,
                    PaymentLog.status == 'success'
                )
            )
            payments_today = result.scalar() or 0
            
            # Платежи за вчера
            result = await session.execute(
                select(func.sum(PaymentLog.amount)).where(
                    PaymentLog.created_at >= yesterday_start,
                    PaymentLog.created_at < today_start,
                    PaymentLog.status == 'success'
                )
            )
            payments_yesterday = result.scalar() or 0
            
            # Расчет трендов
            def format_trend(current, previous):
                if previous == 0:
                    if current > 0:
                        return "🟢 ↗️ новые!"
                    return ""
                
                delta = current - previous
                if delta > 0:
                    return f"🟢 ↗️ +{delta}"
                elif delta < 0:
                    return f"🔴 ↘️ {delta}"
                else:
                    return "⚪ как вчера"
            
            new_users_trend = format_trend(new_users_today, new_users_yesterday)
            payments_trend = format_trend(payments_today, payments_yesterday)

        conversion_rate = round((active_subs / total_users * 100), 1) if total_users > 0 else 0
        avg_payment = round(total_payments / (active_subs + expired_subs), 1) if (active_subs + expired_subs) > 0 else 0
        current_time = datetime.now().strftime('%d.%m.%Y %H:%M')
        
        stats_text = f"""
<b>📊 Статистика Mom's Club</b>

👥 <b>Всего пользователей:</b> {total_users}
   └ Новых за сегодня: {new_users_today} {new_users_trend}

✅ <b>Активных подписок:</b> {active_subs}
❌ <b>Истекших подписок:</b> {expired_subs}

💰 <b>Выручка за сегодня:</b> {payments_today:,.0f} ₽ {payments_trend}
💵 <b>Всего платежей:</b> {total_payments:,.0f} ₽
💳 <b>Средний чек:</b> {avg_payment:,.0f} ₽

📈 <b>Конверсия:</b> {conversion_rate}%
🎁 <b>Промокодов использовано:</b> {total_promo_uses}

<i>⏰ Обновлено: {current_time}</i>
"""

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Обновить данные", callback_data="admin_stats")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
            ]
        )
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(stats_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[core] Ошибка статистики: {e}")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="admin_back")]])
        await callback.message.answer(f"❌ Ошибка при получении статистики: {str(e)}", reply_markup=keyboard)


@core_router.callback_query(F.data == "admin_analytics")
async def process_admin_analytics(callback: CallbackQuery):
    """Обработчик расширенной аналитики"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_view_revenue(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        await callback.answer("Загрузка аналитики...", show_alert=False)
        async with AsyncSessionLocal() as session:
            # Получаем все метрики
            new_users = await get_new_users_by_date(session, days=30)
            new_subs = await get_new_subscriptions_by_date(session, days=30)
            conversion = await get_conversion_rate(session)
            ltv = await get_average_ltv(session)
            revenue_by_month = await get_revenue_by_month(session, months=6)
            retention = await get_retention_rate_by_month(session, months=6)
            top_sources = await get_top_referral_sources(session, limit=10)
            
            # Отладочная информация
            total_users_in_period = sum([count for _, count in new_users])
            total_subs_in_period = sum([count for _, count in new_subs])
            logger.info(f"[analytics] Пользователей за 30 дней: {total_users_in_period}, Подписок: {total_subs_in_period}")
            logger.info(f"[analytics] Дней с пользователями: {len([c for _, c in new_users if c > 0])}, Дней с подписками: {len([c for _, c in new_subs if c > 0])}")
            
            # Проверяем права на просмотр выручки
            async with AsyncSessionLocal() as session:
                current_user = await get_user_by_telegram_id(session, callback.from_user.id)
                can_view = can_view_revenue(current_user) if current_user else False
            
            # Формируем текст с аналитикой
            analytics_text = f"""<b>📈 Расширенная аналитика Mom's Club</b>

<b>📊 Конверсия:</b>
👥 Всего пользователей: {conversion['total_users']}
💳 С платежами: {conversion['users_with_payments']}
✅ С активными подписками: {conversion['users_with_active_subs']}
📈 Конверсия в платежи: <b>{conversion['conversion_to_payment']}%</b>
📈 Конверсия в активные: <b>{conversion['conversion_to_active']}%</b>
"""
            
            # Выручка и LTV - только для тех, кто может видеть выручку
            if can_view:
                analytics_text += f"""
<b>💰 LTV (Lifetime Value):</b>
💵 Общая выручка: <b>{ltv['total_revenue']:,} ₽</b>
👤 Платящих пользователей: {ltv['paying_users']}
💎 Средний LTV платящих: <b>{ltv['avg_ltv_paying']} ₽</b>
💎 Средний LTV всех: <b>{ltv['avg_ltv_all']} ₽</b>

<b>📊 Выручка по месяцам (последние 6 месяцев):</b>
"""
                
                # Добавляем выручку по месяцам
                month_names = {
                    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
                    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
                    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
                }
                for month, revenue in revenue_by_month:
                    try:
                        month_dt = datetime.strptime(month, '%Y-%m')
                        month_name = month_names.get(month_dt.month, month_dt.strftime('%B'))
                        analytics_text += f"  {month_name} {month_dt.year}: <b>{revenue:,} ₽</b>\n"
                    except:
                        analytics_text += f"  {month}: <b>{revenue:,} ₽</b>\n"
            
            analytics_text += f"""
<b>📅 Retention Rate (последние 6 месяцев):</b>
"""
            
            # Добавляем retention по месяцам
            month_names = {
                1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
                5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
                9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
            }
            for month, rate in retention:
                try:
                    month_dt = datetime.strptime(month, '%Y-%m')
                    month_name = month_names.get(month_dt.month, month_dt.strftime('%B'))
                    analytics_text += f"  {month_name} {month_dt.year}: <b>{rate}%</b>\n"
                except:
                    analytics_text += f"  {month}: <b>{rate}%</b>\n"
            
            # График новых пользователей (последние 30 дней, только с данными)
            # Фильтруем только дни с данными из всего периода
            users_with_data = [(d, c) for d, c in new_users if c > 0]
            if users_with_data:
                # Показываем последние 14 дней с данными
                recent_users = users_with_data[-14:] if len(users_with_data) > 14 else users_with_data
                analytics_text += f"\n<b>👥 Новые пользователи (последние дни с данными):</b>\n"
                for date_obj, count in recent_users:
                    date_str = date_obj.strftime('%d.%m')
                    bar = "█" * min(count, 20)  # Визуализация до 20 пользователей
                    analytics_text += f"  {date_str}: {count} {bar}\n"
            else:
                analytics_text += f"\n<b>👥 Новые пользователи:</b>\n"
                analytics_text += f"  За последние 30 дней новых пользователей не было\n"
            
            # График продаж (последние 30 дней, только с данными)
            # Фильтруем только дни с данными из всего периода
            subs_with_data = [(d, c) for d, c in new_subs if c > 0]
            if subs_with_data:
                # Показываем последние 14 дней с данными
                recent_subs = subs_with_data[-14:] if len(subs_with_data) > 14 else subs_with_data
                analytics_text += f"\n<b>💰 Продажи (последние дни с данными):</b>\n"
                analytics_text += f"<i>Все продажи включая продления</i>\n"
                for date_obj, count in recent_subs:
                    date_str = date_obj.strftime('%d.%m')
                    bar = "█" * min(count, 20)  # Визуализация до 20 продаж
                    analytics_text += f"  {date_str}: {count} {bar}\n"
            else:
                analytics_text += f"\n<b>💰 Продажи:</b>\n"
                analytics_text += f"  За последние 30 дней продаж не было\n"
            
            # Топ источников
            analytics_text += f"\n<b>🌟 Топ источников (реферальные коды):</b>\n"
            for idx, (code, refs, paying) in enumerate(top_sources[:5], 1):  # Топ 5
                code_display = code if code != 'Без кода' else 'Без кода'
                analytics_text += f"  {idx}. {code_display}: {refs} рефералов ({paying} платящих)\n"
            
            current_time = datetime.now().strftime('%d.%m.%Y %H:%M')
            analytics_text += f"\n<i>Данные актуальны на: {current_time}</i>"
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="📊 Обновить", callback_data="admin_analytics"),
                        InlineKeyboardButton(text="💾 Экспорт CSV", callback_data="admin_analytics_export:csv")
                    ],
                    [
                        InlineKeyboardButton(text="📄 Экспорт TXT", callback_data="admin_analytics_export:text"),
                        InlineKeyboardButton(text="📊 График продаж", callback_data="admin_analytics_chart")
                    ],
                    [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
                ]
            )
            
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(analytics_text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"[core] Ошибка аналитики: {e}", exc_info=True)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="admin_back")]])
        await callback.message.answer(f"❌ Ошибка при получении аналитики: {str(e)}", reply_markup=keyboard)


@core_router.callback_query(F.data.startswith("admin_analytics_export:"))
async def process_admin_analytics_export(callback: CallbackQuery):
    """Экспорт данных аналитики"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_view_revenue(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        export_format = callback.data.split(":")[1]  # 'csv' или 'text'
        await callback.answer("Подготовка экспорта...", show_alert=False)
        
        async with AsyncSessionLocal() as session:
            export_data = await export_analytics_data(session, format=export_format)
            
            if export_format == 'csv':
                # Отправляем как файл
                import tempfile
                import os
                
                filename = f"analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                
                # Создаем временный файл
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp_file:
                    tmp_file.write(export_data)
                    tmp_file_path = tmp_file.name
                
                try:
                    # Отправляем файл
                    await callback.message.answer_document(
                        document=FSInputFile(tmp_file_path, filename=filename),
                        caption="📊 Экспорт аналитики (CSV)"
                    )
                    await callback.answer("✅ CSV файл отправлен", show_alert=True)
                finally:
                    # Удаляем временный файл
                    try:
                        os.unlink(tmp_file_path)
                    except:
                        pass
            else:
                # Отправляем как текст (может быть длинным, разбиваем на части)
                max_length = 4000  # Лимит Telegram
                if len(export_data) <= max_length:
                    await callback.message.answer(f"<pre>{export_data}</pre>", parse_mode="HTML")
                else:
                    # Разбиваем на части
                    parts = [export_data[i:i+max_length] for i in range(0, len(export_data), max_length)]
                    for part in parts:
                        await callback.message.answer(f"<pre>{part}</pre>", parse_mode="HTML")
                
                await callback.answer("✅ Экспорт выполнен", show_alert=True)
                
    except Exception as e:
        logger.error(f"[core] Ошибка экспорта аналитики: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка экспорта: {str(e)}", show_alert=True)


@core_router.callback_query(F.data == "admin_analytics_chart")
async def process_admin_analytics_chart(callback: CallbackQuery):
    """График новых пользователей и подписок (текстовый)"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_view_revenue(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        await callback.answer("Загрузка графика...", show_alert=False)
        async with AsyncSessionLocal() as session:
            new_users = await get_new_users_by_date(session, days=30)
            new_subs = await get_new_subscriptions_by_date(session, days=30)
            
            # Находим максимальное значение для масштабирования
            max_users = max([count for _, count in new_users]) if new_users else 1
            max_subs = max([count for _, count in new_subs]) if new_subs else 1
            max_count = max(max_users, max_subs)
            
            chart_text = "<b>📊 Графики (последние 30 дней)</b>\n\n"
            
            # Фильтруем только дни с данными для пользователей
            users_with_data = [(d, c) for d, c in new_users if c > 0]
            if users_with_data:
                chart_text += "<b>👥 Новые пользователи (только дни с данными):</b>\n"
                for date_obj, count in users_with_data:
                    date_str = date_obj.strftime('%d.%m')
                    # Масштабируем до 30 символов
                    bar_length = int((count / max_count) * 30) if max_count > 0 else 0
                    bar = "█" * bar_length
                    chart_text += f"{date_str}: {count:3d} {bar}\n"
                chart_text += f"\n<i>Максимум пользователей: {max_users}</i>\n\n"
            else:
                chart_text += "<b>👥 Новые пользователи:</b>\n"
                chart_text += "  За последние 30 дней новых пользователей не было\n\n"
            
            # Фильтруем только дни с данными для продаж
            subs_with_data = [(d, c) for d, c in new_subs if c > 0]
            if subs_with_data:
                chart_text += "<b>💰 Продажи (только дни с данными):</b>\n"
                chart_text += "<i>Все продажи включая продления</i>\n"
                for date_obj, count in subs_with_data:
                    date_str = date_obj.strftime('%d.%m')
                    # Масштабируем до 30 символов
                    bar_length = int((count / max_count) * 30) if max_count > 0 else 0
                    bar = "█" * bar_length
                    chart_text += f"{date_str}: {count:3d} {bar}\n"
                chart_text += f"\n<i>Максимум продаж: {max_subs}</i>"
            else:
                chart_text += "<b>💰 Продажи:</b>\n"
                chart_text += "  За последние 30 дней продаж не было"
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Обновить график", callback_data="admin_analytics_chart")],
                    [InlineKeyboardButton(text="« Назад к аналитике", callback_data="admin_analytics")],
                ]
            )
            
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(chart_text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"[core] Ошибка графика: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


def _admin_menu_keyboard(user=None):
    """Формирует клавиатуру админки в зависимости от прав пользователя (умная сетка 2x2)"""
    keyboard_buttons = []
    
    # 📊 АНАЛИТИКА И ДАННЫЕ (только для can_view_revenue)
    if user and can_view_revenue(user):
        # Заголовок секции с кренделями
        keyboard_buttons.append([
            InlineKeyboardButton(text="🥨 АНАЛИТИКА И ДАННЫЕ 🥨", callback_data="ignore")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton(text="📈 Аналитика", callback_data="admin_analytics")
        ])
    
    # 👤 ПОЛЬЗОВАТЕЛИ (для всех админов)
    keyboard_buttons.append([
        InlineKeyboardButton(text="🥨 ПОЛЬЗОВАТЕЛИ 🥨", callback_data="ignore")
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(text="👤 Пользователи", callback_data="admin_users_menu"),
        InlineKeyboardButton(text="🤝 Реф. связи", callback_data="admin_referral_info")
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(text="⭐ Избранное", callback_data="admin_favorites:0")
    ])
    
    # ⚙️ УПРАВЛЕНИЕ И НАСТРОЙКИ (только для can_manage_admins)
    if user and can_manage_admins(user):
        keyboard_buttons.append([
            InlineKeyboardButton(text="🥨 УПРАВЛЕНИЕ И НАСТРОЙКИ 🥨", callback_data="ignore")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_manage_promocodes"),
            InlineKeyboardButton(text="🔄 Автопродления", callback_data="admin_autorenew_menu")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="⚙️ Админы", callback_data="admin_manage_admins"),
            InlineKeyboardButton(text="🚫 Заявки", callback_data="admin_cancellation_requests")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="💸 Заявки на вывод", callback_data="admin_withdrawals")
        ])
    else:
        # Для обычных админов только заявки (одна кнопка)
        keyboard_buttons.append([
            InlineKeyboardButton(text="🚫 Заявки на отмену", callback_data="admin_cancellation_requests")
        ])
    
    # 📅 КАЛЕНДАРЬ И СРОКИ (для всех админов)
    keyboard_buttons.append([
        InlineKeyboardButton(text="🥨 КАЛЕНДАРЬ И СРОКИ 🥨", callback_data="ignore")
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(text="📅 Сроки подписок", callback_data="admin_subscription_dates"),
        InlineKeyboardButton(text="🎂 Дни рождения", callback_data="admin_birthdays:0")
    ])
    
    # Закрыть
    keyboard_buttons.append([
        InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)


@core_router.callback_query(F.data == "admin_cancel")
async def process_cancel(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    await state.clear()
    async with AsyncSessionLocal() as session:
        current_user = await get_user_by_telegram_id(session, callback.from_user.id)
        keyboard = _admin_menu_keyboard(current_user)
    banner_path = os.path.join(os.getcwd(), "media", "админка.jpg")
    try:
        await callback.message.delete()
    except Exception:
        pass
    banner_photo = FSInputFile(banner_path)
    await callback.message.answer_photo(photo=banner_photo, caption="Операция отменена.\nПанель администратора Mom's Club:", reply_markup=keyboard)
    await callback.answer()


@core_router.callback_query(F.data == "admin_back")
async def process_back(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    try:
        await state.clear()
    except Exception:
        pass
    await callback.answer()
    async with AsyncSessionLocal() as session:
        current_user = await get_user_by_telegram_id(session, callback.from_user.id)
        keyboard = _admin_menu_keyboard(current_user)
    banner_path = os.path.join(os.getcwd(), "media", "админка.jpg")
    banner_photo = FSInputFile(banner_path)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer_photo(photo=banner_photo, caption="Панель администратора Mom's Club:", reply_markup=keyboard)


@core_router.callback_query(F.data == "ignore")
async def process_ignore(callback: CallbackQuery):
    """Обработчик для заголовков-разделителей (не делает ничего)"""
    await callback.answer()


@core_router.callback_query(F.data == "admin_close")
async def process_close(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@core_router.callback_query(F.data == "ignore")
async def process_ignore(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок (снимает индикатор)."""
    await callback.answer()