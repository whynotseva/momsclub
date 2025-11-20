-- Миграция: Добавление таблицы group_activity_log для детального логирования активности
-- Дата: 2025-11-20
-- Описание: Создаём таблицу для отслеживания активности пользователей по дням

CREATE TABLE IF NOT EXISTS group_activity_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    message_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_date UNIQUE (user_id, date)
);

-- Индекс для быстрого поиска по пользователю
CREATE INDEX IF NOT EXISTS idx_group_activity_log_user_id ON group_activity_log(user_id);

-- Индекс для быстрого поиска по дате
CREATE INDEX IF NOT EXISTS idx_group_activity_log_date ON group_activity_log(date);

-- Индекс для быстрого поиска по пользователю и дате
CREATE INDEX IF NOT EXISTS idx_group_activity_log_user_date ON group_activity_log(user_id, date);

-- Комментарий к таблице
COMMENT ON TABLE group_activity_log IS 'Детальное логирование активности пользователей в группе по дням';
COMMENT ON COLUMN group_activity_log.user_id IS 'ID пользователя';
COMMENT ON COLUMN group_activity_log.date IS 'Дата активности (без времени)';
COMMENT ON COLUMN group_activity_log.message_count IS 'Количество сообщений за этот день';
