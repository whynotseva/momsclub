#!/usr/bin/env python3
"""
Скрипт для подключения к серверу и выполнения деплоя
"""
import subprocess
import sys
import os

SERVER = "root@109.73.199.102"
PASSWORD = "v*B9AR#4fD9pih"

def run_ssh_command(command):
    """Выполняет команду на сервере через SSH"""
    try:
        # Используем expect для автоматизации ввода пароля
        expect_script = f'''
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {SERVER}
expect "password:"
send "{PASSWORD}\\r"
expect "# "
send "{command}\\r"
expect "# "
send "exit\\r"
expect eof
'''
        result = subprocess.run(
            ['expect', '-c', expect_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except FileNotFoundError:
        return False, "", "expect не установлен. Установите: brew install expect"
    except subprocess.TimeoutExpired:
        return False, "", "Таймаут выполнения команды"

def main():
    print("=" * 50)
    print("ПОДКЛЮЧЕНИЕ К СЕРВЕРУ")
    print("=" * 50)
    print("")
    
    # Проверка expect
    if not os.path.exists('/usr/bin/expect') and not os.path.exists('/usr/local/bin/expect'):
        print("❌ expect не установлен")
        print("Установите: brew install expect")
        print("")
        print("Или используйте ручное подключение:")
        print(f"ssh {SERVER}")
        print(f"Пароль: {PASSWORD}")
        return
    
    print("🔍 Шаг 1: Проверка состояния сервера...")
    print("")
    
    commands = [
        "cd /root/home/momsclub && pwd",
        "systemctl status momsclub --no-pager -l | head -5 || systemctl status momsclub_bot --no-pager -l | head -5",
        "ls -la /root/home/momsclub | head -10",
        "[ -d /root/home/momsclub/loyalty ] && echo 'loyalty найден' || echo 'loyalty НЕ найден'",
        "[ -f /root/home/momsclub/database/migrations/add_loyalty_fields.py ] && echo 'миграция найдена' || echo 'миграция НЕ найдена'"
    ]
    
    for cmd in commands:
        success, stdout, stderr = run_ssh_command(cmd)
        if success:
            print(stdout)
        else:
            print(f"⚠ Ошибка: {stderr}")
    
    print("")
    print("=" * 50)
    print("Проверка завершена")
    print("=" * 50)

if __name__ == "__main__":
    main()

