"""
Migration to fix the users table primary key issue
"""

import sqlite3
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

def fix_users_primary_key():
    """Fixes the users table primary key to be auto-incrementing"""

    # Path to database
    db_path = Path(__file__).parent.parent.parent / "momsclub.db"

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return False

    try:
        # Connect to database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check current table structure
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()

        print("Current users table structure:")
        for col in columns:
            print(f"  {col[1]}: {col[2]} {'PRIMARY KEY' if col[5] else ''}")

        # Check if id column is properly configured
        id_column = next((col for col in columns if col[1] == 'id'), None)

        if id_column and id_column[5] == 1:  # cid 5 is pk flag
            print("Primary key is already properly configured")
            conn.close()
            return True

        print("Fixing primary key configuration...")

        # Create new table with correct schema
        cursor.execute("""
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_active INTEGER DEFAULT 1,
                referrer_id INTEGER,
                referral_code TEXT UNIQUE,
                welcome_sent INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                birthday DATE,
                birthday_gift_year INTEGER,
                payment_method_id TEXT,
                is_recurring_active INTEGER DEFAULT 0,
                phone TEXT,
                email TEXT,
                reminder_sent INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                FOREIGN KEY (referrer_id) REFERENCES users_new(id) ON DELETE SET NULL
            )
        """)

        # Copy data from old table to new table
        cursor.execute("""
            INSERT INTO users_new (
                id, telegram_id, username, first_name, last_name, is_active,
                referrer_id, referral_code, welcome_sent, created_at, updated_at,
                birthday, birthday_gift_year, payment_method_id, is_recurring_active,
                phone, email, reminder_sent, is_blocked
            )
            SELECT
                id, telegram_id, username, first_name, last_name, is_active,
                referrer_id, referral_code, welcome_sent, created_at, updated_at,
                birthday, birthday_gift_year, payment_method_id, is_recurring_active,
                phone, email, reminder_sent, is_blocked
            FROM users
        """)

        # Drop old table
        cursor.execute("DROP TABLE users")

        # Rename new table to users
        cursor.execute("ALTER TABLE users_new RENAME TO users")

        # Recreate indexes
        cursor.execute("CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id)")
        cursor.execute("CREATE UNIQUE INDEX idx_users_referral_code ON users(referral_code)")

        # Commit changes
        conn.commit()

        print("Primary key fix completed successfully")

        # Verify the fix
        cursor.execute("PRAGMA table_info(users)")
        new_columns = cursor.fetchall()

        print("New users table structure:")
        for col in new_columns:
            print(f"  {col[1]}: {col[2]} {'PRIMARY KEY' if col[5] else ''}")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Error fixing users primary key: {e}")
        print(f"Error fixing users primary key: {e}")
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = fix_users_primary_key()
    if success:
        print("✅ Users table primary key has been fixed")
    else:
        print("❌ Failed to fix users table primary key")
