"""
Файл с константами проекта
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Токены и основные настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ссылка на закрытый канал
CLUB_CHANNEL_URL = "https://t.me/+Z77jamwsi1hiNTZi"  # Обновляем на постоянную ссылку

# ID группы - нужно заменить на актуальный ID
CLUB_GROUP_ID = -1002417284888  # ID группы заказчика

# ID темы в группе (для форумов)
CLUB_GROUP_TOPIC_ID = 4  # ID темы для отправки приветственных сообщений

# Стоимость подписки в рублях
SUBSCRIPTION_PRICE_FIRST = 690  # Специальная цена для первой оплаты
SUBSCRIPTION_PRICE = 990  # Обычная цена подписки

# Длительность подписки в днях
SUBSCRIPTION_DAYS = 30

# Дополнительные тарифы подписки
# 2 месяца за 10 руб
SUBSCRIPTION_PRICE_2MONTHS = 1790
SUBSCRIPTION_DAYS_2MONTHS = 60

# 3 месяца за 150 руб
SUBSCRIPTION_PRICE_3MONTHS = 2490
SUBSCRIPTION_DAYS_3MONTHS = 90

# Количество дней перед окончанием подписки для отправки уведомления
NOTIFICATION_DAYS_BEFORE = 1  # За 1 день (последнее напоминание)
NOTIFICATION_DAYS_BEFORE_EARLY = 7  # За 7 дней (раннее напоминание)

# Путь к изображению
WELCOME_IMAGE_PATH = os.path.join("media", "mainbaner.png")

# Количество дней, которые начисляются участникам реферальной программы
REFERRAL_BONUS_DAYS = 7

# Конфигурация персональных промокодов для возврата пользователей
RETURN_PROMO_CONFIG = {
    'none': {
        'discount_percent': 10,  # 10% скидка
        'message_emoji': '💕',
        'level_name': 'участник',
        'message_text': 'Мы подготовили для тебя особый подарок для возврата!'
    },
    'silver': {
        'discount_percent': 15,  # 15% скидка
        'message_emoji': '🥈',
        'level_name': 'Silver участник',
        'message_text': 'Как наш Silver участник, ты получаешь особый подарок для возврата!'
    },
    'gold': {
        'discount_percent': 20,  # 20% скидка
        'message_emoji': '🥇',
        'level_name': 'Gold участник',
        'message_text': 'Как наш Gold участник, мы подготовили для тебя особый подарок для возврата!'
    },
    'platinum': {
        'discount_percent': 25,  # 25% скидка
        'message_emoji': '💎',
        'level_name': 'Platinum участник',
        'message_text': 'Как наш Platinum участник, ты получаешь особый подарок для возврата!'
    }
}

# Настройки защиты от злоупотребления промокодами возврата
MAX_RETURN_PROMOS = 3  # Максимум промокодов возврата за всё время
MIN_DAYS_BETWEEN_RETURN_PROMOS = 90  # Минимум дней между промокодами (3 месяца)
DISCOUNT_REDUCTION_PER_USE = 5  # Уменьшение скидки на N% за каждое использование

# Приветственный текст
WELCOME_TEXT = """Привет, красотка 🤎



Добро пожаловать в <b>Mom's Club</b> — пространство для мам, которые растут как блогеры, эксперты и творческие женщины.

🎞️ <b>Что внутри?</b>

— подборки вирусных Reels и идей для постов

— лайфхаки по блогингу и развитие личного бренда

— челленджи и контент-марафоны

— подкасты, разборы и ответы на вопросы

— поддержка твоего контента

— уютное комьюнити из мам-креаторов

— предложения от брендов для сотрудничеств

💎 <b>Система лояльности</b>

Чем дольше ты с нами, тем больше бонусов: уровни <b>Silver → Gold → Platinum</b>, скидки и доп. дни доступа.

🌍 <b>Живые встречи</b>

Проводим офлайн-собрания в разных городах — общаемся, вдохновляемся, растём вместе.

✨ <b>Экосистема мам-креаторов</b>

<b>Mom's Club</b> — место, где ты развиваешь блог, находишь поддержку, идеи и окружение, которое понимает.

Оплачивая доступ, ты принимаешь <a href="https://telegra.ph/Publichnaya-oferta-Moms-Club-04-12">публичную оферту</a>.

