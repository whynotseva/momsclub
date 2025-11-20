#!/bin/bash

# Скрипт деплоя системы возврата пользователей с персональными промокодами
# Дата: 16.11.2025

set -e  # Остановка при ошибке

SERVICE_NAME="telegram-bot"
PROJECT_DIR="/root/home/momsclub"
BACKUP_DIR="${PROJECT_DIR}/backups"
MIGRATION_FILE="database/migrations/add_personal_promo_fields.py"
DB_PATH="${PROJECT_DIR}/momsclub.db"

echo "🚀 Начало деплоя системы возврата пользователей..."

# 1. Создаем бэкап БД
echo "📦 Создание бэкапа БД..."
BACKUP_FILE="${BACKUP_DIR}/db_before_return_promo_$(date +%Y%m%d_%H%M%S).db"
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "$BACKUP_FILE"
    echo "✅ Бэкап создан: $BACKUP_FILE"
else
    echo "⚠️  База данных не найдена: $DB_PATH"
fi

# 2. Применяем миграцию
echo "🔧 Применение миграции БД..."
cd "$PROJECT_DIR"
if [ -f "$MIGRATION_FILE" ]; then
    python3 "$MIGRATION_FILE"
    echo "✅ Миграция применена"
else
    echo "❌ Файл миграции не найден: $MIGRATION_FILE"
    exit 1
fi

# 3. Проверяем, что миграция прошла успешно
echo "🔍 Проверка миграции..."
python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(promo_codes)')
columns = [col[1] for col in cursor.fetchall()]
required = ['user_id', 'is_personal', 'auto_generated']
missing = [col for col in required if col not in columns]
if missing:
    print(f'❌ Отсутствуют поля: {missing}')
    exit(1)
else:
    print('✅ Все поля добавлены успешно')
conn.close()
"

if [ $? -ne 0 ]; then
    echo "❌ Ошибка проверки миграции"
    exit 1
fi

# 4. Останавливаем сервис
echo "⏸️  Остановка сервиса $SERVICE_NAME..."
systemctl stop "$SERVICE_NAME" || echo "⚠️  Сервис уже остановлен"

# 5. Ждем немного
sleep 2

# 6. Проверяем статус
echo "📊 Статус сервиса:"
systemctl status "$SERVICE_NAME" --no-pager | head -5 || echo "Сервис остановлен"

# 7. Запускаем сервис
echo "▶️  Запуск сервиса $SERVICE_NAME..."
systemctl start "$SERVICE_NAME"
sleep 3

# 8. Проверяем, что сервис запустился
echo "📊 Финальный статус сервиса:"
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ Сервис $SERVICE_NAME успешно запущен"
    systemctl status "$SERVICE_NAME" --no-pager | head -10
else
    echo "❌ Ошибка запуска сервиса $SERVICE_NAME"
    echo "Последние логи:"
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
fi

echo ""
echo "✅ Деплой завершен успешно!"
echo "📝 Применена миграция: add_personal_promo_fields"
echo "🔄 Сервис перезапущен"

