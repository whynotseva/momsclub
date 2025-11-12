#!/bin/bash
#
# Скрипт для подключения к серверу и выполнения деплоя
# Запустите локально: ./deploy/connect_and_deploy.sh
#

set -e

SERVER="root@109.73.199.102"
PASSWORD="v*B9AR#4fD9pih"

echo "========================================="
echo "ПОДКЛЮЧЕНИЕ К СЕРВЕРУ И ДЕПЛОЙ"
echo "========================================="
echo ""

# Проверка наличия sshpass
if ! command -v sshpass &> /dev/null; then
    echo "Установка sshpass..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            brew install hudochenkov/sshpass/sshpass
        else
            echo "Ошибка: установите sshpass: brew install hudochenkov/sshpass/sshpass"
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        sudo apt-get update && sudo apt-get install -y sshpass
    fi
fi

echo "Подключение к серверу..."
echo ""

# Команды для выполнения на сервере
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$SERVER" << 'ENDSSH'
set -e

echo "========================================="
echo "НА СЕРВЕРЕ: Проверка состояния"
echo "========================================="

cd /root/home/momsclub || { echo "Ошибка: директория не найдена"; exit 1; }

echo "✓ Текущая директория: $(pwd)"
echo ""

# Проверка статуса бота
if systemctl is-active --quiet momsclub 2>/dev/null || systemctl is-active --quiet momsclub_bot 2>/dev/null; then
    echo "✓ Бот работает"
    systemctl status momsclub --no-pager -l | head -5 || systemctl status momsclub_bot --no-pager -l | head -5
else
    echo "⚠ Бот не запущен"
fi

echo ""
echo "Список файлов:"
ls -la | head -10
echo ""

# Проверка наличия deploy скриптов
if [ -d "deploy" ]; then
    echo "✓ Папка deploy найдена"
    ls -la deploy/*.sh 2>/dev/null | head -5 || echo "Скрипты deploy не найдены"
else
    echo "⚠ Папка deploy не найдена - нужно загрузить"
fi

echo ""
echo "========================================="
echo "ГОТОВО К ДЕПЛОЮ"
echo "========================================="
ENDSSH

echo ""
echo "Подключение успешно!"
echo ""
echo "Следующий шаг: запустить деплой"
echo "Выполнить деплой сейчас? (yes/no)"
read -r response

if [ "$response" = "yes" ]; then
    echo "Начинаю деплой..."
    sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$SERVER" 'bash -s' < deploy/remote_deploy.sh
fi

