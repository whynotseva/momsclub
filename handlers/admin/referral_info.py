"""
Админка - информация о реферальной программе пользователя
"""

from aiogram import Router, F, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_user_by_id,
    get_referral_rewards,
    add_referral_balance,
    deduct_referral_balance
)
from utils.admin_permissions import is_admin, can_manage_admins
from sqlalchemy import select, func as sql_func
from database.models import User as UserModel, ReferralReward, WithdrawalRequest
import logging

logger = logging.getLogger(__name__)
referral_info_router = Router()


class AdminReferralStates(StatesGroup):
    """Состояния FSM для работы с реферальными начислениями"""
    waiting_add_amount = State()
    waiting_deduct_amount = State()


def register_admin_referral_info_handlers(dp):
    """Регистрирует обработчики информации о реферальной программе"""
    dp.include_router(referral_info_router)


async def get_referral_section_for_user(session, user_id: int) -> tuple[str, list]:
    """
    Формирует секцию с информацией о реферальной программе для карточки пользователя
    
    Returns:
        tuple: (текст_секции, список_кнопок)
    """
    try:
        user = await get_user_by_id(session, user_id)
        if not user:
            return "", []
        
        # Получаем статистику
        balance = user.referral_balance or 0
        total_earned = user.total_earned_referral or 0
        total_paid = user.total_referrals_paid or 0
        
        # Считаем всех приглашенных
        total_referrals_query = select(sql_func.count(UserModel.id)).where(UserModel.referrer_id == user.id)
        total_referrals = await session.scalar(total_referrals_query) or 0
        
        # Считаем награды по типам
        rewards_query = select(
            ReferralReward.reward_type,
            sql_func.count(ReferralReward.id),
            sql_func.sum(ReferralReward.reward_amount)
        ).where(
            ReferralReward.referrer_id == user.id
        ).group_by(ReferralReward.reward_type)
        
        rewards_result = await session.execute(rewards_query)
        rewards_stats = {row[0]: (row[1], row[2]) for row in rewards_result}
        
        money_count = rewards_stats.get('money', (0, 0))[0]
        money_sum = rewards_stats.get('money', (0, 0))[1] or 0
        days_count = rewards_stats.get('days', (0, 0))[0]
        days_sum = rewards_stats.get('days', (0, 0))[1] or 0
        
        # Формируем текст
        text = "\n\n🤝 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА 2.0</b>\n"
        text += f"💰 <b>Баланс:</b> {balance:,}₽\n"
        text += f"📊 <b>Всего заработано:</b> {total_earned:,}₽\n"
        text += f"👥 <b>Приглашено:</b> {total_referrals} чел.\n"
        text += f"💳 <b>Оплатили:</b> {total_paid} чел.\n\n"
        
        text += "<b>📈 Статистика выборов:</b>\n"
        text += f"  💰 Деньги: {money_count} раз ({money_sum:,}₽)\n"
        text += f"  📅 Дни: {days_count} раз ({days_sum} дн.)\n"
        
        # Формируем кнопки
        buttons = [
            [InlineKeyboardButton(
                text="📊 История начислений",
                callback_data=f"admin_ref_history:{user.telegram_id}"
            )]
        ]
        
        # Кнопка управления балансом только для супер-админов
        buttons.append([
            InlineKeyboardButton(
                text="💰 Управление балансом",
                callback_data=f"admin_ref_balance_menu:{user.telegram_id}"
            )
        ])
        
        return text, buttons
        
    except Exception as e:
        logger.error(f"Ошибка в get_referral_section_for_user: {e}", exc_info=True)
        return "", []


