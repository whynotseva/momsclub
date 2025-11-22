from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.config import Base

class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    referrer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # ID пользователя, который пригласил
    referral_code = Column(String(50), unique=True, nullable=True)  # Уникальный код для приглашения
    welcome_sent = Column(Boolean, default=False)  # Флаг, что приветственное сообщение отправлено
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    birthday = Column(Date, nullable=True)  # Дата рождения пользователя
    birthday_gift_year = Column(Integer, nullable=True)  # Год, в котором был выдан подарок на ДР
    yookassa_payment_method_id = Column(String(255), nullable=True)  # ID платежного метода для автоплатежей (ЮКасса)
    is_recurring_active = Column(Boolean, default=False)  # Флаг активности автопродления (по умолчанию выключено)
    phone = Column(String(32), nullable=True)  # Телефон пользователя
    email = Column(String(255), nullable=True)  # Email пользователя
    reminder_sent = Column(Boolean, default=False)  # Флаг, что напоминание об оплате было отправлено
    is_blocked = Column(Boolean, default=False)  # Флаг, что пользователь заблокировал бота
    is_first_payment_done = Column(Boolean, default=False)  # Флаг первой оплаты (для специальной цены)
    
    # Поля лояльности
    first_payment_date = Column(DateTime, nullable=True)  # Дата первой оплаты для подсчёта стажа
    current_loyalty_level = Column(String(20), default='none')  # 'none', 'silver', 'gold', 'platinum'
    one_time_discount_percent = Column(Integer, default=0)  # Разовая скидка 5% или 10%
    lifetime_discount_percent = Column(Integer, default=0)  # Пожизненная скидка 15%
    pending_loyalty_reward = Column(Boolean, default=False)  # Флаг ожидания выбора бонуса
    gift_due = Column(Boolean, default=False)  # Флаг подарка для Platinum
    
    # Поля защиты от злоупотребления промокодами возврата
    return_promo_count = Column(Integer, default=0)  # Сколько раз получал промокод возврата
    last_return_promo_date = Column(DateTime, nullable=True)  # Когда последний раз получал промокод возврата
    
    # Поле для группы администратора
    admin_group = Column(String(50), nullable=True)  # 'creator', 'developer', 'curator' или NULL для обычных пользователей
    
    # Реферальная система 2.0
    referral_balance = Column(Integer, default=0)  # Баланс реферальных средств в рублях
    total_referrals_paid = Column(Integer, default=0)  # Количество рефералов, оплативших подписку
    total_earned_referral = Column(Integer, default=0)  # Всего заработано реферальных средств за всё время
    
    # Отношение к подпискам
    subscriptions = relationship("Subscription", back_populates="user")
    
    # Связь для рефералов (кто кого пригласил)
    referrer = relationship("User", remote_side=[id], backref="referrals", foreign_keys=[referrer_id])
    
    def __repr__(self):
        return f"<User {self.telegram_id}>"


class Subscription(Base):
    """Модель подписки"""
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    start_date = Column(DateTime, server_default=func.now())
    end_date = Column(DateTime, nullable=False)
    price = Column(Integer, nullable=False)  # Цена в рублях
    is_active = Column(Boolean, default=True)
    payment_id = Column(String(255), nullable=True)  # Идентификатор платежа
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    next_retry_attempt_at = Column(DateTime, nullable=True)  # Дата и время следующей попытки автосписания (NULL если не запланировано)
    autopayment_fail_count = Column(Integer, default=0)      # Счетчик неудачных попыток автоплатежа
    renewal_price = Column(Integer, nullable=True)  # Цена для следующего автосписания (в рублях)
    renewal_duration_days = Column(Integer, nullable=True)  # Длительность следующего автопродления (в днях)
    subscription_id = Column(String(255), nullable=True)  # ID подписки в системе Prodamus
    
    # Поля лояльности (для аудита)
    loyalty_applied_level = Column(String(20), nullable=True)  # Уровень лояльности, применённый к этой подписке
    loyalty_discount_percent = Column(Integer, default=0)  # Процент скидки лояльности, применённый к этой подписке
    
    # Отношение к пользователю
    user = relationship("User", back_populates="subscriptions")
    
    def __repr__(self):
        return f"<Subscription {self.id} for user {self.user_id}>"


