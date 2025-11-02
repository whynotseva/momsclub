# Mom's Club Telegram Bot - AI Coding Instructions

## Project Overview
This is a Telegram subscription bot for "Mom's Club" - a paid community platform with advanced features including subscription management, automated renewals, referral system, birthday rewards, and payment processing through Prodamus.

## Architecture Pattern
- **Hybrid execution model**: Bot uses polling for Telegram updates + FastAPI webhook server for payment callbacks
- **Layered architecture**: `handlers/` → `database/crud.py` → `database/models.py`
- **Async-first**: All database operations use SQLAlchemy async sessions (`AsyncSessionLocal`)
- **Logging segregation**: Separate loggers for payments, birthdays, auto-renewals, and reminders

## Critical Database Patterns

### Session Management
```python
# Always use this pattern for database operations
async with AsyncSessionLocal() as db:
    result = await crud_function(db, ...)
    await db.commit()  # Only if modifying data
```

### Key Models
- `User`: Core user data with `telegram_id`, subscription tracking, referral system
- `Subscription`: Time-based access with auto-renewal capabilities
- `PaymentLog`: Transaction tracking with Prodamus integration
- `PromoCode`: Discount system with usage tracking

## Payment System Architecture

### Prodamus Integration
- **Payment flow**: User handlers → `utils/payment.py` → Prodamus API → webhook callback
- **Webhook endpoint**: FastAPI server in `handlers/webhook_handlers.py` runs parallel to bot
- **Auto-renewals**: Background task checks subscriptions every 2 hours via `SUBSCRIPTION_RENEWAL_SETTINGS`

### Payment Processing Pattern
```python
# Standard payment creation in handlers
payment_url, payment_id, payment_label = await create_payment_link(amount, user_id, description)
# Always log payment attempts
await create_payment_log(db, user_id, amount, "pending", payment_id)
```

## Subscription Management

### Access Control
- Group membership managed via `utils/group_manager.py`
- Auto-removal on expiration using `GroupManager.remove_user()`
- Welcome messages sent to specific forum topic (`CLUB_GROUP_TOPIC_ID`)

### Renewal Logic
- Background task `check_and_renew_subscriptions()` handles auto-renewals
- Failed payments retry on schedule: days 1, 3, 5 before disabling auto-renewal
- Manual renewal notifications sent 1 day before expiration

## Background Tasks Pattern

Bot runs 4 concurrent background tasks:
```python
# In main()
asyncio.create_task(congratulate_birthdays())      # Daily birthday checks
asyncio.create_task(check_expired_subscriptions()) # Hourly expiration cleanup  
asyncio.create_task(check_and_renew_subscriptions()) # Auto-renewal processing
asyncio.create_task(send_scheduled_messages())     # Admin broadcast system
```

## Development Workflow

### Running the Bot
```bash
python bot.py  # Starts polling + webhook server on port 8000
```

### Database Operations
```bash
python database/create_db.py  # Initialize database schema
```

### Environment Setup
- Copy `.env.example` to `.env` and configure:
  - `BOT_TOKEN`: Telegram bot token
  - Prodamus configuration is in `config.py` (`PRODAMUS_CONFIG`)
  - Group/channel IDs in `utils/constants.py`

## Key Integration Points

### Handler Registration
- All handlers must be registered in `bot.py` via `register_*_handlers(dp)`
- Use router pattern: each handler file creates `Router()` and exports registration function

### Message Templates
- Welcome/notification templates stored in database (`MessageTemplate` model)
- Media files in `media/` directory, referenced by relative paths
- Admin broadcast system supports scheduled delivery

### Error Handling
- Payment errors logged to separate `payment_logs.log`
- Database errors should always rollback session
- Bot blocks handled by updating `User.is_blocked = True`

## Testing Considerations
- Test payment webhooks using Prodamus sandbox
- Mock async database sessions in unit tests
- Background tasks can be tested by calling functions directly (they're regular async functions)

## Common Pitfalls
- Never mix sync/async SQLAlchemy operations
- Always handle `IntegrityError` for unique constraints (usernames, referral codes)
- Payment webhook validation must verify HMAC signature (Prodamus uses HMAC-SHA256)
- Background tasks need graceful shutdown handling in production