@referral_info_router.callback_query(F.data.startswith("admin_ref_history:"))
async def show_referral_history(callback: CallbackQuery):
    """Показывает историю реферальных начислений пользователя"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not is_admin(admin):
                await callback.answer("❌ Нет доступа", show_alert=True)
                return
            
            telegram_id = int(callback.data.split(":")[1])
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            # Получаем историю наград
            rewards = await get_referral_rewards(session, user.id, limit=20)
            
            # Получаем историю выводов
            withdrawals_query = select(WithdrawalRequest).where(
                WithdrawalRequest.user_id == user.id,
                WithdrawalRequest.status.in_(['approved', 'rejected'])
            ).order_by(WithdrawalRequest.created_at.desc()).limit(20)
            withdrawals_result = await session.execute(withdrawals_query)
            withdrawals = withdrawals_result.scalars().all()
            
            # Получаем ручные начисления админов
            from database.models import AdminBalanceAdjustment
            adjustments_query = select(AdminBalanceAdjustment).where(
                AdminBalanceAdjustment.user_id == user.id
            ).order_by(AdminBalanceAdjustment.created_at.desc()).limit(20)
            adjustments_result = await session.execute(adjustments_query)
            adjustments = adjustments_result.scalars().all()
            
            text = f"📊 <b>История операций</b>\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {telegram_id}\n"
            text += f"💰 Текущий баланс: {user.referral_balance or 0:,}₽\n\n"
            
            # Объединяем награды и списания в один список
            all_operations = []
            
            # Добавляем награды (rewards это список кортежей (reward, referee))
            for reward, referee in rewards:
                all_operations.append({
                    'type': 'reward',
                    'date': reward.created_at,
                    'data': reward,
                    'referee': referee
                })
            
            # Добавляем списания
            for withdrawal in withdrawals:
                all_operations.append({
                    'type': 'withdrawal',
                    'date': withdrawal.created_at,
                    'data': withdrawal
                })
            
            # Добавляем ручные начисления админов
            for adjustment in adjustments:
                all_operations.append({
                    'type': 'adjustment',
                    'date': adjustment.created_at,
                    'data': adjustment
                })
            
            # Сортируем по дате (новые сверху)
            all_operations.sort(key=lambda x: x['date'], reverse=True)
            
            if not all_operations:
                text += "📋 Нет операций"
            else:
                for op in all_operations[:20]:  # Показываем последние 20
                    date_str = op['date'].strftime('%d.%m.%Y %H:%M')
                    
                    if op['type'] == 'reward':
                        reward = op['data']
                        referee = op['referee']
                        referee_name = referee.first_name if referee else "Неизвестно"
                        if referee and referee.username:
                            referee_name = f"@{referee.username}"
                        
                        if reward.reward_type == 'money':
                            text += f"💰 <b>+{reward.reward_amount}₽</b> от {referee_name}\n"
                        else:
                            text += f"📅 <b>+{reward.reward_amount} дн.</b> от {referee_name}\n"
                        
                        text += f"   🎯 {reward.bonus_percent}% · {date_str}\n\n"
                    
                    elif op['type'] == 'withdrawal':
                        withdrawal = op['data']
                        status_emoji = "✅" if withdrawal.status == 'approved' else "❌"
                        status_text = "Одобрено" if withdrawal.status == 'approved' else "Отклонено"
                        text += f"💸 <b>-{withdrawal.amount:,}₽</b> вывод {status_emoji}\n"
                        text += f"   {status_text} · {date_str}\n\n"
                    
                    elif op['type'] == 'adjustment':
                        adjustment = op['data']
                        admin_name = "админом"
                        if adjustment.admin:
                            admin_name = f"@{adjustment.admin.username}" if adjustment.admin.username else adjustment.admin.first_name
                        
                        # Начисление или списание
                        if adjustment.amount > 0:
                            text += f"🎁 <b>+{adjustment.amount:,}₽</b> начислено {admin_name}\n"
                        else:
                            text += f"➖ <b>{adjustment.amount:,}₽</b> списано {admin_name}\n"
                        text += f"   {date_str}\n\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="« Назад к пользователю",
                    callback_data=f"admin_user_info:{telegram_id}"
                )]
            ])
            
            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                # Если не получилось отредактировать (сообщение с картинкой)
                await callback.message.delete()
                await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в show_referral_history: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@referral_info_router.callback_query(F.data.startswith("admin_ref_balance_menu:"))
async def show_balance_menu(callback: CallbackQuery):
    """Показывает меню управления балансом"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                return
            
            telegram_id = int(callback.data.split(":")[1])
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            text = f"💰 <b>Управление балансом</b>\n\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {telegram_id}\n"
            text += f"💰 Текущий баланс: <b>{user.referral_balance or 0:,}₽</b>\n\n"
            text += "Выберите действие:"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Начислить деньги", callback_data=f"admin_ref_add_money:{telegram_id}")],
                [InlineKeyboardButton(text="➖ Списать деньги", callback_data=f"admin_ref_deduct_menu:{telegram_id}")],
                [InlineKeyboardButton(text="« Назад к пользователю", callback_data=f"admin_user_info:{telegram_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в show_balance_menu: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@referral_info_router.callback_query(F.data.startswith("admin_ref_deduct_menu:"))
async def show_deduct_menu(callback: CallbackQuery):
    """Показывает меню списания"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                return
            
            telegram_id = int(callback.data.split(":")[1])
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            balance = user.referral_balance or 0
            
            text = f"➖ <b>Списание средств</b>\n\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {telegram_id}\n"
            text += f"💰 Текущий баланс: <b>{balance:,}₽</b>\n\n"
            text += "Выберите действие:"
            
            keyboard_buttons = []
            
            # Кнопка списания всего баланса (если баланс > 0)
            if balance > 0:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text=f"🗑 Списать весь баланс ({balance:,}₽)",
                        callback_data=f"admin_ref_deduct_all:{telegram_id}"
                    )
                ])
            
            # Кнопка списания определенной суммы
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text="💵 Списать определенную сумму",
                    callback_data=f"admin_ref_deduct_custom:{telegram_id}"
                )
            ])
            
            keyboard_buttons.append([
                InlineKeyboardButton(text="« Назад", callback_data=f"admin_ref_balance_menu:{telegram_id}")
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в show_deduct_menu: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@referral_info_router.callback_query(F.data.startswith("admin_ref_add_money:"))
async def start_add_money(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс ручного начисления денег пользователю"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                return
            
            telegram_id = int(callback.data.split(":")[1])
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            await state.update_data(target_user_id=user.id, target_telegram_id=telegram_id)
            
            text = f"➕ <b>Начисление средств</b>\n\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {telegram_id}\n"
            text += f"💰 Текущий баланс: {user.referral_balance or 0:,}₽\n\n"
            text += "Введите сумму для начисления (в рублях):\n"
            text += "Например: <code>1000</code>\n\n"
            text += "Или нажмите кнопку отмены"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data=f"admin_ref_balance_menu:{telegram_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await state.set_state(AdminReferralStates.waiting_add_amount)
            
    except Exception as e:
        logger.error(f"Ошибка в start_add_money: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@referral_info_router.message(AdminReferralStates.waiting_add_amount)
async def process_add_money_amount(message: Message, state: FSMContext):
    """Обрабатывает ввод суммы для начисления"""
    try:
        # Проверка прав
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, message.from_user.id)
            if not can_manage_admins(admin):
                await message.answer("❌ Только для супер-админов")
                await state.clear()
                return
            
            # Валидация суммы
            try:
                amount = int(message.text.strip())
                if amount <= 0:
                    raise ValueError("Сумма должна быть положительной")
                if amount > 100000:
                    raise ValueError("Слишком большая сумма (макс. 100,000₽)")
            except ValueError as e:
                await message.answer(f"❌ Некорректная сумма: {e}\n\nПопробуйте еще раз или /cancel")
                return
            
            # Получаем данные из state
            data = await state.get_data()
            target_user_id = data['target_user_id']
            target_telegram_id = data['target_telegram_id']
            
            user = await get_user_by_id(session, target_user_id)
            if not user:
                await message.answer("❌ Пользователь не найден")
                await state.clear()
                return
            
            # Подтверждение
            text = f"💰 <b>Подтверждение начисления</b>\n\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {target_telegram_id}\n\n"
            text += f"💰 Сумма: <b>{amount:,}₽</b>\n"
            text += f"📊 Текущий баланс: {user.referral_balance or 0}₽\n"
            text += f"➡️ Новый баланс: {(user.referral_balance or 0) + amount}₽\n\n"
            text += "Подтвердить начисление?"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_ref_confirm:{amount}"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_ref_cancel")
                ]
            ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в process_add_money_amount: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка")
        await state.clear()


@referral_info_router.callback_query(F.data.startswith("admin_ref_confirm:"))
async def confirm_add_money(callback: CallbackQuery, state: FSMContext):
    """Подтверждает и выполняет начисление"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                await state.clear()
                return
            
            amount = int(callback.data.split(":")[1])
            data = await state.get_data()
            target_user_id = data['target_user_id']
            target_telegram_id = data['target_telegram_id']
            
            user = await get_user_by_id(session, target_user_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                await state.clear()
                return
            
            # Начисляем
            success = await add_referral_balance(session, target_user_id, amount)
            
            if success:
                # Создаём запись о ручном начислении
                from database.models import AdminBalanceAdjustment
                adjustment = AdminBalanceAdjustment(
                    user_id=target_user_id,
                    admin_id=admin.id,
                    amount=amount,
                    comment=f"Ручное начисление админом {admin.username or admin.first_name}"
                )
                session.add(adjustment)
                await session.commit()
                
                await session.refresh(user)
                
                # Уведомляем пользователя
                try:
                    user_text = f"🎁 <b>Начисление средств</b>\n\n"
                    user_text += f"Вам начислено <b>{amount:,}₽</b> на реферальный баланс!\n\n"
                    user_text += f"💰 Ваш баланс: {user.referral_balance:,}₽\n\n"
                    user_text += f"Вы можете использовать средства для оплаты подписки или вывести их."
                    
                    await callback.bot.send_message(target_telegram_id, user_text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {target_telegram_id}: {e}")
                
                # Уведомляем админа
                text = f"✅ <b>Успешно начислено!</b>\n\n"
                text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                text += f"📱 ID: {target_telegram_id}\n"
                text += f"💰 Начислено: {amount:,}₽\n"
                text += f"📊 Новый баланс: {user.referral_balance:,}₽"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="« Назад к пользователю",
                        callback_data=f"admin_user_info:{target_telegram_id}"
                    )]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.answer("❌ Ошибка при начислении", show_alert=True)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в confirm_add_money: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()


@referral_info_router.callback_query(F.data.startswith("admin_ref_deduct_all:"))
async def confirm_deduct_all(callback: CallbackQuery):
    """Подтверждение списания всего баланса"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                return
            
            telegram_id = int(callback.data.split(":")[1])
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            balance = user.referral_balance or 0
            
            if balance <= 0:
                await callback.answer("❌ Баланс уже пуст", show_alert=True)
                return
            
            # Списываем весь баланс
            success = await deduct_referral_balance(session, user.id, balance)
            
            if success:
                # Создаём запись о списании
                from database.models import AdminBalanceAdjustment
                adjustment = AdminBalanceAdjustment(
                    user_id=user.id,
                    admin_id=admin.id,
                    amount=-balance,  # Отрицательное значение для списания
                    comment=f"Списание всего баланса админом {admin.username or admin.first_name}"
                )
                session.add(adjustment)
                await session.commit()
                
                # Уведомляем пользователя
                try:
                    user_text = f"⚠️ <b>Списание средств</b>\n\n"
                    user_text += f"С вашего реферального баланса списано <b>{balance:,}₽</b>.\n\n"
                    user_text += f"💰 Текущий баланс: 0₽"
                    
                    await callback.bot.send_message(telegram_id, user_text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {telegram_id}: {e}")
                
                text = f"✅ <b>Успешно списано!</b>\n\n"
                text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                text += f"📱 ID: {telegram_id}\n"
                text += f"💸 Списано: {balance:,}₽\n"
                text += f"📊 Новый баланс: 0₽"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="« Назад к пользователю",
                        callback_data=f"admin_user_info:{telegram_id}"
                    )]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.answer("❌ Ошибка при списании", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка в confirm_deduct_all: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@referral_info_router.callback_query(F.data.startswith("admin_ref_deduct_custom:"))
async def start_deduct_custom(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс списания определенной суммы"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                return
            
            telegram_id = int(callback.data.split(":")[1])
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            await state.update_data(target_user_id=user.id, target_telegram_id=telegram_id)
            
            text = f"➖ <b>Списание средств</b>\n\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {telegram_id}\n"
            text += f"💰 Текущий баланс: {user.referral_balance or 0:,}₽\n\n"
            text += "Введите сумму для списания (в рублях):\n"
            text += "Например: <code>500</code>\n\n"
            text += "Или нажмите кнопку отмены"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data=f"admin_ref_deduct_menu:{telegram_id}")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await state.set_state(AdminReferralStates.waiting_deduct_amount)
            
    except Exception as e:
        logger.error(f"Ошибка в start_deduct_custom: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@referral_info_router.message(AdminReferralStates.waiting_deduct_amount)
async def process_deduct_amount(message: Message, state: FSMContext):
    """Обрабатывает ввод суммы для списания"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, message.from_user.id)
            if not can_manage_admins(admin):
                await message.answer("❌ Только для супер-админов")
                await state.clear()
                return
            
            # Валидация суммы
            try:
                amount = int(message.text.strip())
                if amount <= 0:
                    raise ValueError("Сумма должна быть положительной")
                if amount > 100000:
                    raise ValueError("Слишком большая сумма (макс. 100,000₽)")
            except ValueError as e:
                await message.answer(f"❌ Некорректная сумма: {e}\n\nПопробуйте еще раз или /cancel")
                return
            
            data = await state.get_data()
            target_user_id = data['target_user_id']
            target_telegram_id = data['target_telegram_id']
            
            user = await get_user_by_id(session, target_user_id)
            if not user:
                await message.answer("❌ Пользователь не найден")
                await state.clear()
                return
            
            balance = user.referral_balance or 0
            
            # Проверка достаточности средств
            if amount > balance:
                await message.answer(
                    f"❌ Недостаточно средств!\n\n"
                    f"💰 Текущий баланс: {balance:,}₽\n"
                    f"📝 Вы пытаетесь списать: {amount:,}₽\n\n"
                    f"Попробуйте ввести меньшую сумму или /cancel"
                )
                return
            
            # Подтверждение
            text = f"⚠️ <b>Подтверждение списания</b>\n\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
            text += f"📱 ID: {target_telegram_id}\n\n"
            text += f"💸 Сумма списания: <b>{amount:,}₽</b>\n"
            text += f"📊 Текущий баланс: {balance}₽\n"
            text += f"➡️ Новый баланс: {balance - amount}₽\n\n"
            text += "Подтвердить списание?"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_ref_deduct_confirm:{amount}"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_ref_deduct_menu:{target_telegram_id}")
                ]
            ])
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в process_deduct_amount: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка")
        await state.clear()