<b>Готова присоединиться?</b> Жми ниже 🤎"""

# Порог для определения бесконечной (пожизненной) подписки
# Подписки с end_date >= LIFETIME_THRESHOLD считаются пожизненными
from datetime import datetime
LIFETIME_THRESHOLD = datetime(2099, 1, 1)

# Группа для пожизненных подписок (для отображения)
LIFETIME_SUBSCRIPTION_GROUP = "∞"

# Список ID администраторов (для обратной совместимости)
ADMIN_IDS = []
admin_ids_str = os.getenv("ADMIN_ID", "")
if admin_ids_str:
    try:
        # Разбиваем строку с ID администраторов по запятой
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in admin_ids_str.split(",") if admin_id.strip()]
        print(f"[constants.py] Загружены ID администраторов: {ADMIN_IDS}")
        if not ADMIN_IDS:
            print("[constants.py] ВНИМАНИЕ: Список администраторов пуст! Проверьте переменную окружения ADMIN_ID")
    except Exception as e:
        print(f"[constants.py] Ошибка при загрузке ID администраторов: {e}")
        print("[constants.py] ВНИМАНИЕ: Установка ID администратора по умолчанию не выполнена.")
else:
    print("[constants.py] ВНИМАНИЕ: Переменная окружения ADMIN_ID не установлена.")

# Группы администраторов
ADMIN_GROUP_CREATOR = "creator"  # 👑 Создательница Moms Club
ADMIN_GROUP_DEVELOPER = "developer"  # 💻 Разработчик Moms Club
ADMIN_GROUP_CURATOR = "curator"  # 🎯 Куратор Moms Club

# Эмодзи для групп админов
ADMIN_GROUP_EMOJIS = {
    ADMIN_GROUP_CREATOR: "👑",
    ADMIN_GROUP_DEVELOPER: "💻",
    ADMIN_GROUP_CURATOR: "🎯",
}

# Названия групп админов
ADMIN_GROUP_NAMES = {
    ADMIN_GROUP_CREATOR: "Создательница Moms Club",
    ADMIN_GROUP_DEVELOPER: "Разработчик Moms Club",
    ADMIN_GROUP_CURATOR: "Куратор Moms Club",
}

# Убираем дублирующуюся строку, если она есть
# REFERRAL_BONUS_DAYS = 7 

# Флаг временного режима оплаты
TEMPORARY_PAYMENT_MODE = False

# Информация для временного режима оплаты
TEMPORARY_PAYMENT_ADMIN = "polinadmitrenkoo"  # Username администратора без @
TEMPORARY_PAYMENT_URL = "https://t.me/polinadmitrenkoo"  # Ссылка на профиль администратора

# Флаги технического обслуживания
MAINTENANCE_MODE = False  # Общий режим техобслуживания
DISABLE_PAYMENTS = False  # Отключение всех платежей

# Сообщение о техническом обслуживании
MAINTENANCE_MESSAGE = """💝 <b>Дорогие мамочки!</b>

Мы делаем Mom's Club еще лучше для вас! 

Сегодня ночью обновляем нашу платежную систему — она станет удобнее и надежнее 🌟

✨ <b>Завтра утром все заработает с новыми возможностями!</b>
🎁 И конечно, вас ждет приятный сюрприз за терпение

Мы любим вас! 💕
<b>Команда Mom's Club</b>""" 

# Настройки уведомлений о смене платежной системы
MIGRATION_NOTIFICATION_SETTINGS = {
    'enabled': True,  # Включить/выключить уведомления
    'notification_window_days': 3,  # За сколько дней до окончания подписки отправлять уведомление
    'check_interval_hours': 12,  # Интервал проверки в часах
    'max_notifications_per_user': 3,  # Максимум уведомлений одному пользователю
    'retry_schedule_days': [3, 2, 1],  # Через сколько дней повторные уведомления (0 = сразу, 2 дня, 1 день)
}

