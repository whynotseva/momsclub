#!/bin/bash
#
# Полный скрипт деплоя системы лояльности
# Выполняет все шаги автоматически с подтверждениями
#
# Использование на сервере:
# cd /root/home/momsclub
# chmod +x deploy/full_deploy.sh
# sudo ./deploy/full_deploy.sh

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

BACKUP_DATE=$(date +%d%m%Y)
BACKUP_DIR="momsclub${BACKUP_DATE}"
CURRENT_DIR="/root/home/momsclub"
BACKUP_PATH="/root/home/${BACKUP_DIR}"
SERVICE_NAME="momsclub"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ПОЛНЫЙ ДЕПЛОЙ СИСТЕМЫ ЛОЯЛЬНОСТИ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Проверка root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Ошибка: запустите с sudo${NC}"
    exit 1
fi

cd "$CURRENT_DIR"

# Шаг 1: Проверка текущего состояния
echo -e "${YELLOW}Шаг 1: Проверка текущего состояния${NC}"
echo "────────────────────────────────────────────"

if [ ! -d "$CURRENT_DIR" ]; then
    echo -e "${RED}Ошибка: директория $CURRENT_DIR не найдена${NC}"
    exit 1
fi

echo "✓ Директория найдена: $CURRENT_DIR"

# Проверка статуса сервиса
if systemctl is-active --quiet $SERVICE_NAME 2>/dev/null || systemctl is-active --quiet "${SERVICE_NAME}_bot" 2>/dev/null; then
    echo "✓ Сервис работает"
    SERVICE_IS_RUNNING=true
else
    echo "⚠ Сервис не запущен"
    SERVICE_IS_RUNNING=false
fi

echo ""

# Шаг 2: Создание бэкапа
echo -e "${YELLOW}Шаг 2: Создание бэкапа текущей версии${NC}"
echo "────────────────────────────────────────────"
echo "Бэкап будет создан в: $BACKUP_PATH"
echo ""
read -p "Продолжить? (yes/no): " confirm1

if [ "$confirm1" != "yes" ]; then
    echo "Отменено"
    exit 0
fi

# Проверка существования бэкапа
if [ -d "$BACKUP_PATH" ]; then
    echo -e "${RED}Ошибка: директория $BACKUP_PATH уже существует${NC}"
    exit 1
fi

mkdir -p "$BACKUP_PATH"
echo "✓ Создана директория $BACKUP_PATH"

# Остановка сервиса
if [ "$SERVICE_IS_RUNNING" = true ]; then
    echo "Остановка сервиса..."
    systemctl stop $SERVICE_NAME 2>/dev/null || systemctl stop "${SERVICE_NAME}_bot" 2>/dev/null || true
    sleep 2
    echo "✓ Сервис остановлен"
fi

# Копирование файлов
echo "Копирование файлов проекта..."
rsync -av \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='.git' \
    --exclude='.env' \
    "$CURRENT_DIR/" "$BACKUP_PATH/" > /dev/null 2>&1

# Сохранение .env и БД
if [ -f "$CURRENT_DIR/.env" ]; then
    cp "$CURRENT_DIR/.env" "$BACKUP_PATH/.env.backup"
fi

if [ -f "$CURRENT_DIR/momsclub.db" ]; then
    cp "$CURRENT_DIR/momsclub.db" "$BACKUP_PATH/momsclub.db"
    echo "✓ База данных сохранена"
fi

echo -e "${GREEN}✓ Бэкап создан успешно${NC}"
echo ""

# Шаг 3: Проверка наличия новых файлов
echo -e "${YELLOW}Шаг 3: Проверка новых файлов${NC}"
echo "────────────────────────────────────────────"

# Проверяем наличие новых файлов лояльности
MISSING_FILES=()
REQUIRED_FILES=(
    "loyalty/levels.py"
    "loyalty/benefits.py"
    "loyalty/service.py"
    "database/migrations/add_loyalty_fields.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$CURRENT_DIR/$file" ]; then
        MISSING_FILES+=("$file")
    fi
done

