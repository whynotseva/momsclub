"""
Константы для работы с подписками Prodamus
"""

# Конфигурация тарифных планов подписок в системе Prodamus
# ВАЖНО: 'id' здесь - это ID тарифного плана, НЕ уникальный ID подписки пользователя!
# Уникальный ID подписки конкретного пользователя - это 'profile_id' в webhook'ах
PRODAMUS_SUBSCRIPTIONS = {
    30: {
        'id': '2478298',  # ID тарифного плана "30 дней" (одинаков для всех пользователей)
        'name': 'Предоставление доступа к Moms Club на 30 дней',
        'amount': 990,
        'description': 'Месячная подписка Mom\'s Club'
    },
    60: {
        'id': '2474084',  # ID тарифного плана "60 дней" (одинаков для всех пользователей)
        'name': 'Предоставление доступа к Moms Club на 60 дней',
        'amount': 1790,
        'description': 'Подписка Mom\'s Club на 2 месяца'
    },
    90: {
        'id': '2474086',  # ID тарифного плана "90 дней" (одинаков для всех пользователей)
        'name': 'Предоставление доступа к Moms Club на 90 дней', 
        'amount': 2490,
        'description': 'Подписка Mom\'s Club на 3 месяца'
    }
}

# Реверсивный маппинг: ID тарифного плана -> информация о подписке
SUBSCRIPTION_TARIFF_ID_TO_INFO = {
    '2478298': {'days': 30, 'amount': 990},
    '2474084': {'days': 60, 'amount': 1790},
    '2474086': {'days': 90, 'amount': 2490}
}

def get_subscription_info_by_tariff_id(tariff_id: str) -> dict:
    """
    Возвращает информацию о подписке по ID тарифного плана.
    
    Args:
        tariff_id: ID тарифного плана в Prodamus (например, '2478298')
        
    Returns:
        dict: Информация о подписке (days, amount)
    """
    return SUBSCRIPTION_TARIFF_ID_TO_INFO.get(tariff_id, {'days': 30, 'amount': 990})

def get_subscription_info_by_id(subscription_id: str) -> dict:
    """
    УСТАРЕВШАЯ функция для обратной совместимости.
    Используйте get_subscription_info_by_tariff_id() для ясности.
    
    Args:
        subscription_id: ID тарифного плана в Prodamus
        
    Returns:
        dict: Информация о подписке (days, amount)
    """
    return get_subscription_info_by_tariff_id(subscription_id)

def get_tariff_id_by_days(days: int) -> str:
    """
    Возвращает ID тарифного плана по количеству дней.
    
    Args:
        days: Количество дней подписки
        
    Returns:
        str: ID тарифного плана в Prodamus
    """
    subscription = PRODAMUS_SUBSCRIPTIONS.get(days)
    if subscription:
        return subscription['id']
    return PRODAMUS_SUBSCRIPTIONS[30]['id']  # По умолчанию 30 дней

def get_subscription_id_by_days(days: int) -> str:
    """
    УСТАРЕВШАЯ функция для обратной совместимости.
    Используйте get_tariff_id_by_days() для ясности.
    
    Args:
        days: Количество дней подписки
        
    Returns:
        str: ID тарифного плана в Prodamus
    """
    return get_tariff_id_by_days(days)

def get_subscription_amount_by_days(days: int) -> int:
    """
    Возвращает стоимость подписки по количеству дней.
    
    Args:
        days: Количество дней подписки
        
    Returns:
        int: Стоимость в рублях
    """
    subscription = PRODAMUS_SUBSCRIPTIONS.get(days)
    if subscription:
        return subscription['amount']
    return PRODAMUS_SUBSCRIPTIONS[30]['amount']  # По умолчанию 30 дней

def get_all_subscription_plans() -> dict:
    """
    Возвращает все доступные планы подписок.
    
    Returns:
        dict: Все планы подписок
    """
    return PRODAMUS_SUBSCRIPTIONS.copy()

# ================================================================================
# ВАЖНОЕ РАЗЪЯСНЕНИЕ ПО ТЕРМИНОЛОГИИ:
# ================================================================================
# 
# В системе Prodamus есть два разных понятия:
# 
# 1. ТАРИФНЫЙ ПЛАН (Subscription Plan/Product):
#    - ID: '2478298', '2474084', '2474086' 
#    - Это шаблон подписки (30 дней за 990₽, 60 дней за 1790₽ и т.д.)
#    - ОДИНАКОВ для всех пользователей, выбравших этот план
#    - Передается в webhook'ах как subscription[id]
# 
# 2. ПОДПИСКА ПОЛЬЗОВАТЕЛЯ (User Subscription Instance):
#    - ID: уникальное число для каждого пользователя (profile_id)
#    - Это конкретная подписка конкретного пользователя  
#    - УНИКАЛЕН для каждого пользователя
#    - Передается в webhook'ах как subscription[profile_id]
# 
# ПРАВИЛЬНО: сохранять profile_id как subscription_id в нашей БД
# ================================================================================
