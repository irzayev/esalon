"""Default chatbot message templates."""

DEFAULT_CHATBOT_WELCOME = (
    "{company}\n"
    "Добро пожаловать!\n\n"
    "1 — {menu_info}\n"
    "2 — {menu_booking}\n"
    "3 — {menu_operator}\n\n"
    "Ответьте цифрой или напишите запрос."
)

DEFAULT_MENU_INFO = "Информация"
DEFAULT_MENU_BOOKING = "Запись на мойку"
DEFAULT_MENU_OPERATOR = "Связаться с оператором"

DEFAULT_CHATBOT_OPERATOR_MESSAGE = (
    "{company}\n"
    "Ваш запрос передан оператору. Ожидайте ответа.\n"
    "Чтобы вернуться в меню, напишите «меню»."
)

DEFAULT_CHATBOT_OPERATOR_NOTIFY = (
    "Запрос оператора от клиента {client_name} ({phone}).\n"
    "Последнее сообщение: {last_message}"
)

DEFAULT_CHATBOT_SELECT_SERVICE = (
    "Выберите услугу (ответьте цифрой):\n\n"
    "{services_menu}\n\n"
    "0 — в меню"
)

DEFAULT_CHATBOT_SELECT_DATE = (
    "Укажите дату записи в формате ДД.ММ.ГГГГ\n"
    "(например 10.06.2026).\n\n"
    "0 — в меню"
)

DEFAULT_CHATBOT_SELECT_TIME = (
    "Свободное время на {date}:\n\n"
    "{slots_menu}\n\n"
    "0 — в меню"
)

DEFAULT_CHATBOT_CONFIRM = (
    "Подтвердите запись:\n"
    "Услуга: {service_name}\n"
    "Цена: {price} {currency}\n"
    "Дата: {date}\n"
    "Время: {time}\n\n"
    "Ответьте ДА для подтверждения или НЕТ для отмены."
)

DEFAULT_CHATBOT_SUCCESS = (
    "{company}\n"
    "Запись создана! Заказ #{order_number}.\n"
    "Ссылка для отслеживания: {order_link}\n\n"
    "{contacts}"
)

DEFAULT_CHATBOT_NO_SLOTS = (
    "На выбранную дату нет свободных слотов.\n"
    "Укажите другую дату (ДД.ММ.ГГГГ) или 0 — в меню."
)

DEFAULT_CHATBOT_ERROR = (
    "Не удалось создать запись: {error}\n"
    "Попробуйте снова или напишите «меню»."
)
