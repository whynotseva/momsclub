#!/bin/bash
# Шаг 1: Проверка состояния сервера

SERVER="root@109.73.199.102"
PASSWORD="v*B9AR#4fD9pih"

echo "🔍 Проверка состояния сервера..."
echo ""

if command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$SERVER" << 'EOF'
cd /root/home/momsclub || { echo "❌ Директория /root/home/momsclub не найдена"; exit 1; }

echo "✓ Директория найдена: $(pwd)"
echo ""

echo "📊 Статус бота:"
if systemctl is-active --quiet momsclub 2>/dev/null; then
    echo "✓ Сервис momsclub: работает"
    systemctl status momsclub --no-pager -l | head -3
elif systemctl is-active --quiet momsclub_bot 2>/dev/null; then
    echo "✓ Сервис momsclub_bot: работает"
    systemctl status momsclub_bot --no-pager -l | head -3
else
    echo "⚠ Бот не запущен"
fi

echo ""
echo "📁 Структура директории:"
ls -la | head -10

echo ""
echo "📦 Проверка ключевых файлов:"
[ -f "bot.py" ] && echo "✓ bot.py" || echo "✗ bot.py не найден"
[ -f "database/models.py" ] && echo "✓ database/models.py" || echo "✗ database/models.py не найден"
[ -f "handlers/user_handlers.py" ] && echo "✓ handlers/user_handlers.py" || echo "✗ handlers/user_handlers.py не найден"

echo ""
echo "📦 Проверка новых файлов лояльности:"
[ -d "loyalty" ] && echo "✓ папка loyalty существует" || echo "✗ папка loyalty не найдена"
[ -f "loyalty/levels.py" ] && echo "✓ loyalty/levels.py" || echo "✗ loyalty/levels.py не найден"
[ -f "database/migrations/add_loyalty_fields.py" ] && echo "✓ database/migrations/add_loyalty_fields.py" || echo "✗ миграция не найдена"

echo ""
echo "📦 Проверка deploy скриптов:"
if [ -d "deploy" ]; then
    echo "✓ папка deploy существует"
    ls -1 deploy/*.sh 2>/dev/null | wc -l | xargs -I {} echo "  найдено {} скриптов"
else
    echo "✗ папка deploy не найдена - нужно загрузить"
fi

echo ""
echo "💾 База данных:"
[ -f "momsclub.db" ] && echo "✓ momsclub.db существует ($(du -h momsclub.db | cut -f1))" || echo "✗ momsclub.db не найдена"

echo ""
echo "========================================="
echo "Проверка завершена"
echo "========================================="
EOF
else
    echo "⚠ sshpass не установлен"
    echo "Подключитесь вручную: ssh root@109.73.199.102"
    echo "И выполните команды из deploy/SERVER_COMMANDS.md"
fi

