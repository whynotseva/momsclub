#!/bin/bash
# Скрипт для выполнения на сервере через SSH

set -e

cd /root/home/momsclub || exit 1

BACKUP_DATE=$(date +%d%m%Y)
BACKUP_DIR="momsclub${BACKUP_DATE}"
BACKUP_PATH="/root/home/${BACKUP_DIR}"

echo "========================================="
echo "ШАГ 1: СОЗДАНИЕ БЭКАПА"
echo "========================================="
echo ""

# Проверка существования бэкапа
if [ -d "$BACKUP_PATH" ]; then
    echo "⚠ Бэкап $BACKUP_PATH уже существует"
    read -p "Продолжить? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        exit 0
    fi
fi

# Создание бэкапа
mkdir -p "$BACKUP_PATH"
echo "✓ Создана директория $BACKUP_PATH"

# Остановка сервиса
if systemctl is-active --quiet momsclub 2>/dev/null || systemctl is-active --quiet momsclub_bot 2>/dev/null; then
    echo "Остановка бота..."
    systemctl stop momsclub 2>/dev/null || systemctl stop momsclub_bot 2>/dev/null || true
    sleep 2
    echo "✓ Бот остановлен"
fi

# Копирование
echo "Копирование файлов..."
rsync -av \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='.git' \
    --exclude='.env' \
    /root/home/momsclub/ "$BACKUP_PATH/" > /dev/null 2>&1

# Сохранение критичных файлов
if [ -f "/root/home/momsclub/.env" ]; then
    cp /root/home/momsclub/.env "$BACKUP_PATH/.env.backup"
fi

if [ -f "/root/home/momsclub/momsclub.db" ]; then
    cp /root/home/momsclub/momsclub.db "$BACKUP_PATH/momsclub.db"
    echo "✓ База данных сохранена"
fi

echo "✓ Бэкап создан: $BACKUP_PATH"
echo ""

echo "========================================="
echo "ШАГ 2: ПРОВЕРКА НОВЫХ ФАЙЛОВ"
echo "========================================="
echo ""

# Проверка наличия новых файлов
MISSING=0
if [ ! -f "loyalty/levels.py" ]; then
    echo "⚠ Файл loyalty/levels.py не найден"
    MISSING=1
fi
if [ ! -f "database/migrations/add_loyalty_fields.py" ]; then
    echo "⚠ Файл database/migrations/add_loyalty_fields.py не найден"
    MISSING=1
fi

if [ $MISSING -eq 1 ]; then
    echo ""
    echo "❌ Не все файлы найдены!"
    echo "Загрузите новые файлы на сервер в /root/home/momsclub/"
    echo "После загрузки запустите скрипт снова"
    exit 1
fi

echo "✓ Все необходимые файлы найдены"
echo ""

echo "========================================="
echo "ШАГ 3: ВЫПОЛНЕНИЕ МИГРАЦИИ"
echo "========================================="
echo "⚠ КРИТИЧНО: Это изменит базу данных!"
echo ""
read -p "Выполнить миграцию? (yes/no): " confirm_migrate

if [ "$confirm_migrate" != "yes" ]; then
    echo "Миграция отменена"
    exit 0
fi

cd /root/home/momsclub

# Обновление зависимостей
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "Обновление зависимостей..."
    pip install -r requirements.txt --quiet --upgrade 2>&1 | grep -v "already satisfied" || true
fi

# Миграция
echo "Выполнение миграции..."
python3 database/migrations/add_loyalty_fields.py

if [ $? -eq 0 ]; then
    echo "✓ Миграция выполнена успешно"
else
    echo "❌ Ошибка миграции!"
    exit 1
fi

echo ""

echo "========================================="
echo "ШАГ 4: ЗАПУСК СЕРВИСА"
echo "========================================="

if systemctl start momsclub 2>/dev/null; then
    echo "✓ Сервис momsclub запущен"
elif systemctl start momsclub_bot 2>/dev/null; then
    echo "✓ Сервис momsclub_bot запущен"
else
    echo "⚠ Не удалось запустить сервис автоматически"
fi

sleep 3

# Проверка
if systemctl is-active --quiet momsclub 2>/dev/null || systemctl is-active --quiet momsclub_bot 2>/dev/null; then
    echo "✓ Сервис работает"
else
    echo "⚠ Сервис не запустился, проверьте: systemctl status momsclub"
fi

echo ""
echo "========================================="
echo "ДЕПЛОЙ ЗАВЕРШЕН"
echo "========================================="
echo ""
echo "Бэкап: $BACKUP_PATH"
echo "Для отката: cd /root/home/momsclub/deploy && ./rollback.sh $BACKUP_DATE"

