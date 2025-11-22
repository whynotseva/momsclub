"""
Шаблоны сообщений для реферальной системы 2.0
Все тексты пушей в одном месте для легкого изменения
"""


def get_reward_choice_text(
    referee_name: str,
    money_amount: int,
    bonus_percent: int,
    loyalty_emoji: str,
    can_get_money: bool
) -> str:
    """
    Текст уведомления о выборе награды
    
    Args:
        referee_name: Имя реферала
        money_amount: Размер денежной награды
        bonus_percent: Процент бонуса
        loyalty_emoji: Эмодзи уровня лояльности
        can_get_money: Доступна ли денежная награда
        
    Returns:
        Отформатированный текст
    """
    text = (
        f"🎁 <b>Отличные новости!</b>\n\n"
        f"Пользователь {referee_name} оплатил подписку!\n\n"
        f"💰 <b>Ваш бонус:</b> {money_amount:,}₽ ({bonus_percent}% {loyalty_emoji})\n\n"
        f"Выберите награду:"
    )
    
    if not can_get_money:
        text += (
            "\n\n⚠️ <i>Денежные награды недоступны для администраторов "
            "и пользователей с бесконечной подпиской</i>"
        )
    
    return text


def get_money_reward_success_text(amount: int, new_balance: int) -> str:
    """
    Текст успешного начисления денежной награды
    
    Args:
        amount: Начисленная сумма
        new_balance: Новый баланс
        
    Returns:
        Отформатированный текст
    """
    return (
        f"✅ <b>Успешно зачислено!</b>\n\n"
        f"💰 +{amount:,}₽ на ваш реферальный баланс\n\n"
        f"📊 Текущий баланс: {new_balance:,}₽\n\n"
        f"Используйте баланс для оплаты подписки или выведите от 500₽ на карту!"
    )


def get_days_reward_success_text(days: int, end_date: str) -> str:
    """
    Текст успешного начисления дней подписки
    
    Args:
        days: Количество дней
        end_date: Новая дата окончания подписки
        
    Returns:
        Отформатированный текст
    """
    return (
        f"✅ <b>Успешно зачислено!</b>\n\n"
        f"📅 +{days} дней к вашей подписке\n\n"
        f"🗓 Новая дата окончания: {end_date}\n\n"
        f"Спасибо за участие в реферальной программе! 💖"
    )


def get_withdrawal_start_text(balance: int, min_amount: int) -> str:
    """
    Текст начала процесса вывода средств
    
    Args:
        balance: Текущий баланс
        min_amount: Минимальная сумма вывода
        
    Returns:
        Отформатированный текст
    """
    return (
        f"💸 <b>Вывод средств</b>\n\n"
        f"💰 Доступно к выводу: {balance:,}₽\n"
        f"⚠️ Минимальная сумма: {min_amount}₽\n"
        f"⏰ Срок зачисления: от 1 часа до 5 дней\n\n"
        f"Выберите способ вывода:"
    )


def get_withdrawal_confirmation_text(amount: int, masked_details: str, payment_method: str) -> str:
    """
    Текст подтверждения вывода средств
    
    Args:
        amount: Сумма вывода
        masked_details: Маскированные реквизиты
        payment_method: Способ вывода
        
    Returns:
        Отформатированный текст
    """
    method_icon = "💳" if payment_method == "card" else "📱"
    method_text = "Карта" if payment_method == "card" else "СБП"
    
    return (
        f"{method_icon} <b>Подтверждение вывода</b>\n\n"
        f"💰 Сумма: {amount:,}₽\n"
        f"📇 {method_text}: <code>{masked_details}</code>\n\n"
        f"⚠️ Заявка будет отправлена на модерацию администраторам.\n"
        f"⏰ Средства поступят от 1 часа до 5 дней.\n\n"
        f"Подтвердите вывод:"
    )


def get_withdrawal_request_created_text(amount: int, payment_details: str) -> str:
    """
    Текст подтверждения создания заявки на вывод
    
    Args:
        amount: Сумма вывода
        payment_details: Маскированные реквизиты
        
    Returns:
        Отформатированный текст
    """
    return (
        f"✅ <b>Заявка создана!</b>\n\n"
        f"💰 Сумма: {amount:,}₽\n"
        f"📇 Реквизиты: {payment_details}\n\n"
        f"📋 Ваша заявка отправлена на модерацию.\n"
        f"⏰ Средства поступят от 1 часа до 5 дней.\n\n"
        f"Вы получите уведомление о результате! 💌"
    )


def get_withdrawal_approved_text(amount: int, payment_details: str) -> str:
    """
    Текст одобрения заявки на вывод
    
    Args:
        amount: Сумма вывода
        payment_details: Реквизиты
        
    Returns:
        Отформатированный текст
    """
    return (
        f"✅ <b>Заявка на вывод одобрена!</b>\n\n"
        f"💰 Сумма: {amount:,}₽\n"
        f"📇 Реквизиты: {payment_details}\n\n"
        f"⏰ Средства поступят от 1 часа до 5 дней! 💌"
    )


