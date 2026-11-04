"""User-facing strings in Russian and Uzbek."""

from __future__ import annotations

from .language import RU, UZ


def t(language: str, ru: str, uz: str) -> str:
    return uz if language == UZ else ru


BUSY = {
    RU: "⏳ Я ещё считаю предыдущий вопрос. Подождите пару секунд, пожалуйста.",
    UZ: "⏳ Oldingi savolga hali javob hisoblayapman. Bir necha soniya kuting, iltimos.",
}

TOO_LONG = {
    RU: "Слишком длинный вопрос. Сформулируйте его короче (до 2000 символов).",
    UZ: "Savol juda uzun. Iltimos, qisqaroq yozing (2000 belgidan oshmasin).",
}

EMPTY = {
    RU: "Напишите вопрос о сделках, контрактах, компаниях, брокерах или курсе доллара.",
    UZ: "Bitimlar, shartnomalar, kompaniyalar, brokerlar yoki dollar kursi haqida savol yozing.",
}

TIMEOUT = {
    RU: "⏱ Не успел посчитать за отведённое время. Попробуйте переформулировать вопрос или сузить период.",
    UZ: "⏱ Belgilangan vaqt ichida hisoblab ulgurmadim. Savolni qisqartirib yoki davrni toraytirib ko‘ring.",
}

SERVICE_UNAVAILABLE = {
    RU: "⚠️ Сервис данных временно недоступен. Попробуйте через минуту.",
    UZ: "⚠️ Maʼlumotlar xizmati vaqtincha ishlamayapti. Bir daqiqadan so‘ng urinib ko‘ring.",
}

LLM_UNAVAILABLE = {
    RU: "⚠️ Не удалось получить ответ от языковой модели. Попробуйте через минуту.",
    UZ: "⚠️ Til modelidan javob olib bo‘lmadi. Bir daqiqadan so‘ng urinib ko‘ring.",
}

GENERIC_ERROR = {
    RU: "⚠️ Не смог обработать вопрос. Попробуйте переформулировать его.",
    UZ: "⚠️ Savolni qayta ishlay olmadim. Iltimos, boshqacha yozib ko‘ring.",
}

START = {
    RU: (
        "👋 <b>Здравствуйте!</b>\n\n"
        "Я агент по реестру сделок UZEX Spot. Отвечаю только по данным реестра: "
        "500 000 сделок с 03.01.2022 по 30.10.2026, контракты, компании, брокеры и курс USD.\n\n"
        "<b>Что умею</b>\n"
        "• считать сделки, суммы, объёмы и средние цены;\n"
        "• находить сделки, контракты, компании по ИНН и брокеров;\n"
        "• сравнивать годы, регионы, товары и формы контрактов;\n"
        "• пересчитывать экспортные суммы USD → UZS по курсу на дату сделки.\n\n"
        "<b>Примеры</b>\n"
        "• Сколько всего сделок заключено в 2024 году?\n"
        "• Какая компания продала на наибольшую сумму в 2025?\n"
        "• Найди сделку №185158 — кто продавец и покупатель?\n"
        "• Средняя цена за тонну каустической соды в 2023?\n\n"
        "Если ответа в данных нет, я скажу об этом прямо — выдумывать не буду.\n"
        "Язык ответа определяется по вашему вопросу (RU / UZ)."
    ),
    UZ: (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men UZEX Spot bitimlar reyestri bo‘yicha agentman. Faqat reyestr maʼlumotlari asosida javob beraman: "
        "03.01.2022–30.10.2026 davridagi 500 000 bitim, shartnomalar, kompaniyalar, brokerlar va USD kursi.\n\n"
        "<b>Nimalarni qila olaman</b>\n"
        "• bitimlar, summalar, hajmlar va o‘rtacha narxlarni hisoblash;\n"
        "• bitim, shartnoma, kompaniya (STIR bo‘yicha) va brokerni topish;\n"
        "• yillar, hududlar, tovarlar va shartnoma shakllarini taqqoslash;\n"
        "• eksport summalarini bitim sanasidagi kurs bo‘yicha USD → UZS ga o‘tkazish.\n\n"
        "<b>Misol savollar</b>\n"
        "• 2024-yilda jami nechta bitim tuzilgan?\n"
        "• 2025-yilda eng katta summaga sotgan kompaniya qaysi?\n"
        "• 185158-raqamli bitimni top — sotuvchi va xaridor kim?\n"
        "• 2023-yilda kaustik soda tonnasi o‘rtacha narxi?\n\n"
        "Agar maʼlumotlarda javob bo‘lmasa, buni ochiq aytaman — o‘ylab topmayman.\n"
        "Javob tili savolingiz tiliga mos bo‘ladi (RU / UZ)."
    ),
}