if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    echo -e "${RED}Ошибка: не найдены следующие файлы:${NC}"
    for file in "${MISSING_FILES[@]}"; do
        echo "  - $file"
    done
    echo ""
    echo "Загрузите новые файлы на сервер в директорию $CURRENT_DIR"
    echo "Или запустите этот скрипт после загрузки файлов"
    exit 1
fi

echo -e "${GREEN}✓ Все необходимые файлы найдены${NC}"
echo ""

# Шаг 4: Обновление зависимостей
echo -e "${YELLOW}Шаг 4: Обновление зависимостей${NC}"
echo "────────────────────────────────────────────"

if [ -f "requirements.txt" ] && [ -d "venv" ]; then
    echo "Обновление зависимостей..."
    source venv/bin/activate
    pip install -r requirements.txt --quiet --upgrade 2>&1 | grep -v "already satisfied" || true
    echo -e "${GREEN}✓ Зависимости обновлены${NC}"
else
    echo "⚠ venv не найден, пропускаю обновление зависимостей"
fi

echo ""

# Шаг 5: Проверка синтаксиса
echo -e "${YELLOW}Шаг 5: Проверка синтаксиса Python${NC}"
echo "────────────────────────────────────────────"

if command -v python3 &> /dev/null; then
    echo "Проверка основных файлов..."
    python3 -m py_compile bot.py handlers/*.py loyalty/*.py 2>&1 | head -10 || {
        echo -e "${RED}Ошибка: найдены синтаксические ошибки${NC}"
        exit 1
    }
    echo -e "${GREEN}✓ Синтаксис корректен${NC}"
else
    echo "⚠ python3 не найден, пропускаю проверку синтаксиса"
fi

echo ""

# Шаг 6: Миграция базы данных
echo -e "${YELLOW}Шаг 6: Выполнение миграции базы данных${NC}"
echo "────────────────────────────────────────────"
echo -e "${RED}ВНИМАНИЕ: Это изменит структуру базы данных!${NC}"
echo ""
read -p "Выполнить миграцию? (yes/no): " confirm2

if [ "$confirm2" != "yes" ]; then
    echo "Миграция отменена"
    exit 0
fi

if [ -f "database/migrations/add_loyalty_fields.py" ]; then
    echo "Запуск миграции..."
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    python3 database/migrations/add_loyalty_fields.py
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Миграция выполнена успешно${NC}"
    else
        echo -e "${RED}Ошибка при выполнении миграции!${NC}"
        echo "Для отката используйте: ./deploy/rollback.sh $BACKUP_DATE"
        exit 1
    fi
else
    echo -e "${RED}Ошибка: файл миграции не найден${NC}"
    exit 1
fi

echo ""

# Шаг 7: Запуск сервиса
echo -e "${YELLOW}Шаг 7: Запуск сервиса${NC}"
echo "────────────────────────────────────────────"

if systemctl start $SERVICE_NAME 2>/dev/null; then
    echo -e "${GREEN}✓ Сервис $SERVICE_NAME запущен${NC}"
elif systemctl start "${SERVICE_NAME}_bot" 2>/dev/null; then
    echo -e "${GREEN}✓ Сервис ${SERVICE_NAME}_bot запущен${NC}"
else
    echo -e "${RED}Ошибка: не удалось запустить сервис${NC}"
    echo "Проверьте конфигурацию: systemctl status $SERVICE_NAME"
    exit 1
fi

# Проверка статуса
sleep 3
if systemctl is-active --quiet $SERVICE_NAME 2>/dev/null || systemctl is-active --quiet "${SERVICE_NAME}_bot" 2>/dev/null; then
    echo -e "${GREEN}✓ Сервис работает${NC}"
else
    echo -e "${YELLOW}⚠ Сервис не запустился, проверьте логи${NC}"
fi

echo ""

# Финальный отчёт
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}ДЕПЛОЙ ЗАВЕРШЕН${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Бэкап сохранён в: $BACKUP_PATH"
echo "Для отката используйте: ./deploy/rollback.sh $BACKUP_DATE"
echo ""
echo "Проверьте работу:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f --lines=50"
echo "  tail -f bot.log | grep loyalty"