class PaymentLog(Base):
    """Модель логов платежей"""
    __tablename__ = "payment_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Integer, nullable=False)  # Сумма в рублях
    status = Column(String(50), nullable=False)  # success, pending, failed
    payment_method = Column(String(100), nullable=True)
    # ИСПРАВЛЕНО CRIT-001: transaction_id теперь unique и NOT NULL для идемпотентности
    transaction_id = Column(String(255), nullable=False, unique=True, index=True)
    prodamus_order_id = Column(String(255), nullable=True)  # ID заказа в системе Prodamus
    payment_label = Column(String(255), nullable=True)  # Метка платежа для идентификации
    details = Column(Text, nullable=True)  # Дополнительная информация о платеже
    days = Column(Integer, nullable=True) # Кол-во дней подписки, связанной с этим платежом
    created_at = Column(DateTime, server_default=func.now())
    is_confirmed = Column(Boolean, default=False)  # Флаг подтверждения платежа
    
    def __repr__(self):
        return f"<PaymentLog {self.id} for user {self.user_id}>"


class PromoCode(Base):
    """Модель промокодов"""
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    discount_type = Column(String(20), nullable=False, default='days')  # 'days', 'percent', etc.
    value = Column(Integer, nullable=False)  # Количество дней или процент
    max_uses = Column(Integer, nullable=True)  # Максимальное количество использований (None - безлимит)
    current_uses = Column(Integer, default=0)  # Текущее количество использований
    is_active = Column(Boolean, default=True)
    expiry_date = Column(DateTime, nullable=True)  # Дата истечения срока действия (None - бессрочный)
    created_at = Column(DateTime, server_default=func.now())
    
    # Поля для персональных промокодов
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Привязка к пользователю (NULL = общий промокод)
    is_personal = Column(Boolean, default=False)  # Флаг персонального промокода
    auto_generated = Column(Boolean, default=False)  # Флаг автоматической генерации

    # Связь с использовавшими пользователями
    used_by_users = relationship("UserPromoCode", back_populates="promo_code")
    user = relationship("User", foreign_keys=[user_id])  # Связь с пользователем для персональных промокодов

    def __repr__(self):
        return f"<PromoCode {self.code}>"


class UserPromoCode(Base):
    """Модель для отслеживания использования промокодов пользователями"""
    __tablename__ = "user_promo_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False)
    used_at = Column(DateTime, server_default=func.now())

    # Связи
    user = relationship("User")
    promo_code = relationship("PromoCode", back_populates="used_by_users")

    def __repr__(self):
        return f"<UserPromoCode user={self.user_id} code={self.promo_code_id}>"


class SubscriptionNotification(Base):
    """Модель для отслеживания отправленных уведомлений о подписках"""
    __tablename__ = "subscription_notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    notification_type = Column(String(50), nullable=False)  # 'expiration', 'payment_reminder', etc.
    sent_at = Column(DateTime, server_default=func.now())
    
    # Связь с подпиской
    subscription = relationship("Subscription")
    
    # Уникальность: одно уведомление одного типа для одной подписки
    __table_args__ = (
        UniqueConstraint('subscription_id', 'notification_type', name='uix_subscription_notification'),
    )
    
    def __repr__(self):
        return f"<SubscriptionNotification subscription_id={self.subscription_id} type={self.notification_type}>"


class MessageTemplate(Base):
    """Модель для хранения шаблонов сообщений"""
    __tablename__ = "message_templates"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)  # Название шаблона
    text = Column(Text, nullable=False)  # Текст шаблона
    format = Column(String(50), default="HTML")  # Формат (HTML, MarkdownV2, Plain)
    media_type = Column(String(50), nullable=True)  # Тип медиа (photo, video, videocircle или None)
    media_file_id = Column(String(255), nullable=True)  # ID медиафайла в Telegram
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Кто создал
    created_at = Column(DateTime, server_default=func.now())
    
    # Отношение к пользователю-создателю
    author = relationship("User", foreign_keys=[created_by])
    
    def __repr__(self):
        return f"<MessageTemplate {self.id}: {self.name}>"


