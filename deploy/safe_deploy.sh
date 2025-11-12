#!/bin/bash
#
# Скрипт безопасного деплоя системы лояльности
# Создает бэкап текущей версии перед развертыванием новой
#
# Использование: ./safe_deploy.sh [дата_бэкапа]
# Пример: ./safe_deploy.sh 04112025

set -e  # Прекратить выполнение при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Параметры
BACKUP_DATE="${1:-$(date +%d%m%Y)}"
BACKUP_DIR="momsclub${BACKUP_DATE}"
CURRENT_DIR="/root/home/momsclub"
BACKUP_PATH="/root/home/${BACKUP_DIR}"
SERVICE_NAME="momsclub"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Безопасный деплой системы лояльности${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Проверка, что скрипт запущен от root или с sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Ошибка: скрипт должен быть запущен от root или с sudo${NC}"
    exit 1
fi

# Проверка существования текущей директории
if [ ! -d "$CURRENT_DIR" ]; then
    echo -e "${RED}Ошибка: директория $CURRENT_DIR не найдена${NC}"
    exit 1
fi

echo -e "${YELLOW}Шаг 1: Создание бэкапа текущей версии${NC}"
echo "Бэкап будет создан в: $BACKUP_PATH"

# Проверка, существует ли уже бэкап с таким именем
if [ -d "$BACKUP_PATH" ]; then
    echo -e "${RED}Ошибка: директория $BACKUP_PATH уже существует${NC}"
    echo "Используйте другую дату или удалите старый бэкап"
    exit 1
fi

# Создание директории бэкапа
mkdir -p "$BACKUP_PATH"
echo "✓ Создана директория $BACKUP_PATH"

# Копирование файлов (исключаем виртуальное окружение, логи, кэш)
echo "Копирование файлов проекта..."
rsync -av \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='*.db.backup*' \
    --exclude='.git' \
    --exclude='.env' \
    "$CURRENT_DIR/" "$BACKUP_PATH/"

# Сохранение .env отдельно (если существует)
if [ -f "$CURRENT_DIR/.env" ]; then
    cp "$CURRENT_DIR/.env" "$BACKUP_PATH/.env.backup"
    echo "✓ Сохранен .env файл"
fi

# Сохранение базы данных
if [ -f "$CURRENT_DIR/momsclub.db" ]; then
    cp "$CURRENT_DIR/momsclub.db" "$BACKUP_PATH/momsclub.db"
    echo "✓ Скопирована база данных momsclub.db"
fi

echo -e "${GREEN}✓ Бэкап создан успешно${NC}"
echo ""

echo -e "${YELLOW}Шаг 2: Остановка текущего сервиса${NC}"
if systemctl is-active --quiet $SERVICE_NAME; then
    systemctl stop $SERVICE_NAME
    echo "✓ Сервис $SERVICE_NAME остановлен"
else
    echo "⚠ Сервис $SERVICE_NAME не запущен"
fi

# Также проверяем альтернативное имя сервиса
if systemctl is-active --quiet "${SERVICE_NAME}_bot"; then
    systemctl stop "${SERVICE_NAME}_bot"
    echo "✓ Сервис ${SERVICE_NAME}_bot остановлен"
fi

echo ""

echo -e "${YELLOW}Шаг 3: Проверка статуса сервисов${NC}"
if systemctl is-active --quiet $SERVICE_NAME || systemctl is-active --quiet "${SERVICE_NAME}_bot"; then
    echo -e "${RED}Ошибка: сервисы все еще запущены${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Все сервисы остановлены${NC}"
echo ""

echo -e "${YELLOW}Шаг 4: Информация для продолжения${NC}"
echo "────────────────────────────────────────────"
echo "Бэкап создан: $BACKUP_PATH"
echo "Текущая директория: $CURRENT_DIR"
echo ""
echo "Следующие шаги:"
echo "1. Загрузите новую версию кода в $CURRENT_DIR"
echo "2. Обновите зависимости (если нужно): pip install -r requirements.txt"
echo "3. Запустите миграцию: python database/migrations/add_loyalty_fields.py"
echo "4. Перезапустите сервис: systemctl start $SERVICE_NAME"
echo ""
echo "Для отката используйте: ./rollback.sh $BACKUP_DATE"
echo "────────────────────────────────────────────"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Бэкап готов. Можно загружать новую версию${NC}"
echo -e "${GREEN}========================================${NC}"