# Текст уведомления о смене платежной системы (возврат на ЮКасy)
MIGRATION_NOTIFICATION_TEXT = """🔄 <b>Важное обновление Mom's Club!</b>

Дорогие, красотки! 🫂

Мы вернулись на прежнюю платежную систему ЮКассу для вашего удобства и стабильности.

— прошлая система работала не корректно, что часто доставляло 😥 вам неудобства

🎁 мы так же добавляем вам бонус! За неудобство при переходе, к вашей подписке добавлены <b>3 подарочных дня!</b>

⚠️ <b>Что это значит для вас:</b>
• Ваша текущая подписка действует до <b>{end_date}</b>
• Автопродление временно приостановлено
• Для следующего продления нужно заново настроить оплату

🗒️ <b>Что нужно сделать:</b>
1. За день до окончания подписки вы получите напоминание
2. Нажмите "Настроить новую оплату" 
3. Оплатите через систему ЮКассы
4. Автопродление снова заработает!

Спасибо за понимание! 🤎

<i>Команда Mom's Club</i>"""

# ===== Константы для системы достижений (badges) =====

# Список всех допустимых типов badges
VALID_BADGE_TYPES = [
    # Автоматические badges
    'first_payment',
    'referral_1',
    'referral_5',
    'referral_10',
    'month_in_club',
    'half_year_in_club',
    'year_in_club',
    'loyal_customer',
    'platinum_customer',
    'active_member',
    'birthday_gift',
    # Специальные badges (только от админов)
    'community_helper',
    'inspiration',
    'early_supporter',
    'ambassador',
    'special_thanks',
    'milestone_celebrator',
    'supportive_friend',
    'creative_soul',
    'motivator',
    'heart_of_club',
    'creator_special',
    'moscow_first_meetup',
]

# Словарь названий badges для отображения (короткие названия)
BADGE_NAMES = {
    # Автоматические badges
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
    # Специальные badges (только от админов)
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
    'moscow_first_meetup': '🎉 Первая встреча в Москве',
}

# Словарь названий и описаний badges (для подробного отображения)
BADGE_NAMES_AND_DESCRIPTIONS = {
    # Автоматические badges
    'first_payment': ('💳 Первая оплата', 'Твоя первая оплата в Mom\'s Club'),
    'referral_1': ('🤝 Пригласила друга', 'Ты пригласила первого друга'),
    'referral_5': ('🌟 Пригласила 5 друзей', 'Ты пригласила 5 друзей'),
    'referral_10': ('✨ Пригласила 10 друзей', 'Ты пригласила 10 друзей!'),
    'month_in_club': ('📅 Месяц в клубе', 'Ты с нами уже месяц!'),
    'half_year_in_club': ('💫 Полгода в клубе', 'Ты с нами уже полгода!'),
    'year_in_club': ('🏆 Год в клубе', 'Ты с нами уже целый год!'),
    'loyal_customer': ('💎 Верный клиент', '5+ успешных платежей'),
    'platinum_customer': ('👑 Платиновый клиент', '10+ успешных платежей'),
    'active_member': ('🔥 Активный участник', 'Подписка продлевалась 3+ раза'),
    'birthday_gift': ('🎂 День рождения', 'Получен подарок на ДР'),
    # Специальные badges (только от админов)
    'community_helper': ('💝 Помощь сообществу', 'Особый вклад в развитие клуба'),
    'inspiration': ('✨ Источник вдохновения', 'Ты вдохновляешь других участниц'),
    'early_supporter': ('🌱 Первопроходец', 'Одна из первых участниц клуба'),
    'ambassador': ('🌟 Амбассадор клуба', 'Настоящий представитель Mom\'s Club'),
    'special_thanks': ('💖 Особая благодарность', 'Особая благодарность от команды'),
    'milestone_celebrator': ('🎉 Празднуем вместе', 'Особые моменты вместе с нами'),
    'supportive_friend': ('🤗 Поддерживающая подруга', 'Ты всегда поддерживаешь других'),
    'creative_soul': ('🎨 Творческая душа', 'Твои идеи вдохновляют'),
    'motivator': ('💪 Мотиватор', 'Ты мотивируешь других к действию'),
    'heart_of_club': ('💕 Сердце клуба', 'Ты — сердце нашего сообщества'),
    'creator_special': ('💋 Моя сучка от создателя Moms Club', 'Особое достижение от создателя'),
    'moscow_first_meetup': ('🎉 Первая встреча в Москве', 'Участница первой офлайн-встречи Mom\'s Club в Москве'),
}

# Списки badges по категориям
AUTOMATIC_BADGES = [
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

SPECIAL_BADGES = [
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
    ('moscow_first_meetup', '🎉 Первая встреча в Москве'),
]