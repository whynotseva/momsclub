# 🔌 Анализ работы портов на сервере

## 📊 Текущая ситуация

| Порт | Сервис | Управление | Статус |
|------|--------|------------|--------|
| **80/443** | nginx | systemd ✅ | Стабильно |
| **8000** | telegram-bot (FastAPI) | systemd ✅ | Стабильно |
| **8001** | library-api (uvicorn) | systemd ✅ | Стабильно |
| **3000** | Next.js (frontend) | screen/nohup ❌ | **ПРОБЛЕМА** |

---

## ⚠️ Причина проблем с портами

### Проблема 1: Next.js (порт 3000) НЕ под systemd

**Симптомы:**
- После перезапуска сервера Next.js не стартует автоматически
- Сложно остановить/перезапустить — процесс "зомби"
- Иногда запускается несколько экземпляров (3000 + 3001)

**Почему так:**
```bash
# Сейчас запускается через screen:
SCREEN -dmS next bash -c "cd /root/home/library_frontend && npx next start -p 3001"
```
Это ненадёжно — процесс может "потеряться".

### Проблема 2: Я не знал про library-api.service

Когда я делал `pkill uvicorn` — systemd сразу перезапускал сервис, отсюда "Address already in use".

**Правильный способ:**
```bash
systemctl restart library-api   # НЕ pkill!
```

---

## ✅ Решение: Создать systemd сервис для Next.js

### Шаг 1: Создать файл сервиса

```bash
sudo nano /etc/systemd/system/library-frontend.service
```

```ini
[Unit]
Description=LibriMomsClub Frontend (Next.js)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/home/library_frontend
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=10
Environment=NODE_ENV=production
Environment=PORT=3000

[Install]
WantedBy=multi-user.target
```

### Шаг 2: Включить и запустить

```bash
systemctl daemon-reload
systemctl enable library-frontend
systemctl start library-frontend
```

### Шаг 3: Убить старые процессы

```bash
pkill -f "next-server"
pkill -f "next start"
screen -X -S next quit
```

---

## 📋 Итоговая архитектура (после исправления)

```
┌─────────────────────────────────────────────────────────────┐
│                         NGINX                               │
│                    (порты 80, 443)                          │
│                    systemd: nginx                           │
└─────────────────────┬───────────────────┬───────────────────┘
                      │                   │
                      ▼                   ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│    librarymomsclub.ru       │   │   momsclubwebhook.ru        │
│    (проксируется на 3000)   │   │   (проксируется на 8000)    │
└─────────────────────────────┘   └─────────────────────────────┘
                      │                   │
                      ▼                   ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│      NEXT.JS FRONTEND       │   │      TELEGRAM BOT           │
│         (порт 3000)         │   │      (порт 8000)            │
│  systemd: library-frontend  │   │  systemd: telegram-bot      │
└─────────────────────────────┘   └─────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────┐
│      LIBRARY BACKEND        │
│        (порт 8001)          │
│    systemd: library-api     │
└─────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────┐
│        momsclub.db          │
│     (общая база данных)     │
└─────────────────────────────┘
```

---

## 🛠 Команды для управления сервисами

```bash
# Telegram Bot
systemctl status telegram-bot
systemctl restart telegram-bot
systemctl stop telegram-bot
journalctl -u telegram-bot -f   # логи в реальном времени

# Library Backend API
systemctl status library-api
systemctl restart library-api
journalctl -u library-api -f

# Library Frontend (после создания сервиса)
systemctl status library-frontend
systemctl restart library-frontend
journalctl -u library-frontend -f

# Nginx
systemctl status nginx
systemctl restart nginx
systemctl reload nginx   # перезагрузка конфига без downtime
```

---

## 🚫 Что НЕ делать

```bash
# НЕПРАВИЛЬНО:
pkill -f uvicorn        # systemd сразу перезапустит
kill $(lsof -t -i:8001) # то же самое
fuser -k 8001/tcp       # то же самое

# ПРАВИЛЬНО:
systemctl restart library-api
```

---

## 📝 TODO: Исправить порт 3000

1. [ ] Создать `/etc/systemd/system/library-frontend.service`
2. [ ] `systemctl daemon-reload`
3. [ ] Убить старые процессы Next.js
4. [ ] `systemctl enable --now library-frontend`
5. [ ] Проверить: `systemctl status library-frontend`
6. [ ] Обновить deploy.sh — использовать `systemctl restart library-frontend`

---

## 💡 Бонус: Обновлённый deploy.sh для фронтенда

После создания systemd сервиса, deploy.sh станет проще:

```bash
#!/bin/bash
# Копируем файлы
rsync -avz --exclude 'node_modules' --exclude '.next' \
  /local/path/ root@server:/root/home/library_frontend/

# Билд и рестарт через systemd
ssh root@server "cd /root/home/library_frontend && \
  npm run build && \
  systemctl restart library-frontend"

# Очистка nginx кэша
ssh root@server "systemctl reload nginx"
```

Никаких `pkill`, `lsof`, `fuser` — только systemctl! 🎉
