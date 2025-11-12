#!/bin/bash
#
# Скрипт отката на предыдущую версию
# Использование: ./rollback.sh [дата_бэкапа]
# Пример: ./rollback.sh 04112025

set -e  # Прекратить выполнение при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Параметры
BACKUP_DATE="${1}"
if [ -z "$BACKUP_DATE" ]; then
    echo -e "${RED}Ошибка: не указана дата бэкапа${NC}"
    echo "Использование: ./rollback.sh [дата_бэкапа]"
    echo "Пример: ./rollback.sh 04112025"
    exit 1
fi

BACKUP_DIR="momsclub${BACKUP_DATE}"
CURRENT_DIR="/root/home/momsclub"
BACKUP_PATH="/root/home/${BACKUP_DIR}"
SERVICE_NAME="momsclub"

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}ОТКАТ НА ПРЕДЫДУЩУЮ ВЕРСИЮ${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Проверка, что скрипт запущен от root или с sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Ошибка: скрипт должен быть запущен от root или с sudo${NC}"
    exit 1
fi

# Проверка существования бэкапа
if [ ! -d "$BACKUP_PATH" ]; then
    echo -e "${RED}Ошибка: бэкап $BACKUP_PATH не найден${NC}"
    exit 1
fi

echo -e "${RED}ВНИМАНИЕ: Вы собираетесь откатить систему на версию от $BACKUP_DATE${NC}"
echo "Текущая версия будет сохранена как momsclub_current_$(date +%Y%m%d_%H%M%S)"
echo ""
read -p "Продолжить? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Откат отменен"
    exit 0
fi

echo ""

echo -e "${YELLOW}Шаг 1: Создание бэкапа текущей версии перед откатом${NC}"
CURRENT_BACKUP="momsclub_current_$(date +%Y%m%d_%H%M%S)"
CURRENT_BACKUP_PATH="/root/home/${CURRENT_BACKUP}"

mkdir -p "$CURRENT_BACKUP_PATH"
echo "Сохраняю текущую версию в: $CURRENT_BACKUP_PATH"

# Быстрое копирование критичных файлов
rsync -av \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='.git' \
    "$CURRENT_DIR/" "$CURRENT_BACKUP_PATH/"

if [ -f "$CURRENT_DIR/momsclub.db" ]; then
    cp "$CURRENT_DIR/momsclub.db" "$CURRENT_BACKUP_PATH/momsclub.db"
fi

echo -e "${GREEN}✓ Текущая версия сохранена${NC}"
echo ""

echo -e "${YELLOW}Шаг 2: Остановка текущего сервиса${NC}"
if systemctl is-active --quiet $SERVICE_NAME; then
    systemctl stop $SERVICE_NAME
    echo "✓ Сервис $SERVICE_NAME остановлен"
fi

if systemctl is-active --quiet "${SERVICE_NAME}_bot"; then
    systemctl stop "${SERVICE_NAME}_bot"
    echo "✓ Сервис ${SERVICE_NAME}_bot остановлен"
fi

echo ""

echo -e "${YELLOW}Шаг 3: Восстановление из бэкапа${NC}"

# Удаление текущих файлов (кроме критичных)
echo "Очистка текущей директории..."
find "$CURRENT_DIR" -type f -name "*.py" -delete
find "$CURRENT_DIR" -type f -name "*.txt" -delete
find "$CURRENT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Восстановление из бэкапа
echo "Восстановление файлов из бэкапа..."
rsync -av \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='.git' \
    "$BACKUP_PATH/" "$CURRENT_DIR/"

# Восстановление .env если есть бэкап
if [ -f "$BACKUP_PATH/.env.backup" ]; then
    cp "$BACKUP_PATH/.env.backup" "$CURRENT_DIR/.env"
    echo "✓ Восстановлен .env файл"
fi

# Восстановление базы данных (ОПЦИОНАЛЬНО - будьте осторожны!)
echo ""
read -p "Восстановить базу данных из бэкапа? Это перезапишет текущую БД! (yes/no): " restore_db

if [ "$restore_db" == "yes" ]; then
    if [ -f "$BACKUP_PATH/momsclub.db" ]; then
        cp "$BACKUP_PATH/momsclub.db" "$CURRENT_DIR/momsclub.db"
        echo -e "${GREEN}✓ База данных восстановлена${NC}"
    else
        echo -e "${YELLOW}⚠ База данных в бэкапе не найдена${NC}"
    fi
else
    echo "База данных не восстановлена (используется текущая)"
fi

echo ""

echo -e "${YELLOW}Шаг 4: Запуск сервиса${NC}"
if systemctl start $SERVICE_NAME; then
    echo -e "${GREEN}✓ Сервис $SERVICE_NAME запущен${NC}"
else
    echo -e "${YELLOW}⚠ Не удалось запустить $SERVICE_NAME, пробую альтернативное имя...${NC}"
    if systemctl start "${SERVICE_NAME}_bot"; then
        echo -e "${GREEN}✓ Сервис ${SERVICE_NAME}_bot запущен${NC}"
    else
        echo -e "${RED}Ошибка: не удалось запустить сервис${NC}"
        echo "Проверьте статус: systemctl status $SERVICE_NAME"
    fi
fi

echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}ОТКАТ ЗАВЕРШЕН${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Восстановлено из: $BACKUP_PATH"
echo "Текущая версия сохранена в: $CURRENT_BACKUP_PATH"
echo ""
echo "Проверьте статус: systemctl status $SERVICE_NAME"
echo "Проверьте логи: journalctl -u $SERVICE_NAME -f"

