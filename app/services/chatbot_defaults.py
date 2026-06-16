"""Default chatbot message templates."""

DEFAULT_CHATBOT_WELCOME = (
    "{company}\n"
    "Xoş gəldiniz!\n\n"
    "{menu_lines}\n\n"
    "Rəqəm ilə cavab verin və ya sorğunuzu yazın."
)

DEFAULT_CHATBOT_OPERATOR_UNAVAILABLE = (
    "{company}\n"
    "Operatorla əlaqə hazırda mövcud deyil.\n\n"
    "{menu_lines}"
)

DEFAULT_MENU_INFO = "Məlumat"
DEFAULT_MENU_BOOKING = "Yazı"
DEFAULT_MENU_OPERATOR = "Operatorla əlaqə"

DEFAULT_CHATBOT_OPERATOR_MESSAGE = (
    "{company}\n"
    "Sorğunuz operatora ötürüldü. Cavab gözləyin.\n"
    "Menyuya qayıtmaq üçün «menyu» yazın."
)

DEFAULT_CHATBOT_OPERATOR_NOTIFY = (
    "{client_name} ({phone}) müştərisindən operator sorğusu.\n"
    "Son mesaj: {last_message}"
)

DEFAULT_CHATBOT_SELECT_SERVICE = (
    "Xidmət seçin (rəqəmlə cavab verin):\n\n"
    "{services_menu}\n\n"
    "0 — menyuya"
)

DEFAULT_CHATBOT_SELECT_DATE = (
    "Yazı tarixini dd.mm.yyyy formatında göstərin\n"
    "(məsələn 10.06.2026).\n\n"
    "0 — menyuya"
)

DEFAULT_CHATBOT_SELECT_TIME = (
    "{date} tarixi üçün boş vaxtlar:\n\n"
    "{slots_menu}\n\n"
    "0 — menyuya"
)

DEFAULT_CHATBOT_CONFIRM = (
    "Yazını təsdiqləyin:\n"
    "Xidmət: {service_name}\n"
    "Qiymət: {price} {currency}\n"
    "Tarix: {date}\n"
    "Vaxt: {time}\n\n"
    "Təsdiqləmək üçün BƏLİ, ləğv etmək üçün XEYR yazın."
)

DEFAULT_CHATBOT_SUCCESS = (
    "{company}\n"
    "Yazı yaradıldı! Sifariş #{order_number}.\n"
    "İzləmə linki: {order_link}\n\n"
    "{contacts}"
)

DEFAULT_CHATBOT_NO_SLOTS = (
    "Seçilmiş tarixə boş slot yoxdur.\n"
    "Başqa tarix göstərin (dd.mm.yyyy) və ya 0 — menyuya."
)

DEFAULT_CHATBOT_ERROR = (
    "Yazı yaradıla bilmədi: {error}\n"
    "Yenidən cəhd edin və ya «menyu» yazın."
)