class ScheduledMessage(Base):
    """Модель для хранения запланированных сообщений"""
    __tablename__ = "scheduled_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("message_templates.id", ondelete="CASCADE"), nullable=True)
    text = Column(Text, nullable=False)  # Текст сообщения
    format = Column(String(50), default="HTML")  # Формат (HTML, MarkdownV2, Plain)
    media_type = Column(String(50), nullable=True)  # Тип медиа
    media_file_id = Column(String(255), nullable=True)  # ID медиафайла
    scheduled_time = Column(DateTime, nullable=False)  # Время отправки
    is_sent = Column(Boolean, default=False)  # Флаг отправки
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Кто создал
    created_at = Column(DateTime, server_default=func.now())
    
    # Отношения
    template = relationship("MessageTemplate", foreign_keys=[template_id])
    author = relationship("User", foreign_keys=[created_by])
    
    def __repr__(self):
        return f"<ScheduledMessage {self.id}: {self.scheduled_time}>"


class ScheduledMessageRecipient(Base):
    """Модель для хранения получателей запланированных сообщений"""
    __tablename__ = "scheduled_message_recipients"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("scheduled_messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_sent = Column(Boolean, default=False)  # Флаг отправки конкретному пользователю
    sent_at = Column(DateTime, nullable=True)  # Время отправки
    error = Column(Text, nullable=True)  # Ошибка отправки, если есть
    
    # Отношения
    message = relationship("ScheduledMessage", backref="recipients")
    user = relationship("User")
    
    def __repr__(self):
        return f"<MessageRecipient {self.id}: message {self.message_id} to user {self.user_id}>"


class MigrationNotification(Base):
    """Модель для отслеживания уведомлений о смене платежной системы"""
    __tablename__ = "migration_notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_type = Column(String(50), nullable=False, default='payment_system_migration')
    is_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Отношение к пользователю
    user = relationship("User")
    
    def __repr__(self):
        return f"<MigrationNotification {self.id} for user {self.user_id}>"


class AutorenewalCancellationRequest(Base):
    """Модель заявок на отмену автопродления"""
    __tablename__ = "autorenewal_cancellation_requests"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False, default='pending')  # 'pending', 'approved', 'rejected', 'contacted'
    reason = Column(Text, nullable=True)  # Причина отмены (может заполнить служба заботы)
    created_at = Column(DateTime, server_default=func.now())
    contacted_at = Column(DateTime, nullable=True)  # Когда служба заботы связалась
    reviewed_at = Column(DateTime, nullable=True)  # Когда админ обработал
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # ID админа
    admin_notes = Column(Text, nullable=True)  # Заметки админа
    
    # Отношения
    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    
    def __repr__(self):
        return f"<AutorenewalCancellationRequest {self.id} for user {self.user_id} status={self.status}>"


class LoyaltyEvent(Base):
    """Модель событий лояльности"""
    __tablename__ = "loyalty_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(50), nullable=False)  # 'level_up', 'benefit_chosen', 'bonus_applied', 'reversed'
    level = Column(String(20), nullable=True)  # 'silver', 'gold', 'platinum'
    payload = Column(Text, nullable=True)  # JSON с дополнительными данными
    created_at = Column(DateTime, server_default=func.now())
    
    # Отношение к пользователю
    user = relationship("User")
    
    def __repr__(self):
        return f"<LoyaltyEvent {self.id} for user {self.user_id} kind={self.kind}>"


class UserBadge(Base):
    """Модель для достижений (badges) пользователей"""
    __tablename__ = "user_badges"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    badge_type = Column(String(50), nullable=False)  # 'first_payment', 'referral_1', 'referral_5', 'year_in_club'
    earned_at = Column(DateTime, server_default=func.now())  # Когда получен badge
    
    # Отношение к пользователю
    user = relationship("User")
    
    # Уникальность: один badge одного типа для одного пользователя
    __table_args__ = (
        UniqueConstraint('user_id', 'badge_type', name='uix_user_badge'),
    )
    
    def __repr__(self):
        return f"<UserBadge {self.badge_type} for user {self.user_id}>"


