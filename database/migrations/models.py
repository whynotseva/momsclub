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
    price = Column(Integer, nullable=False)  # Цена в копейках
    is_active = Column(Boolean, default=True)
    payment_id = Column(String(255), nullable=True)  # Идентификатор платежа
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    next_retry_attempt_at = Column(DateTime, nullable=True)  # Дата и время следующей попытки автосписания (NULL если не запланировано)
    autopayment_fail_count = Column(Integer, default=0)      # Счетчик неудачных попыток автоплатежа
    renewal_price = Column(Integer, nullable=True)  # Цена для следующего автосписания (в копейках)
    renewal_duration_days = Column(Integer, nullable=True)  # Длительность следующего автопродления (в днях)
    subscription_id = Column(String(255), nullable=True)  # ID подписки в системе Prodamus
    
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
    amount = Column(Integer, nullable=False)  # Сумма в копейках
    status = Column(String(50), nullable=False)  # success, pending, failed
    payment_method = Column(String(100), nullable=True)
    transaction_id = Column(String(255), nullable=True)
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

    # Связь с использовавшими пользователями
    used_by_users = relationship("UserPromoCode", back_populates="promo_code")

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