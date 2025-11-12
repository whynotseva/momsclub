#!/bin/bash
# ==========================================
# КОМАНДЫ ДЛЯ ВЫПОЛНЕНИЯ НА СЕРВЕРЕ
# Скопируйте и выполните эти команды на сервере
# ==========================================

echo "========================================="
echo "ДЕПЛОЙ СИСТЕМЫ ЛОЯЛЬНОСТИ"
echo "========================================="
echo ""

# Переход в директорию проекта
cd /root/home/momsclub || exit 1

# Проверка статуса
echo "Проверка текущего состояния..."
systemctl status momsclub --no-pager -l | head -10
echo ""

# Создание скриптов исполняемыми
echo "Подготовка скриптов..."
chmod +x deploy/*.sh 2>/dev/null || echo "Скрипты deploy не найдены - загрузите их сначала"
echo ""

# Информация
echo "========================================="
echo "ГОТОВО К ДЕПЛОЮ"
echo "========================================="
echo ""
echo "Выберите вариант:"
echo ""
echo "1. Автоматический деплой (всё за один раз):"
echo "   cd /root/home/momsclub/deploy"
echo "   sudo ./full_deploy.sh"
echo ""
echo "2. Пошаговый деплой (с подтверждениями):"
echo "   cd /root/home/momsclub/deploy"
echo "   sudo ./safe_deploy.sh \$(date +%d%m%Y)"
echo "   # (загрузите новые файлы)"
echo "   sudo ./deploy_new_version.sh"
echo ""
echo "Для подробных инструкций см. deploy/COMPLETE_DEPLOY_GUIDE.md"

