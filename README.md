# Washer CRM

Веб-CRM для автомойки и детейлинг-центра. Flask + SQLite + Tailwind, упакован в Docker.

## Возможности (MVP)

- Аутентификация и роли: **admin / manager / worker / client**
- Заказы (work orders) с услугами, скидками, бонусами, оплатами и фото до/после
- Чек из карточки заказа (печать на странице чека)
- CRM клиентов и их автомобилей
- Услуги и категории, рецепты материалов на услугу
- Пакеты услуг (конструктор + добавление в заказ)
- Списание склада при закрытии заказа (шаблон по рецепту, ручная правка)
- Склад с автодвижениями
- Сотрудники и модели зарплат
- Зарплатная ведомость за период + KPI расчёт (fixed / percent / kpi)
- Касса с итогами по дню и методам оплаты
- Бонусная программа (cashback, уровни Silver/Gold/Platinum)
- **Полная админка**: общие настройки, НДС, Azericard, Evolution API (WhatsApp), **шаблон чека**, пользователи, филиалы, audit log
- **Портал работника** (`/worker`): назначенные заказы, смена статуса, списание материалов
- **Бэкап БД + картинок одним архивом** с восстановлением
- Persistent storage: БД и загруженные файлы лежат в `app/static/data` и `app/static/uploads` — переживают пересборку контейнера

## Стек

- Backend: Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-WTF
- DB: SQLite (файл `app/static/data/app.db`)
- Frontend: Jinja2 + Tailwind (CDN) + Chart.js
- Контейнер: Python 3.12-slim + gunicorn

## Запуск (Docker)

```bash
cp .env.example .env
# отредактируйте .env — SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD

docker compose build
docker compose up -d
```

Откройте http://localhost:7000

Учётка администратора берётся из `.env` (по умолчанию `admin@washer.local` / `admin123`). Вход также возможен по телефону `+994…`, если он указан в карточке пользователя (Админка → Пользователи).

### Где хранятся данные

Два именованных docker volume:

- `washer_data` → `/app/app/static/data` (SQLite база)
- `washer_uploads` → `/app/app/static/uploads` (картинки заказов, логотипы и т.п.)

При `docker compose build && up -d` данные сохраняются. Удалить можно через `docker volume rm`.

## Запуск без Docker (dev)

```bash
python -m venv .venv
. .venv/Scripts/activate    # Windows
pip install -r requirements.txt
cp .env.example .env
python wsgi.py
```

## Бэкап

Админка → **Настройки** → **Бэкап**:

- **Скачать архив** — zip с базой + uploads (можно сохранить локально или в облако)
- **Восстановить** — загрузка zip перезапишет текущие данные. После восстановления перезапустите контейнер.

## Брендинг

Админка → **Настройки → Брендинг**:

- Логотип, название компании, адрес, телефон, email, сайт

Данные отображаются в боковом меню, на странице входа и в чеках. В WhatsApp подставляются как `{company}`, `{contacts}` и `{instagram}`.

Шаблоны сообщений — **Настройки → Evolution API** (правая колонка): переменные `{company}`, `{order_number}`, `{client_name}`, `{contacts}`, `{instagram}`.

## Шаблон чека

Админка → **Настройки → Шаблон чека**:

- HTML-разметка с переменными `{company_name}`, `{order_number}`, `{items_table}` и др.
- Кассир по умолчанию и текст внизу чека
- Пустой шаблон = встроенный стандартный вид

Чек открывается из карточки заказа кнопкой **Чек**; на странице чека — печать.

## Интеграции

### Azericard

Админка → Настройки → Azericard. Заполните Terminal ID, Merchant Name, Merchant URL, валюту (944 = AZN), **приватный RSA-ключ мерчанта** (PEM) и **публичный ключ Azericard** для проверки callback. BACKREF: `https://ваш-домен/payments/azericard/backref` (должен быть доступен из интернета по HTTPS).

В карточке заказа выберите **Azericard** и сумму → **Создать ссылку на оплату**. Появится ссылка и кнопка **Отправить на оплату** (WhatsApp клиенту). Клиент открывает ссылку `/pay/<token>` и переходит на MPI. Шаблон сообщения: Настройки → WhatsApp. Журнал: Настройки → Azericard → «Журнал Azericard».

### Evolution API (WhatsApp)

Админка → Настройки → Evolution API: слева — подключение (Base URL, API Key, инстанс), справа — системные шаблоны и **дополнительные шаблоны для рассылки** (создание и редактирование). Кнопка «Проверить подключение» — `/instance/connectionState`.

- Уведомления: при создании заказа и при статусе «Завершён»
- **CRM → Клиенты**: кнопка WhatsApp у каждого клиента (личное сообщение по шаблону) и **«Рассылка WhatsApp»** по списку на странице
- **Напоминания по расписанию** (шаблон «Напоминание»): клиентам, у кого последняя завершённая мойка была N дней назад (`evolution_reminder_days`)

Cron (ежедневно, пример):

```bash
# через Flask CLI
flask wa-reminders

# или HTTP (задайте CRON_SECRET в .env)
curl "http://localhost:7000/cron/wa-reminders?token=YOUR_CRON_SECRET"
```

Проверка без отправки: `flask wa-reminders --dry-run`

## Структура проекта

```
washer2/
├─ Dockerfile, docker-compose.yml, requirements.txt
├─ wsgi.py
└─ app/
   ├─ __init__.py          app factory
   ├─ config.py            конфигурация
   ├─ extensions.py        db, login_manager, csrf, migrate
   ├─ models/              SQLAlchemy модели (user, client, order, service…)
   ├─ blueprints/          разделение по доменам
   │  ├─ auth, dashboard, admin
   │  ├─ crm, services, orders
   │  ├─ inventory, finance, employees
   ├─ services/            бизнес-логика (azericard, evolution_api, backup)
   ├─ utils/               decorators, uploads, template_filters
   ├─ templates/           Jinja2
   └─ static/
      ├─ uploads/          ← persistent (volume)
      └─ data/             ← persistent (SQLite)
```

## Безопасность

- CSRF включён глобально (Flask-WTF)
- Парольный хэш — `werkzeug.security` (PBKDF2)
- Доступы через декораторы `@admin_required`, `@manager_required`, `@staff_required`
- Audit log сохраняет действия пользователей с IP

## Что ещё не сделано (roadmap)

Эти модули из плана либо имеют заглушки, либо требуют расширения:

- AI WhatsApp бот (модуль 10)
- Аналитика — расширенные графики и сегментация (модуль 11)
- Расширение KPI-формул (весовые коэффициенты, штрафы, качество, скорость)
- ~~Multi-branch фильтрация по UI~~ (заказы, дашборд, касса, зарплаты)
- Client/Worker portals (роли есть, UI порталов — следующий шаг)
