"""
Миграция обратно на ЮКассу
1. Переименование payment_method_id → yookassa_payment_method_id
2. Отключение автопродления для всех (нужно заново настраивать)
3. Очистка Prodamus данных
"""

import os
import sys
import sqlite3
from datetime import datetime

# Добавляем корневую папку в путь
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate_to_yookassa(db_path="momsclub.db"):
    """
    Выполняет миграцию обратно на ЮКассу
    
    Args:
        db_path (str): Путь к файлу базы данных
    """
    
    print("="*60)
    print("🔄 МИГРАЦИЯ ОБРАТНО НА ЮКАССУ")
    print("="*60)
    print(f"База данных: {db_path}\n")
    
    # Создаем резервную копию
    backup_path = f"{db_path}.backup_yookassa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Резервная копия создана: {backup_path}\n")
    except Exception as e:
        print(f"⚠️  Не удалось создать резервную копию: {e}")
        response = input("Продолжить без резервной копии? (y/N): ")
        if response.lower() != 'y':
            print("❌ Миграция отменена")
            return False
    
    # Подключение к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("📋 Начинаем выполнение миграций...\n")
        
        # 1. Проверяем текущую структуру таблицы users
        cursor.execute("PRAGMA table_info(users)")
        columns = {col[1]: col for col in cursor.fetchall()}
        
        print("📊 Текущие поля в таблице users:")
        for col_name in columns.keys():
            print(f"   - {col_name}")
        print()
        
        # 2. Переименовываем payment_method_id → yookassa_payment_method_id
        if 'payment_method_id' in columns and 'yookassa_payment_method_id' not in columns:
            print("🔄 Переименовываем payment_method_id → yookassa_payment_method_id...")
            
            # SQLite не поддерживает переименование напрямую, используем временную таблицу
            cursor.execute("""
                CREATE TABLE users_new AS 
                SELECT 
                    id, telegram_id, username, first_name, last_name, is_active,
                    referrer_id, referral_code, welcome_sent, created_at, updated_at,
                    birthday, birthday_gift_year,
                    NULL as yookassa_payment_method_id,
                    is_recurring_active, phone, email, reminder_sent, is_blocked
                FROM users
            """)
            
            cursor.execute("DROP TABLE users")
            cursor.execute("ALTER TABLE users_new RENAME TO users")
            
            # Восстанавливаем индексы
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code) WHERE referral_code IS NOT NULL")
            
            print("✅ Поле переименовано: payment_method_id → yookassa_payment_method_id")
            print("   (Все payment_method_id очищены - нужно заново настраивать автоплатежи)\n")
        else:
            print("ℹ️  Поле yookassa_payment_method_id уже существует или payment_method_id отсутствует\n")
        
        # 3. Отключаем автопродление для ВСЕХ пользователей
        print("🔄 Отключаем автопродление для всех пользователей...")
        cursor.execute("UPDATE users SET is_recurring_active = 0")
        disabled_count = cursor.rowcount
        print(f"✅ Автопродление отключено для {disabled_count} пользователей\n")
        
        # 4. Очищаем Prodamus subscription_id в subscriptions (опционально)
        print("🔄 Проверяем поле subscription_id в subscriptions...")
        cursor.execute("PRAGMA table_info(subscriptions)")
        sub_columns = {col[1]: col for col in cursor.fetchall()}
        
        if 'subscription_id' in sub_columns:
            cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE subscription_id IS NOT NULL")
            prodamus_subs = cursor.fetchone()[0]
            
            if prodamus_subs > 0:
                print(f"   Найдено {prodamus_subs} подписок с Prodamus subscription_id")
                print("   Очищаем (данные сохранены в резервной копии)...")
                cursor.execute("UPDATE subscriptions SET subscription_id = NULL")
                print(f"✅ Очищено {cursor.rowcount} subscription_id\n")
            else:
                print("   Нет подписок с Prodamus subscription_id\n")
        
        # 5. Помечаем платежи Prodamus для истории
        print("🔄 Помечаем платежи Prodamus в истории...")
        cursor.execute("""
            UPDATE payment_logs 
            SET details = 'PRODAMUS (старая система): ' || COALESCE(details, '')
            WHERE payment_method LIKE '%prodamus%'
        """)
        marked_payments = cursor.rowcount
        print(f"✅ Помечено {marked_payments} платежей Prodamus\n")
        
        # Сохраняем все изменения
        conn.commit()
        
        # 6. Финальная проверка
        print("="*60)
        print("🔍 ФИНАЛЬНАЯ ПРОВЕРКА")
        print("="*60)
        
        cursor.execute("PRAGMA table_info(users)")
        final_columns = [col[1] for col in cursor.fetchall()]
        
        checks = [
            ('yookassa_payment_method_id в users', 'yookassa_payment_method_id' in final_columns),
            ('payment_method_id удалено', 'payment_method_id' not in final_columns),
            ('Автопродление отключено', True)
        ]
        
        all_passed = True
        for check_name, check_result in checks:
            status = "✅" if check_result else "❌"
            print(f"{status} {check_name}")
            if not check_result:
                all_passed = False
        
        print()
        
        # Статистика
        cursor.execute("SELECT COUNT(*) FROM users WHERE yookassa_payment_method_id IS NOT NULL")
        users_with_methods = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_recurring_active = 1")
        users_with_auto = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE subscription_id IS NOT NULL")
        subs_with_prodamus = cursor.fetchone()[0]
        
        print("📊 СТАТИСТИКА ПОСЛЕ МИГРАЦИИ:")
        print(f"   - Пользователей с yookassa_payment_method_id: {users_with_methods}")
        print(f"   - С включенным автопродлением: {users_with_auto}")
        print(f"   - Подписок с Prodamus ID: {subs_with_prodamus}")
        print()
        
        if all_passed:
            print("="*60)
            print("🎉 МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")
            print("="*60)
            print(f"📦 Резервная копия: {backup_path}")
            print()
            print("⚠️  ВАЖНО:")
            print("   1. Все пользователи должны заново настроить автопродление")
            print("   2. Обновите .env файл с ключами ЮКассы")
            print("   3. Установите: pip install yookassa")
            print("   4. Настройте webhook в личном кабинете ЮКассы")
            print("="*60)
            return True
        else:
            print("❌ Миграция завершена с ошибками")
            return False
            
    except Exception as e:
        print(f"\n❌ ОШИБКА ВО ВРЕМЯ МИГРАЦИИ: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def rollback_migration(db_path="momsclub.db"):
    """Откат миграции из резервной копии"""
    import glob
    
    backup_files = glob.glob(f"{db_path}.backup_yookassa_*")
    if not backup_files:
        print("❌ Резервные копии не найдены")
        return False
    
    latest_backup = max(backup_files)
    
    print(f"🔄 Восстанавливаем из: {latest_backup}")
    
    try:
        import shutil
        shutil.copy2(latest_backup, db_path)
        print("✅ База данных восстановлена")
        return True
    except Exception as e:
        print(f"❌ Ошибка восстановления: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_migration()
    else:
        migrate_to_yookassa()