class GroupActivity(Base):
    """Модель для отслеживания активности пользователей в группе"""
    __tablename__ = "group_activity"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    message_count = Column(Integer, default=0)  # Количество сообщений в группе
    last_activity = Column(DateTime, nullable=True)  # Дата и время последнего сообщения
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Отношение к пользователю
    user = relationship("User")
    
    def __repr__(self):
        return f"<GroupActivity user_id={self.user_id} messages={self.message_count}>"


class GroupActivityLog(Base):
    """Модель для детального логирования активности пользователей в группе по дням"""
    __tablename__ = "group_activity_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)  # Дата (без времени)
    message_count = Column(Integer, default=0)  # Количество сообщений за этот день
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Уникальность: один пользователь - одна запись на день
    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='unique_user_date'),
    )
    
    # Отношение к пользователю
    user = relationship("User")
    
    def __repr__(self):
        return f"<GroupActivityLog user_id={self.user_id} date={self.date} messages={self.message_count}>"


class FavoriteUser(Base):
    """Модель для избранных пользователей админа"""
    __tablename__ = "favorite_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_telegram_id = Column(Integer, nullable=False)  # Telegram ID админа, который добавил в избранное
    user_telegram_id = Column(Integer, nullable=False)  # Telegram ID пользователя, которого добавили
    note = Column(Text, nullable=True)  # Заметка админа о пользователе
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Уникальность: один админ не может добавить одного пользователя дважды
    __table_args__ = (
        UniqueConstraint('admin_telegram_id', 'user_telegram_id', name='unique_admin_favorite_user'),
    )
    
    def __repr__(self):
        return f"<FavoriteUser admin={self.admin_telegram_id} user={self.user_telegram_id}>"


class ReferralReward(Base):
    """Модель истории реферальных наград"""
    __tablename__ = "referral_rewards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # Кто получил награду
    referee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # Кто оплатил (приглашенный)
    payment_id = Column(Integer, ForeignKey("payment_logs.id", ondelete="SET NULL"), nullable=True)  # За какой платеж (НОВОЕ!)
    payment_amount = Column(Integer, nullable=False)  # Сумма покупки реферала в рублях
    reward_type = Column(String(20), nullable=False)  # 'money' или 'days'
    reward_amount = Column(Integer, nullable=False)  # Количество рублей или дней
    loyalty_level = Column(String(20), nullable=True)  # Уровень лояльности на момент выбора
    bonus_percent = Column(Integer, nullable=False)  # Процент бонуса на момент выбора
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_id], backref="rewards_given")
    referee = relationship("User", foreign_keys=[referee_id], backref="rewards_received")
    payment = relationship("PaymentLog", foreign_keys=[payment_id])
    
    def __repr__(self):
        return f"<ReferralReward {self.id} for referrer {self.referrer_id}>"


class WithdrawalRequest(Base):
    """Модель заявок на вывод реферальных средств"""
    __tablename__ = "withdrawal_requests"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)  # Сумма вывода в рублях
    payment_method = Column(String(50), nullable=False)  # 'card' или 'sbp'
    payment_details = Column(String(255), nullable=False)  # Номер карты или телефона
    status = Column(String(20), default='pending')  # 'pending', 'approved', 'rejected', 'completed'
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)  # Когда обработана
    processed_by_admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Кто обработал
    admin_comment = Column(Text, nullable=True)  # Комментарий админа
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="withdrawal_requests")
    processed_by = relationship("User", foreign_keys=[processed_by_admin_id])
    
    def __repr__(self):
        return f"<WithdrawalRequest {self.id} user={self.user_id} amount={self.amount}>"


class AdminBalanceAdjustment(Base):
    """Модель ручных начислений/списаний баланса админом"""
    __tablename__ = "admin_balance_adjustments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Кто сделал
    amount = Column(Integer, nullable=False)  # Сумма (положительная для начисления, отрицательная для списания)
    comment = Column(Text, nullable=True)  # Комментарий админа
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="balance_adjustments")
    admin = relationship("User", foreign_keys=[admin_id])
    
    def __repr__(self):
        return f"<AdminBalanceAdjustment {self.id} user={self.user_id} amount={self.amount}>"