HELP = {
    RU: (
        "<b>Как спрашивать</b>\n"
        "Пишите обычным языком — SQL знать не нужно. Указывайте период, товар, компанию, "
        "регион или форму контракта, если это важно.\n\n"
        "<b>Примеры</b>\n"
        "• Сколько сделок аннулировано из-за неоплаты в 2025?\n"
        "• Через какого брокера прошло больше всего сделок?\n"
        "• Сумма экспортных сделок в долларах в 2024?\n"
        "• Какие товары продаёт компания с ИНН 986932945?\n"
        "• Самая дорогая сделка 2026 года в пересчёте на сумы?\n\n"
        "<b>Важно</b>\n"
        "• Данные вымышленные и охватывают 03.01.2022–30.10.2026.\n"
        "• Если в реестре нет ответа, бот скажет: «В данных реестра ответа на этот вопрос нет».\n"
        "• Каждый ответ содержит блок «Основание» с фильтрами и идентификаторами.\n"
        "• Один вопрос обрабатывается до 75 секунд; обычно 5–25 секунд.\n\n"
        "Команды: /start, /help, /lang ru|uz|auto, /reset"
    ),
    UZ: (
        "<b>Qanday so‘rash kerak</b>\n"
        "Oddiy tilda yozing — SQL bilish shart emas. Davr, tovar, kompaniya, hudud yoki "
        "shartnoma shaklini ko‘rsatsangiz, javob aniqroq bo‘ladi.\n\n"
        "<b>Misol savollar</b>\n"
        "• 2025-yilda to‘lanmaganligi uchun nechta bitim bekor qilingan?\n"
        "• Eng ko‘p bitim qaysi broker orqali o‘tgan?\n"
        "• 2024-yilda eksport bitimlari dollarda qancha?\n"
        "• STIR 986932945 bo‘lgan kompaniya qanday tovarlar sotadi?\n"
        "• 2026-yil eng qimmat bitim so‘mda qancha?\n\n"
        "<b>Muhim</b>\n"
        "• Maʼlumotlar o‘ylab topilgan va 03.01.2022–30.10.2026 davrini qamraydi.\n"
        "• Reyestrda javob bo‘lmasa, bot «Maʼlumotlar reyestrida bu savolga javob yo‘q» deb aytadi.\n"
        "• Har bir javobda filtrlar va identifikatorlar ko‘rsatilgan «Asos» bloki bor.\n"
        "• Bitta savol 75 soniyagacha ishlanadi; odatda 5–25 soniya.\n\n"
        "Buyruqlar: /start, /help, /lang ru|uz|auto, /reset"
    ),
}

RESET = {
    RU: "🧹 Контекст диалога очищен. Задайте новый вопрос.",
    UZ: "🧹 Suhbat konteksti tozalandi. Yangi savol bering.",
}

LANG_SET = {
    RU: "✅ Язык ответов: русский.",
    UZ: "✅ Javob tili: o‘zbekcha.",
}

LANG_AUTO = {
    RU: "✅ Язык ответов: автоматически по тексту вопроса.",
    UZ: "✅ Javob tili: savol matniga qarab avtomatik.",
}

LANG_PROMPT = {
    RU: "Выберите язык ответов. Можно также написать /lang ru, /lang uz или /lang auto.",
    UZ: "Javob tilini tanlang. /lang ru, /lang uz yoki /lang auto buyrug‘ini ham yozishingiz mumkin.",
}

LANG_UNKNOWN = {
    RU: "Не понял язык. Используйте /lang ru, /lang uz или /lang auto.",
    UZ: "Tilni tushunmadim. /lang ru, /lang uz yoki /lang auto dan foydalaning.",
}

HEALTH_DENIED = {
    RU: "Команда доступна только администратору.",
    UZ: "Bu buyruq faqat administrator uchun.",
}
