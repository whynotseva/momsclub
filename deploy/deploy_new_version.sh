#!/bin/bash
#
# Скрипт развертывания новой версии после создания бэкапа
# Использование: ./deploy_new_version.sh
#
# ПРЕДУСЛОВИЕ: должен быть запущен safe_deploy.sh перед этим

set -e  # Прекратить выполнение при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Параметры
CURRENT_DIR="/root/home/momsclub"
SERVICE_NAME="momsclub"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Развертывание новой версии${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Проверка, что скрипт запущен от root или с sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Ошибка: скрипт должен быть запущен от root или с sudo${NC}"
    exit 1
fi

# Проверка существования директории
if [ ! -d "$CURRENT_DIR" ]; then
    echo -e "${RED}Ошибка: директория $CURRENT_DIR не найдена${NC}"
    exit 1
fi

cd "$CURRENT_DIR"

echo -e "${YELLOW}Шаг 1: Проверка зависимостей${NC}"
if [ -f "requirements.txt" ]; then
    echo "Обновление зависимостей..."
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    pip install -r requirements.txt --quiet
    echo -e "${GREEN}✓ Зависимости обновлены${NC}"
else
    echo -e "${YELLOW}⚠ requirements.txt не найден, пропускаю обновление зависимостей${NC}"
fi

echo ""

echo -e "${YELLOW}Шаг 2: Запуск миграции базы данных${NC}"
if [ -n "${SKIP_MIGRATE}" ]; then
    echo -e "${YELLOW}SKIP_MIGRATE установлен — пропускаю миграцию${NC}"
else
    if [ -f "database/migrations/add_loyalty_fields.py" ]; then
        echo "Выполняется миграция add_loyalty_fields.py..."
        # Используем python3 для надёжности
        python3 database/migrations/add_loyalty_fields.py
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Миграция выполнена успешно${NC}"
        else
            echo -e "${RED}Ошибка при выполнении миграции!${NC}"
            exit 1
        fi
    else
        echo -e "${RED}Ошибка: файл миграции не найден${NC}"
        exit 1
    fi
fi

echo ""

echo -e "${YELLOW}Шаг 3: Проверка синтаксиса Python файлов${NC}"
echo "Проверка основных файлов..."
python -m py_compile bot.py handlers/*.py loyalty/*.py 2>/dev/null || {
    echo -e "${RED}Ошибка: найдены синтаксические ошибки${NC}"
    exit 1
}
echo -e "${GREEN}✓ Синтаксис корректен${NC}"

echo ""

echo -e "${YELLOW}Шаг 4: Проверка конфигурации${NC}"
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠ Файл .env не найден${NC}"
    echo "Убедитесь, что переменные окружения настроены"
else
    echo -e "${GREEN}✓ Файл .env найден${NC}"
fi

echo ""

echo -e "${YELLOW}Шаг 5: Запуск сервиса${NC}"
if systemctl start $SERVICE_NAME; then
    echo -e "${GREEN}✓ Сервис $SERVICE_NAME запущен${NC}"
elif systemctl start "${SERVICE_NAME}_bot"; then
    echo -e "${GREEN}✓ Сервис ${SERVICE_NAME}_bot запущен${NC}"
else
    echo -e "${RED}Ошибка: не удалось запустить сервис${NC}"
    echo "Проверьте конфигурацию сервиса"
    exit 1
fi

# Проверка статуса
sleep 2
if systemctl is-active --quiet $SERVICE_NAME || systemctl is-active --quiet "${SERVICE_NAME}_bot"; then
    echo -e "${GREEN}✓ Сервис работает${NC}"
else
    echo -e "${RED}⚠ Сервис не запустился, проверьте логи${NC}"
fi

echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Развертывание завершено${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Проверьте статус: systemctl status $SERVICE_NAME"
echo "Проверьте логи: journalctl -u $SERVICE_NAME -f --lines=50"
echo ""
echo "Для отката используйте скрипт: ./rollback.sh [дата_бэкапа]"