def get_withdrawal_rejected_text(amount: int, reason: str) -> str:
    """
    Текст отклонения заявки на вывод
    
    Args:
        amount: Сумма вывода
        reason: Причина отклонения
        
    Returns:
        Отформатированный текст
    """
    return (
        f"❌ <b>Заявка на вывод отклонена</b>\n\n"
        f"💰 Сумма: {amount:,}₽\n\n"
        f"📝 Причина: {reason}\n\n"
        f"💡 Пожалуйста, создайте новую заявку с корректными данными."
    )


def get_referral_program_text(
    balance: int,
    total_earned: int,
    total_referrals: int,
    total_paid: int,
    level_name: str,
    bonus_percent: int,
    referral_link: str
) -> str:
    """
    Текст главного экрана реферальной программы
    
    Args:
        balance: Текущий баланс
        total_earned: Всего заработано
        total_referrals: Всего приглашено
        total_paid: Сколько оплатили
        level_name: Название уровня
        bonus_percent: Процент бонуса
        referral_link: Реферальная ссылка
        
    Returns:
        Отформатированный текст
    """
    # Мотивация и прогресс
    motivation_text = ""
    if balance >= 500:
        motivation_text = f"\n🎉 <b>Поздравляем!</b> Вы можете вывести {balance:,}₽!\n"
    else:
        # Показываем прогресс даже при нулевом балансе
        remaining = 500 - balance
        progress_percent = int((balance / 500) * 100)
        progress_bar = "█" * (progress_percent // 10) + "░" * (10 - (progress_percent // 10))
        
        if balance == 0:
            motivation_text = (
                f"\n💡 <b>Начните зарабатывать!</b>\n"
                f"🎯 До первого вывода: 500₽\n"
                f"📊 Прогресс: {progress_bar} 0%\n"
            )
        else:
            motivation_text = (
                f"\n🎯 <b>До вывода осталось:</b> {remaining:,}₽\n"
                f"📊 Прогресс: {progress_bar} {progress_percent}%\n"
            )
    
    return (
        f"🤝 <b>Реферальная программа</b>\n\n"
        f"💰 <b>Ваш баланс:</b> {balance:,}₽\n"
        f"📊 <b>Всего заработано:</b> {total_earned:,}₽\n"
        f"👥 <b>Приглашено друзей:</b> {total_referrals}\n"
        f"💳 <b>Оплатили подписку:</b> {total_paid}\n"
        f"{motivation_text}\n"
        f"📈 <b>Ваш уровень:</b> {level_name} ({bonus_percent}%)\n\n"
        f"💡 <b>Как это работает:</b>\n"
        f"1️⃣ Отправьте свою реферальную ссылку друзьям\n"
        f"2️⃣ Когда друг перейдет по ссылке и оформит подписку\n"
        f"3️⃣ Вы получите выбор: <b>деньги ({bonus_percent}%)</b> или <b>7 дней</b> к подписке 🎁\n"
        f"4️⃣ Накопленные деньги можно вывести от 500₽ на карту или СБП\n"
        f"5️⃣ Вывод средств занимает от 1 часа до 5 дней\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"Нажмите кнопку ниже, чтобы поделиться ссылкой! 💌"
    )


def get_referral_history_text(rewards_list: list) -> str:
    """
    Текст истории реферальных начислений
    
    Args:
        rewards_list: Список кортежей (награда, реферал)
        
    Returns:
        Отформатированный текст
    """
    if not rewards_list:
        return (
            "📊 <b>История начислений</b>\n\n"
            "У вас пока нет начислений.\n\n"
            "<i>Приглашайте друзей и зарабатывайте бонусы!</i>"
        )
    
    text = "📊 <b>История начислений</b>\n\n"
    
    for reward, referee in rewards_list:
        referee_name = referee.username or referee.first_name or f"ID:{referee.telegram_id}"
        reward_icon = "💰" if reward.reward_type == "money" else "📅"
        
        if reward.reward_type == "money":
            amount_text = f"{reward.reward_amount:,}₽"
        else:
            amount_text = f"{reward.reward_amount}д"
        
        date_text = reward.created_at.strftime('%d.%m.%Y %H:%M')
        
        text += f"{reward_icon} <b>{amount_text}</b> от @{referee_name}\n"
        text += f"   {date_text}\n\n"
    
    return text


def get_admin_withdrawal_notification_text(
    user_name: str,
    user_id: int,
    amount: int,
    payment_details: str,
    payment_method: str
) -> str:
    """
    Текст уведомления админам о новой заявке на вывод
    
    Args:
        user_name: Имя пользователя
        user_id: Telegram ID пользователя
        amount: Сумма вывода
        payment_details: Реквизиты
        payment_method: Способ вывода
        
    Returns:
        Отформатированный текст
    """
    method_icon = "💳" if payment_method == "card" else "📱"
    method_text = "Карта" if payment_method == "card" else "СБП"
    
    return (
        f"💸 <b>НОВАЯ ЗАЯВКА НА ВЫВОД</b>\n\n"
        f"👤 {user_name} (ID: {user_id})\n"
        f"💰 Сумма: {amount:,}₽\n"
        f"{method_icon} {method_text}: {payment_details}\n\n"
        f"Перейдите в админку для обработки заявки."
    )