@referral_info_router.callback_query(F.data.startswith("admin_ref_deduct_confirm:"))
async def confirm_deduct(callback: CallbackQuery, state: FSMContext):
    """Подтверждает и выполняет списание"""
    try:
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not can_manage_admins(admin):
                await callback.answer("❌ Только для супер-админов", show_alert=True)
                await state.clear()
                return
            
            amount = int(callback.data.split(":")[1])
            data = await state.get_data()
            target_user_id = data['target_user_id']
            target_telegram_id = data['target_telegram_id']
            
            user = await get_user_by_id(session, target_user_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                await state.clear()
                return
            
            # Списываем
            success = await deduct_referral_balance(session, target_user_id, amount)
            
            if success:
                # Создаём запись о списании
                from database.models import AdminBalanceAdjustment
                adjustment = AdminBalanceAdjustment(
                    user_id=target_user_id,
                    admin_id=admin.id,
                    amount=-amount,  # Отрицательное значение
                    comment=f"Списание админом {admin.username or admin.first_name}"
                )
                session.add(adjustment)
                await session.commit()
                
                await session.refresh(user)
                
                # Уведомляем пользователя
                try:
                    user_text = f"⚠️ <b>Списание средств</b>\n\n"
                    user_text += f"С вашего реферального баланса списано <b>{amount:,}₽</b>.\n\n"
                    user_text += f"💰 Текущий баланс: {user.referral_balance:,}₽"
                    
                    await callback.bot.send_message(target_telegram_id, user_text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {target_telegram_id}: {e}")
                
                text = f"✅ <b>Успешно списано!</b>\n\n"
                text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
                text += f"📱 ID: {target_telegram_id}\n"
                text += f"💸 Списано: {amount:,}₽\n"
                text += f"📊 Новый баланс: {user.referral_balance:,}₽"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="« Назад к пользователю",
                        callback_data=f"admin_user_info:{target_telegram_id}"
                    )]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.answer("❌ Ошибка при списании", show_alert=True)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в confirm_deduct: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()


@referral_info_router.callback_query(F.data == "admin_ref_cancel")
async def cancel_add_money(callback: CallbackQuery, state: FSMContext):
    """Отменяет начисление"""
    try:
        data = await state.get_data()
        target_telegram_id = data.get('target_telegram_id')
        
        await callback.message.edit_text(
            "❌ Операция отменена",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="« Назад к пользователю",
                    callback_data=f"admin_user_info:{target_telegram_id}"
                )]
            ]) if target_telegram_id else None
        )
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в cancel_add_money: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()
