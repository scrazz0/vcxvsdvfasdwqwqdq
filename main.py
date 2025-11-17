import logging
import re
import sqlite3
import datetime
import uuid
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.error import TelegramError

# --- ИМПОРТ ИЗ ДРУГИХ ФАЙЛОВ ПРОЕКТА ---
from config import BOT_TOKEN, ADMIN_IDS, SOURCE_CHANNEL_ID
from payment_gateways import generate_mono_card_invoice, generate_mono_parts_invoice
from currency_converter import get_usd_to_uah_rate
from db import init_db, db_query # Используем функции из db.py

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И СОСТОЯНИЯ ДИАЛОГА ---
(
    MAIN_MENU, LANGUAGE_SELECTION, MODEL_SEARCH,
    ADMIN_PANEL, ADMIN_STATS, ADMIN_CATEGORIES, ADMIN_PRODUCTS,
    ADMIN_ADD_CATEGORY_NAME, ADMIN_DEL_CATEGORY, ADMIN_ADD_PRODUCT_STEP1_CAT,
    ADMIN_ADD_PRODUCT_STEP2_NAME, ADMIN_ADD_PRODUCT_STEP3_DESC, ADMIN_ADD_PRODUCT_STEP4_PRICE,
    ADMIN_ADD_PRODUCT_STEP5_MEDIA, ADMIN_DEL_PRODUCT, ADMIN_POSTING_STEP1_TEXT,
    ADMIN_POSTING_STEP2_MEDIA, ADMIN_POSTING_STEP3_BTN_TEXT, ADMIN_POSTING_STEP4_BTN_URL,
    FILTER_MENU, SET_MIN_PRICE, SET_MAX_PRICE,
    # === НОВЫЕ СОСТОЯНИЯ ДЛЯ СБОРА ДАННЫХ О ЗАКАЗЕ ===
    GET_PHONE, GET_NAME, GET_CITY, GET_NOVAPOSHTA
) = range(26)

products_cache = {}
product_details_cache = {}
user_languages = {}

# --- МУЛЬТИЯЗЫЧНОСТЬ (с новыми строками) ---
translations = {
    "ru": {
        "welcome": "Привет! Я бот для продажи техники Apple. Чем могу помочь?",
        "catalog": "Каталог 🗂️",
        "find_model": "Найти модель 🔎",
        "change_language": "Сменить язык 🌐",
        "filters": "Фильтры ⚙️",
        "support": "Тех. поддержка 🤝",
        "choose_category": "Выберите категорию:",
        "choose_language": "Пожалуйста, выберите язык:",
        "language_changed": "Язык изменен на русский.",
        "enter_model_name": "Введите название модели, которую вы ищете:",
        "model_not_found": "К сожалению, такая модель не найдена.",
        "model_found": "Найдены следующие модели:",
        "buy": "Купить 🛒",
        "price": "Цена",
        "no_access": "У вас нет доступа к этой команде.",
        "no_products_in_category": "В этой категории пока нет товаров.",
        "use_buttons": "Пожалуйста, используйте кнопки ниже для навигации.",
        "new_order_for_admin": "👇 Новый заказ! 👇",
        "user": "Пользователь",
        "support_message": "Для связи с технической поддержкой, пожалуйста, нажмите на кнопку ниже:",
        "contact_support": "Связаться с поддержкой",
        # Оплата
        "choose_payment_method": "Отлично! Теперь выберите удобный способ оплаты:",
        "payment_cash": "Наличными (при самовывозе)",
        "payment_cashless": "Безналичный расчет",
        "payment_cod": "Наложенный платеж (Новая Почта)",
        "payment_mono_card": "Оплата картой MonoBank",
        "payment_mono_parts": "Покупка частями (Monobank)",
        "order_created": "Ваш заказ создан. Для завершения, пожалуйста, нажмите на кнопку ниже и произведите оплату.",
        "order_offline_created": "Спасибо за ваш заказ! Менеджер скоро свяжется с вами для подтверждения и уточнения деталей.",
        "payment_error": "К сожалению, не удалось создать счет для этого способа оплаты. Пожалуйста, попробуйте другой способ или свяжитесь с поддержкой.",
        "price_not_set": "Извините, у этого товара не указана цена. Обратитесь к менеджеру для уточнения.",
        "go_to_payment": "Перейти к оплате 💳",
        # Filters
        "filter_menu_title": "Настройте фильтры для поиска:",
        "set_min_price": "Цена от",
        "set_max_price": "Цена до",
        "apply_filters": "✅ Применить и показать",
        "reset_filters": "Сбросить 🗑️",
        "back_to_main": "⬅️ В главное меню",
        "enter_min_price": "Введите минимальную цену (только цифры):",
        "enter_max_price": "Введите максимальную цену (только цифры):",
        "price_set": "Цена установлена.",
        "filters_applied": "Результаты по вашим фильтрам:",
        "no_results_filters": "По вашим фильтрам ничего не найдено.",
        "choose_currency": "Валюта",
        "currency_set_to": "Валюта для фильтра изменена на: {}",
        "currency_rate_error": "Не удалось получить курс валют для расчета. Попробуйте позже или выберите UAH.",
        # === НОВЫЕ СТРОКИ ДЛЯ СБОРА ДАННЫХ ===
        "ask_phone": "Для оформления заказа, пожалуйста, введите ваш номер телефона:",
        "ask_name": "Спасибо! Теперь введите ваше ФИО:",
        "ask_city": "Отлично! Введите город доставки:",
        "ask_novaposhta": "И последний шаг: укажите номер отделения Новой Почты:",
        "invalid_phone": "Некорректный формат телефона. Пожалуйста, введите номер в формате +380xxxxxxxxx или 0xxxxxxxxx.",
        "order_details_for_admin": "👤 <b>Данные клиента:</b>\n<b>Имя:</b> {name}\n<b>Телефон:</b> {phone}\n<b>Город:</b> {city}\n<b>Отделение НП:</b> {address}",
        # Admin Panel (остается на русском для удобства админов)
        "admin_welcome": "👑 Добро пожаловать в админ-панель!\n\nДля импорта старых постов из канала используйте команду /sync.",
        "admin_back": "⬅️ Назад",
        "admin_stats": "Статистика 📊",
        "admin_categories": "Категории 🗂️",
        "admin_products": "Товары 📱",
        "admin_posting": "Постинг в канал 📢",
        "stats_title": "📊 Статистика пользователей:",
        "stats_total": "Всего:",
        "stats_today": "За сегодня:",
        "stats_week": "За неделю:",
        "stats_month": "За месяц:",
        "cat_manage": "Управление категориями:",
        "cat_add": "Добавить категорию",
        "cat_del": "Удалить категорию",
        "cat_enter_name": "Введите название новой категории:",
        "cat_added": "✅ Категория '{}' добавлена.",
        "cat_exists": "⚠️ Категория с таким названием уже существует.",
        "cat_choose_del": "Выберите категорию для удаления:",
        "cat_deleted": "❌ Категория '{}' и все товары в ней удалены.",
        "cat_not_found": "Категория не найдена.",
        "prod_manage": "Управление товарами:",
        "prod_add": "Добавить товар",
        "prod_del": "Удалить товар",
        "prod_choose_cat_for_add": "Выберите категорию для нового товара:",
        "prod_enter_name": "Теперь введите название товара:",
        "prod_enter_desc": "Отлично. Теперь введите описание товара:",
        "prod_enter_price": "Введите цену (например: `35000 грн` или `999$`). Валюта будет определена автоматически. Если цена по запросу, напишите 'По запросу'.",
        "prod_send_media": "Последний шаг. Отправьте фото или видео для товара:",
        "prod_added": "✅ Товар '{}' успешно добавлен.",
        "prod_exists": "⚠️ Товар с таким названием уже существует.",
        "prod_choose_del": "Выберите товар для удаления:",
        "prod_deleted": "❌ Товар '{}' удален.",
        "post_enter_text": "Введите текст для поста в канале:",
        "post_send_media": "Теперь отправьте фото (постинг видео не поддерживается в этом режиме).",
        "post_enter_btn_text": "Введите текст для кнопки под постом (например, 'Купить'):",
        "post_enter_btn_url": "Отправьте полную ссылку для кнопки (например, https://t.me/your_bot):",
        "post_success": "✅ Пост успешно опубликован в канале!",
        "post_fail": "❌ Не удалось опубликовать пост.",
        "post_fail_chat_not_found": "\n\n<b>Причина:</b> Чат не найден.\n<b>Решение:</b>\n1. Убедитесь, что `SOURCE_CHANNEL_ID` в `config.py` указан верно (должен начинаться с `-100...`).\n2. Убедитесь, что бот добавлен в канал как администратор с правом публикации постов.",
        "sync_command_info": """⚙️ <b>Импорт существующих товаров из канала</b> (инфо для админа)""",
    },
    "ua": {
        "welcome": "Вітаю! Я бот для продажу техніки Apple. Чим можу допомогти?",
        "catalog": "Каталог 🗂️",
        "find_model": "Знайти модель 🔎",
        "change_language": "Змінити мову 🌐",
        "filters": "Фільтри ⚙️",
        "support": "Тех. підтримка 🤝",
        "choose_category": "Оберіть категорію:",
        "choose_language": "Будь ласка, оберіть мову:",
        "language_changed": "Мову змінено на українську.",
        "enter_model_name": "Введіть назву моделі, яку ви шукаєте:",
        "model_not_found": "На жаль, таку модель не знайдено.",
        "model_found": "Знайдено наступні моделі:",
        "buy": "Купити 🛒",
        "price": "Ціна",
        "no_access": "У вас немає доступу до цієї команди.",
        "no_products_in_category": "У цій категорії поки що немає товарів.",
        "use_buttons": "Будь ласка, використовуйте кнопки нижче для навігації.",
        "new_order_for_admin": "👇 Нове замовлення! 👇",
        "user": "Користувач",
        "support_message": "Для зв'язку з технічною підтримкою, будь ласка, натисніть на кнопку нижче:",
        "contact_support": "Зв'язатися з підтримкою",
        # Оплата
        "choose_payment_method": "Чудово! Тепер оберіть зручний спосіб оплати:",
        "payment_cash": "Готівкою (при самовивозі)",
        "payment_cashless": "Безготівковий розрахунок",
        "payment_cod": "Післяплата (Нова Пошта)",
        "payment_mono_card": "Оплата карткою MonoBank",
        "payment_mono_parts": "Покупка частинами (Monobank)",
        "order_created": "Ваше замовлення створено. Для завершення, будь ласка, натисніть на кнопку нижче та здійсніть оплату.",
        "order_offline_created": "Дякуємо за ваше замовлення! Менеджер скоро зв'яжеться з вами для підтвердження та уточнення деталей.",
        "payment_error": "На жаль, не вдалося створити рахунок для цього способу оплати. Будь ласка, спробуйте інший спосіб або зв'яжіться з підтримкою.",
        "price_not_set": "Вибачте, у цього товару не вказана ціна. Зверніться до менеджера для уточнення.",
        "go_to_payment": "Перейти до оплати 💳",
        # Filters
        "filter_menu_title": "Налаштуйте фільтри для пошуку:",
        "set_min_price": "Ціна від",
        "set_max_price": "Ціна до",
        "apply_filters": "✅ Застосувати та показати",
        "reset_filters": "Скинути 🗑️",
        "back_to_main": "⬅️ В головне меню",
        "enter_min_price": "Введіть мінімальну ціну (тільки цифри):",
        "enter_max_price": "Введіть максимальну ціну (тільки цифри):",
        "price_set": "Ціну встановлено.",
        "filters_applied": "Результати за вашими фільтрами:",
        "no_results_filters": "За вашими фільтрами нічого не знайдено.",
        "choose_currency": "Валюта",
        "currency_set_to": "Валюту для фільтра змінено на: {}",
        "currency_rate_error": "Не вдалося отримати курс валют для розрахунку. Спробуйте пізніше або оберіть UAH.",
        # === НОВЫЕ СТРОКИ ДЛЯ СБОРА ДАННЫХ ===
        "ask_phone": "Для оформлення замовлення, будь ласка, введіть ваш номер телефону:",
        "ask_name": "Дякую! Тепер введіть ваше ПІБ:",
        "ask_city": "Чудово! Введіть місто доставки:",
        "ask_novaposhta": "І останній крок: вкажіть номер відділення Нової Пошти:",
        "invalid_phone": "Некоректний формат телефону. Будь ласка, введіть номер у форматі +380xxxxxxxxx або 0xxxxxxxxx.",
        "order_details_for_admin": "👤 <b>Дані клієнта:</b>\n<b>Ім'я:</b> {name}\n<b>Телефон:</b> {phone}\n<b>Місто:</b> {city}\n<b>Відділення НП:</b> {address}",
        # Admin Panel (остается на русском для удобства админов)
        "admin_welcome": "👑 Добро пожаловать в админ-панель!\n\nДля импорта старых постов из канала используйте команду /sync.",
        "admin_back": "⬅️ Назад",
        "admin_stats": "Статистика 📊",
        "admin_categories": "Категории 🗂️",
        "admin_products": "Товары 📱",
        "admin_posting": "Постинг в канал 📢",
        "stats_title": "📊 Статистика пользователей:",
        "stats_total": "Всего:",
        "stats_today": "За сегодня:",
        "stats_week": "За неделю:",
        "stats_month": "За месяц:",
        "cat_manage": "Управление категориями:",
        "cat_add": "Добавить категорию",
        "cat_del": "Удалить категорию",
        "cat_enter_name": "Введите название новой категории:",
        "cat_added": "✅ Категория '{}' добавлена.",
        "cat_exists": "⚠️ Категория с таким названием уже существует.",
        "cat_choose_del": "Выберите категорию для удаления:",
        "cat_deleted": "❌ Категория '{}' и все товары в ней удалены.",
        "cat_not_found": "Категория не найдена.",
        "prod_manage": "Управление товарами:",
        "prod_add": "Добавить товар",
        "prod_del": "Удалить товар",
        "prod_choose_cat_for_add": "Выберите категорию для нового товара:",
        "prod_enter_name": "Теперь введите название товара:",
        "prod_enter_desc": "Отлично. Теперь введите описание товара:",
        "prod_enter_price": "Введите цену (например: `35000 грн` или `999$`). Валюта будет определена автоматически. Если цена по запросу, напишите 'По запросу'.",
        "prod_send_media": "Последний шаг. Отправьте фото или видео для товара:",
        "prod_added": "✅ Товар '{}' успешно добавлен.",
        "prod_exists": "⚠️ Товар с таким названием уже существует.",
        "prod_choose_del": "Выберите товар для удаления:",
        "prod_deleted": "❌ Товар '{}' удален.",
        "post_enter_text": "Введите текст для поста в канале:",
        "post_send_media": "Теперь отправьте фото (постинг видео не поддерживается в этом режиме).",
        "post_enter_btn_text": "Введите текст для кнопки под постом (например, 'Купить'):",
        "post_enter_btn_url": "Отправьте полную ссылку для кнопки (например, https://t.me/your_bot):",
        "post_success": "✅ Пост успешно опубликован в канале!",
        "post_fail": "❌ Не удалось опубликовать пост.",
        "post_fail_chat_not_found": "\n\n<b>Причина:</b> Чат не найден.\n<b>Решение:</b>\n1. Убедитесь, что `SOURCE_CHANNEL_ID` в `config.py` указан верно (должен начинаться с `-100...`).\n2. Убедитесь, что бот добавлен в канал как администратор с правом публикации постов.",
        "sync_command_info": """⚙️ <b>Імпорт існуючих товарів з каналу</b> (інфо для адміна)""",
    }
}

def get_text(key, user_id):
    lang = user_languages.get(user_id, "ua")
    return translations.get(lang, translations["ua"]).get(key) or translations["ru"].get(key, f"_{key}_")

def l10n_regex(key, lang_codes=['ru', 'ua']):
    parts = [translations[lang].get(key, "") for lang in lang_codes]
    cleaned_parts = [re.sub(r'\(.*\)', '', part).strip() for part in parts]
    return f"^({ '|'.join(filter(None, cleaned_parts)) })$"

# --- ХЕЛПЕРЫ ДЛЯ РАБОТЫ С БД ---
def load_data_from_db():
    global products_cache, product_details_cache
    products_cache.clear()
    product_details_cache.clear()
    all_products = db_query("SELECT id, name, description, price, price_numeric, photo_id, video_id, category_name FROM products", fetchall=True)
    for p in all_products:
        prod_id, name, desc, price, price_num, photo, video, cat = p
        products_cache.setdefault(cat, []).append((prod_id, name))
        product_details_cache[prod_id] = {
            "name": name, "description": desc, "price": price,
            "price_numeric": price_num, "photo": photo, "video": video
        }
    logger.info(f"Данные из БД загружены в кэш. Товаров: {len(product_details_cache)}, Категорий: {len(products_cache)}")


# --- ЛОГИКА ПАРСИНГА ЦЕНЫ ---
def process_price_string(text_with_price: str) -> tuple[str, int | None, str]:
    price_pattern = re.compile(
        r'Цена\s*[:\-]*\s*([\d\s.,]+)\s*?(\$|usd|eur|€|грн|uah|руб|rub)|'
        r'([\d\s.,]+)\s*?(\$|usd|eur|€|грн|uah|руб|rub)',
        re.IGNORECASE | re.UNICODE
    )
    price_display = "По запросу"
    price_numeric = None
    cleaned_text = text_with_price
    match = price_pattern.search(text_with_price)
    if match:
        if match.group(1):
            price_str = match.group(1)
            currency = match.group(2).lower() if match.group(2) else ''
        else:
            price_str = match.group(3)
            currency = match.group(4).lower() if match.group(4) else ''

        price_value = float(re.sub(r'[^\d.]', '', price_str.replace(',', '.')))
        
        currency_symbol = currency.replace('usd','$').replace('eur', '€').replace('грн', 'UAH').replace('uah', 'UAH').upper()
        price_display = f"{int(price_value) if price_value.is_integer() else price_value} {currency_symbol}"

        if currency in ['$', 'usd']:
            usd_rate = get_usd_to_uah_rate()
            if usd_rate:
                price_numeric = int(price_value * usd_rate * 100)
                logger.info(f"Конвертация: {price_value}$ * {usd_rate} = {price_numeric / 100} UAH")
            else:
                logger.warning("Не удалось получить курс USD, цена не будет установлена.")
        elif currency in ['грн', 'uah']:
            price_numeric = int(price_value * 100)
        
        lines = text_with_price.splitlines()
        cleaned_lines = [line for line in lines if not price_pattern.search(line)]
        cleaned_text = "\n".join(cleaned_lines).strip()

    return price_display, price_numeric, cleaned_text

# --- ОСНОВНЫЕ ФУНКЦИИ БОТА ---
def get_main_keyboard(user_id):
    keyboard = [
        [KeyboardButton(get_text("catalog", user_id)), KeyboardButton(get_text("find_model", user_id))],
        [KeyboardButton(get_text("filters", user_id)), KeyboardButton(get_text("support", user_id))],
        [KeyboardButton(get_text("change_language", user_id))],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_languages.setdefault(user.id, "ua")
    db_query("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date) VALUES (?, ?, ?, ?)",
             (user.id, user.username, user.first_name, datetime.datetime.now().isoformat()), commit=True)
    await update.message.reply_text(get_text("welcome", user.id), reply_markup=get_main_keyboard(user.id))
    return MAIN_MENU

# --- ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ---
async def catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    categories = db_query("SELECT name FROM categories", fetchall=True)
    keyboard = [[InlineKeyboardButton(cat['name'], callback_data=f"cat_{cat['name']}")] for cat in categories]
    await update.message.reply_text(get_text("choose_category", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU

async def change_language_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("Українська 🇺🇦", callback_data="lang_ua")],
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")]
    ]
    await update.message.reply_text(get_text("choose_language", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    return LANGUAGE_SELECTION

async def search_model_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("enter_model_name", update.effective_user.id))
    return MODEL_SEARCH

async def main_menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("use_buttons", update.effective_user.id))
    return MAIN_MENU

async def show_support_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text=get_text("contact_support", user_id),
            url="https://t.me/ReSeller_Group_Sale" # Замените на ваш контакт
        )]
    ])
    await update.message.reply_text(
        text=get_text("support_message", user_id),
        reply_markup=keyboard
    )
    return

# --- ОБРАБОТЧИКИ ДРУГИХ СОСТОЯНИЙ ---
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang_code = query.data.split("_")[1]
    user_languages[user_id] = lang_code
    
    lang_changed_text = "Язык изменен на русский." if lang_code == "ru" else "Мову змінено на українську."
    
    await query.edit_message_text(lang_changed_text)
    await context.bot.send_message(
        chat_id=user_id,
        text=get_text("welcome", user_id),
        reply_markup=get_main_keyboard(user_id)
    )
    return MAIN_MENU

# --- ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ КАТАЛОГА ---
async def catalog_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("cat_"):
        category = data.split("_", 1)[1]
        products_in_cat = products_cache.get(category, [])
        if products_in_cat:
            keyboard = [[InlineKeyboardButton(name, callback_data=f"prod_{prod_id}")] for prod_id, name in products_in_cat]
            await query.edit_message_text(text=f"{get_text('choose_category', user_id)}: {category}", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(text=get_text("no_products_in_category", user_id))

    elif data.startswith("prod_"):
        product_id = int(data.replace("prod_", "", 1))
        details = product_details_cache.get(product_id)
        if details:
            caption_parts = [
                f"<b>{details['name']}</b>",
                details['description'],
                f"<b>{get_text('price', user_id)}: {details['price']}</b>"
            ]
            caption = "\n\n".join(filter(None, caption_parts))
            keyboard = [[InlineKeyboardButton(get_text("buy", user_id), callback_data=f"buy_{product_id}")]]
            
            try:
                await query.delete_message()
            except TelegramError as e:
                logger.warning(f"Не удалось удалить сообщение при показе товара: {e}")

            try:
                if details.get("photo"):
                    await context.bot.send_photo(chat_id=user_id, photo=details["photo"], caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
                elif details.get("video"):
                    await context.bot.send_video(chat_id=user_id, video=details["video"], caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
                else:
                    await context.bot.send_message(chat_id=user_id, text=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except TelegramError as e:
                logger.error(f"Ошибка отправки карточки товара ID {product_id}: {e}")
                await context.bot.send_message(chat_id=user_id, text=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("buy_"):
        product_id = int(data.replace("buy_", "", 1))
        details = product_details_cache.get(product_id)
        
        if not details or not details.get("price_numeric"):
            await context.bot.send_message(user_id, get_text("price_not_set", user_id))
            return

        order_id = str(uuid.uuid4())
        amount = details["price_numeric"]
        db_query(
            "INSERT INTO orders (id, user_id, product_id, amount, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, user_id, product_id, amount, datetime.datetime.now().isoformat()),
            commit=True
        )

        keyboard = get_payment_keyboard(user_id, order_id)
        if query.message.reply_markup:
            await query.edit_message_reply_markup(reply_markup=None) 
        await context.bot.send_message(chat_id=user_id, text=get_text("choose_payment_method", user_id), reply_markup=keyboard)

def get_payment_keyboard(user_id: int, order_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(get_text("payment_mono_card", user_id), callback_data=f"pay_monocard_{order_id}")],
        [InlineKeyboardButton(get_text("payment_mono_parts", user_id), callback_data=f"pay_monoparts_{order_id}")],
        [InlineKeyboardButton(get_text("payment_cod", user_id), callback_data=f"pay_cod_{order_id}")],
        [InlineKeyboardButton(get_text("payment_cash", user_id), callback_data=f"pay_cash_{order_id}")],
        [InlineKeyboardButton(get_text("payment_cashless", user_id), callback_data=f"pay_cashless_{order_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)

# === НОВЫЙ БЛОК: СБОР ДАННЫХ И ОФОРМЛЕНИЕ ЗАКАЗА ===

async def start_checkout_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс сбора данных после выбора способа оплаты."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    parts = query.data.split('_')
    payment_system = parts[1]
    order_id = parts[2]
    
    context.user_data['order_info'] = {
        'order_id': order_id,
        'payment_system': payment_system
    }

    db_query("UPDATE orders SET payment_method = ? WHERE id = ?", (payment_system, order_id), commit=True)
    
    await query.edit_message_reply_markup(reply_markup=None)
    
    await context.bot.send_message(chat_id=user_id, text=get_text("ask_phone", user_id))
    return GET_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает и проверяет номер телефона."""
    user_id = update.effective_user.id
    phone = update.message.text
    # Проверка на украинский номер телефона
    if not re.match(r'^(\+380\d{9}|0\d{9})$', phone):
        await update.message.reply_text(get_text("invalid_phone", user_id))
        return GET_PHONE
    
    context.user_data['customer_info'] = {'phone': phone}
    await update.message.reply_text(get_text("ask_name", user_id))
    return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает ФИО."""
    user_id = update.effective_user.id
    context.user_data['customer_info']['name'] = update.message.text
    await update.message.reply_text(get_text("ask_city", user_id))
    return GET_CITY

async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает город."""
    user_id = update.effective_user.id
    context.user_data['customer_info']['city'] = update.message.text
    await update.message.reply_text(get_text("ask_novaposhta", user_id))
    return GET_NOVAPOSHTA

async def get_novaposhta_and_finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает отделение НП и завершает заказ."""
    user_id = update.effective_user.id
    context.user_data['customer_info']['address'] = update.message.text

    order_info = context.user_data.get('order_info', {})
    customer_info = context.user_data.get('customer_info', {})
    order_id = order_info.get('order_id')
    payment_system = order_info.get('payment_system')

    if not all([order_id, payment_system, customer_info]):
        logger.warning(f"Недостаточно данных для завершения заказа для user_id: {user_id}")
        await update.message.reply_text("Произошла ошибка, попробуйте начать сначала.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
        
    db_query(
        """UPDATE orders 
           SET customer_phone = ?, customer_name = ?, customer_city = ?, customer_address = ?
           WHERE id = ?""",
        (customer_info['phone'], customer_info['name'], customer_info['city'], customer_info['address'], order_id),
        commit=True
    )

    order_data = db_query("SELECT product_id, amount FROM orders WHERE id = ?", (order_id,), fetchone=True)
    if not order_data:
        await update.message.reply_text("❌ Ошибка: заказ не найден.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
        
    product_id, amount = order_data['product_id'], order_data['amount']
    product_name = product_details_cache.get(product_id, {}).get("name", f"ID: {product_id}")

    await notify_admin_of_new_order(context, order_id, payment_system, product_name, customer_info)

    payment_url = None
    if payment_system in ['monocard', 'monoparts']:
        invoice_data = None
        if payment_system == 'monocard':
            invoice_data = generate_mono_card_invoice(order_id, amount, f"Оплата за: {product_name}")
        elif payment_system == 'monoparts':
            invoice_data = generate_mono_parts_invoice(order_id, amount, f"Покупка частинами: {product_name}")
        
        if invoice_data and invoice_data.get("url"):
            payment_url = invoice_data["url"]
            db_query("UPDATE orders SET payment_invoice_id = ? WHERE id = ?", (invoice_data["invoice_id"], order_id), commit=True)
            
            keyboard = [[InlineKeyboardButton(get_text("go_to_payment", user_id), url=payment_url)]]
            await update.message.reply_text(get_text("order_created", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(get_text("payment_error", user_id))
    
    else: # cash, cod, cashless
        await update.message.reply_text(get_text("order_offline_created", user_id))

    context.user_data.pop('order_info', None)
    context.user_data.pop('customer_info', None)
    
    await update.message.reply_text(get_text("welcome", user_id), reply_markup=get_main_keyboard(user_id))
    return MAIN_MENU

# === КОНЕЦ НОВОГО БЛОКА ===

async def notify_admin_of_new_order(context: ContextTypes.DEFAULT_TYPE, order_id: str, payment_method: str, product_name: str, customer_info: dict):
    order_info = db_query("SELECT user_id FROM orders WHERE id = ?", (order_id,), fetchone=True)
    if not order_info: return
    user_id = order_info['user_id']
    try:
        user = await context.bot.get_chat(user_id)
        user_info = f"{user.first_name} (@{user.username})" if user.username else user.first_name
    except TelegramError:
        user_info = f"ID: {user_id}"

    details_text = get_text("order_details_for_admin", "ru").format( # Используем язык админа
        name=customer_info.get('name', '-'),
        phone=customer_info.get('phone', '-'),
        city=customer_info.get('city', '-'),
        address=customer_info.get('address', '-')
    )

    text_for_admin = (
        f"{get_text('new_order_for_admin', 'ru')}\n\n"
        f"<b>Товар:</b> {product_name}\n"
        f"<b>Способ оплаты:</b> {payment_method}\n"
        f"<b>Пользователь:</b> {user_info}\n<b>User ID:</b> {user_id}\n"
        f"<b>Order ID:</b> {order_id}\n\n"
        f"{details_text}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text_for_admin, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

async def search_model_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    query_text = update.message.text.lower()
    
    found_products = []
    for prod_id, details in product_details_cache.items():
        if query_text in details['name'].lower():
            found_products.append((prod_id, details['name']))

    if not found_products:
        await update.message.reply_text(get_text("model_not_found", user_id))
    else:
        keyboard = [[InlineKeyboardButton(name, callback_data=f"prod_{prod_id}")] for prod_id, name in found_products]
        await update.message.reply_text(get_text("model_found", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    
    return MAIN_MENU


# --- ФИЛЬТРЫ (без изменений) ---
def get_filter_keyboard(user_id, context):
    filters_data = context.user_data.get('filters', {})
    min_price = filters_data.get('min_price')
    max_price = filters_data.get('max_price')
    currency = filters_data.get('currency', 'UAH').upper()

    min_price_text = f" ({min_price})" if min_price else ""
    max_price_text = f" ({max_price})" if max_price else ""
    currency_text = f" ({currency})"

    keyboard = [
        [
            KeyboardButton(get_text("set_min_price", user_id) + min_price_text),
            KeyboardButton(get_text("set_max_price", user_id) + max_price_text)
        ],
        [KeyboardButton(get_text("choose_currency", user_id) + currency_text)],
        [KeyboardButton(get_text("apply_filters", user_id))],
        [KeyboardButton(get_text("reset_filters", user_id)), KeyboardButton(get_text("back_to_main", user_id))],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    context.user_data.setdefault('filters', {}).setdefault('currency', 'uah')
    await update.message.reply_text(
        get_text("filter_menu_title", user_id),
        reply_markup=get_filter_keyboard(user_id, context)
    )
    return FILTER_MENU

async def toggle_filter_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    filters_data = context.user_data.setdefault('filters', {})
    current_currency = filters_data.get('currency', 'uah')

    new_currency = 'usd' if current_currency == 'uah' else 'uah'
    filters_data['currency'] = new_currency
    
    await update.message.reply_text(
        get_text("currency_set_to", user_id).format(new_currency.upper()),
        reply_markup=get_filter_keyboard(user_id, context)
    )
    return FILTER_MENU

async def ask_for_min_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("enter_min_price", update.effective_user.id))
    return SET_MIN_PRICE

async def set_min_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    try:
        price = int(update.message.text)
        context.user_data.setdefault('filters', {})['min_price'] = price
        await update.message.reply_text(
            get_text("price_set", user_id),
            reply_markup=get_filter_keyboard(user_id, context)
        )
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
    return FILTER_MENU

async def ask_for_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("enter_max_price", update.effective_user.id))
    return SET_MAX_PRICE

async def set_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    try:
        price = int(update.message.text)
        context.user_data.setdefault('filters', {})['max_price'] = price
        await update.message.reply_text(
            get_text("price_set", user_id),
            reply_markup=get_filter_keyboard(user_id, context)
        )
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректкое число.")
    return FILTER_MENU
    
async def reset_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'filters' in context.user_data:
        lang_currency = context.user_data['filters'].get('currency')
        context.user_data['filters'] = {}
        if lang_currency:
            context.user_data['filters']['currency'] = lang_currency

    await update.message.reply_text(
        "Фильтры цен сброшены.",
        reply_markup=get_filter_keyboard(update.effective_user.id, context)
    )
    return FILTER_MENU

async def apply_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    filters_data = context.user_data.get('filters', {})
    min_price = filters_data.get('min_price')
    max_price = filters_data.get('max_price')
    currency = filters_data.get('currency', 'uah')

    min_price_kopecks = None
    max_price_kopecks = None

    if currency == 'usd':
        usd_rate = get_usd_to_uah_rate()
        if not usd_rate:
            await update.message.reply_text(get_text("currency_rate_error", user_id))
            return FILTER_MENU
        if min_price is not None:
            min_price_kopecks = int(min_price * usd_rate * 100)
        if max_price is not None:
            max_price_kopecks = int(max_price * usd_rate * 100)
    else: # UAH
        if min_price is not None:
            min_price_kopecks = min_price * 100
        if max_price is not None:
            max_price_kopecks = max_price * 100

    query = "SELECT id, name FROM products WHERE price_numeric IS NOT NULL"
    params = []
    if min_price_kopecks is not None:
        query += " AND price_numeric >= ?"
        params.append(min_price_kopecks)
    if max_price_kopecks is not None:
        query += " AND price_numeric <= ?"
        params.append(max_price_kopecks)

    found_products = db_query(query, tuple(params), fetchall=True)
    await update.message.reply_text("Поиск завершен.", reply_markup=get_main_keyboard(user_id))

    if not found_products:
        await update.message.reply_text(get_text("no_results_filters", user_id))
    else:
        keyboard = [[InlineKeyboardButton(row['name'], callback_data=f"prod_{row['id']}")] for row in found_products]
        await update.message.reply_text(get_text("filters_applied", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
        
    context.user_data.pop('filters', None)
    return MAIN_MENU


# --- ПАРСИНГ КАНАЛА И АДМИН-ПАНЕЛЬ (без изменений) ---
def parse_message_for_product(message):
    text = message.text or message.caption or ""
    text_lower = text.lower()
    
    category = None
    categories_from_db = db_query("SELECT name FROM categories", fetchall=True)
    for cat_tuple in categories_from_db:
        cat_name = cat_tuple[0]
        if re.search(r'\b' + re.escape(cat_name.lower()) + r'\b', text_lower, re.UNICODE):
            category = cat_name
            break
    if not category: return None

    product_name = None
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines: return None

    if category.lower() in lines[0].lower():
        product_name = lines[0].strip()
    else:
        for line in lines:
            if category.lower() in line.lower():
                product_name = line.strip()
                break
    if not product_name: product_name = lines[0].strip()
    if len(product_name) > 100: product_name = product_name[:97] + "..."

    price_display, price_numeric, cleaned_description = process_price_string(text)
    
    year_match = re.search(r'\b(20\d{2})\b', text)
    year = int(year_match.group(1)) if year_match else None

    details = {
        "description": cleaned_description,
        "price": price_display,
        "price_numeric": price_numeric,
        "year": year,
        "photo": message.photo[-1].file_id if message.photo else None,
        "video": message.video.file_id if message.video else None
    }
    return category, product_name, details

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.channel_post
    if not message: return
    parsed_data = parse_message_for_product(message)
    if parsed_data:
        category, product_name, details = parsed_data
        exists = db_query("SELECT 1 FROM products WHERE name = ?", (product_name,), fetchone=True)
        if not exists:
            db_query("INSERT INTO products (name, description, price, price_numeric, year, photo_id, video_id, category_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (product_name, details['description'], details['price'], details['price_numeric'], details['year'], details['photo'], details['video'], category), commit=True)
            logger.info(f"Добавлен новый товар из канала: {product_name}")
            load_data_from_db()
        else:
            logger.info(f"Товар '{product_name}' из канала уже существует в БД. Пропускаем.")

def get_admin_keyboard(user_id):
    keyboard = [
        [KeyboardButton(get_text("admin_stats", user_id)), KeyboardButton(get_text("admin_categories", user_id))],
        [KeyboardButton(get_text("admin_products", user_id)), KeyboardButton(get_text("admin_posting", user_id))],
        [KeyboardButton(get_text("admin_back", user_id))]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(get_text("no_access", user_id))
        return ConversationHandler.END
    await update.message.reply_text(get_text("admin_welcome", user_id), reply_markup=get_admin_keyboard(user_id))
    return ADMIN_PANEL

async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await admin_panel(update, context)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("welcome", update.effective_user.id), reply_markup=get_main_keyboard(update.effective_user.id))
    return MAIN_MENU

async def sync_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(get_text("no_access", user_id))
        return
    await update.message.reply_text(get_text("sync_command_info", user_id), parse_mode="HTML")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    month_ago = today - datetime.timedelta(days=30)
    
    total = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    today_count = db_query("SELECT COUNT(*) FROM users WHERE date(join_date) = ?", (today.isoformat(),), fetchone=True)[0]
    week_count = db_query("SELECT COUNT(*) FROM users WHERE date(join_date) >= ?", (week_ago.isoformat(),), fetchone=True)[0]
    month_count = db_query("SELECT COUNT(*) FROM users WHERE date(join_date) >= ?", (month_ago.isoformat(),), fetchone=True)[0]
    
    stats_text = (f"{get_text('stats_title', user_id)}\n\n"
                  f"👤 {get_text('stats_total', user_id)} <b>{total}</b>\n"
                  f"☀️ {get_text('stats_today', user_id)} <b>{today_count}</b>\n"
                  f"📅 {get_text('stats_week', user_id)} <b>{week_count}</b>\n"
                  f"🗓️ {get_text('stats_month', user_id)} <b>{month_count}</b>")
    await update.message.reply_text(stats_text, parse_mode="HTML")
    return ADMIN_PANEL

async def admin_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    keyboard = ReplyKeyboardMarkup([[KeyboardButton(get_text("cat_add", user_id)), KeyboardButton(get_text("cat_del", user_id))],
                                    [KeyboardButton(get_text("admin_back", user_id))]], resize_keyboard=True)
    await update.message.reply_text(get_text("cat_manage", user_id), reply_markup=keyboard)
    return ADMIN_CATEGORIES

async def admin_add_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("cat_enter_name", update.effective_user.id))
    return ADMIN_ADD_CATEGORY_NAME

async def admin_add_category_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cat_name = update.message.text.strip()
    user_id = update.effective_user.id
    if db_query("SELECT 1 FROM categories WHERE name = ?", (cat_name,), fetchone=True):
        await update.message.reply_text(get_text("cat_exists", user_id))
    else:
        db_query("INSERT INTO categories (name) VALUES (?)", (cat_name,), commit=True)
        load_data_from_db()
        await update.message.reply_text(get_text("cat_added", user_id).format(cat_name))
    return await admin_categories(update, context)

async def admin_del_category_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    categories = db_query("SELECT name FROM categories", fetchall=True)
    if not categories:
        await update.message.reply_text("Нет категорий для удаления.")
        return await admin_categories(update, context)
    keyboard = [[InlineKeyboardButton(cat['name'], callback_data=f"delcat_{cat['name']}")] for cat in categories]
    await update.message.reply_text(get_text("cat_choose_del", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_DEL_CATEGORY

async def admin_del_category_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    cat_name = query.data.split("_", 1)[1]
    db_query("DELETE FROM products WHERE category_name = ?", (cat_name,), commit=True)
    db_query("DELETE FROM categories WHERE name = ?", (cat_name,), commit=True)
    load_data_from_db()
    await query.edit_message_text(get_text("cat_deleted", user_id).format(cat_name))
    # Hack to pass message object to the next state function
    query.message.from_user = query.from_user 
    return await admin_categories(query.message, context)

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    keyboard = ReplyKeyboardMarkup([[KeyboardButton(get_text("prod_add", user_id)), KeyboardButton(get_text("prod_del", user_id))],
                                    [KeyboardButton(get_text("admin_back", user_id))]], resize_keyboard=True)
    await update.message.reply_text(get_text("prod_manage", user_id), reply_markup=keyboard)
    return ADMIN_PRODUCTS

async def admin_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    categories = db_query("SELECT name FROM categories", fetchall=True)
    keyboard = [[InlineKeyboardButton(cat['name'], callback_data=f"addprod_{cat['name']}")] for cat in categories]
    await update.message.reply_text(get_text("prod_choose_cat_for_add", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_ADD_PRODUCT_STEP1_CAT

async def admin_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['new_product'] = {'category': query.data.split('_', 1)[1]}
    await query.edit_message_text(get_text("prod_enter_name", query.from_user.id))
    return ADMIN_ADD_PRODUCT_STEP2_NAME

async def admin_add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_product']['name'] = update.message.text.strip()
    await update.message.reply_text(get_text("prod_enter_desc", update.effective_user.id))
    return ADMIN_ADD_PRODUCT_STEP3_DESC

async def admin_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_product']['description'] = update.message.text
    await update.message.reply_text(get_text("prod_enter_price", update.effective_user.id), parse_mode="Markdown")
    return ADMIN_ADD_PRODUCT_STEP4_PRICE

async def admin_add_product_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_str = update.message.text.strip()
    price_display, numeric_price, _ = process_price_string(f"Цена: {price_str}")
    context.user_data['new_product']['price'] = price_display
    context.user_data['new_product']['price_numeric'] = numeric_price
    await update.message.reply_text(get_text("prod_send_media", update.effective_user.id))
    return ADMIN_ADD_PRODUCT_STEP5_MEDIA

async def admin_add_product_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    product = context.user_data['new_product']
    product['photo'] = update.message.photo[-1].file_id if update.message.photo else None
    product['video'] = update.message.video.file_id if update.message.video else None
    year_match = re.search(r'\b(20\d{2})\b', product['description'])
    year = int(year_match.group(1)) if year_match else None
    if db_query("SELECT 1 FROM products WHERE name = ?", (product['name'],), fetchone=True):
        await update.message.reply_text(get_text("prod_exists", user_id))
    else:
        db_query("INSERT INTO products (name, description, price, price_numeric, year, photo_id, video_id, category_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (product['name'], product['description'], product['price'], product['price_numeric'], year, product['photo'], product['video'], product['category']), commit=True)
        load_data_from_db()
        await update.message.reply_text(get_text("prod_added", user_id).format(product['name']))
    context.user_data.pop('new_product', None)
    return await admin_panel(update, context)

async def admin_del_product_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    all_products = db_query("SELECT id, name FROM products ORDER BY name", fetchall=True)
    if not all_products:
        await update.message.reply_text(get_text("no_products_in_category", user_id))
        return await admin_products(update, context)
    keyboard = [[InlineKeyboardButton(row['name'], callback_data=f"delprod_{row['id']}")] for row in all_products]
    await update.message.reply_text(get_text("prod_choose_del", user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_DEL_PRODUCT

async def admin_del_product_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    product_id = int(query.data.replace("delprod_", "", 1))
    product_name = product_details_cache.get(product_id, {}).get("name", f"ID: {product_id}")
    db_query("DELETE FROM products WHERE id = ?", (product_id,), commit=True)
    load_data_from_db()
    await query.edit_message_text(get_text("prod_deleted", user_id).format(product_name))
    query.message.from_user = query.from_user
    return await admin_products(query.message, context)

async def admin_posting_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(get_text("post_enter_text", update.effective_user.id))
    context.user_data['new_post'] = {}
    return ADMIN_POSTING_STEP1_TEXT

async def admin_posting_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_post']['text'] = update.message.text
    await update.message.reply_text(get_text("post_send_media", update.effective_user.id))
    return ADMIN_POSTING_STEP2_MEDIA

async def admin_posting_btn_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_post']['photo'] = update.message.photo[-1].file_id
    await update.message.reply_text(get_text("post_enter_btn_text", update.effective_user.id))
    return ADMIN_POSTING_STEP3_BTN_TEXT

async def admin_posting_btn_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_post']['btn_text'] = update.message.text
    await update.message.reply_text(get_text("post_enter_btn_url", update.effective_user.id))
    return ADMIN_POSTING_STEP4_BTN_URL

async def admin_posting_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    post_data = context.user_data['new_post']
    post_data['btn_url'] = update.message.text
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(post_data['btn_text'], url=post_data['btn_url'])]])
    try:
        await context.bot.send_photo(
            chat_id=SOURCE_CHANNEL_ID, photo=post_data['photo'],
            caption=post_data['text'], reply_markup=keyboard)
        await update.message.reply_text(get_text("post_success", user_id))
    except TelegramError as e:
        logger.error(f"Ошибка постинга в канал {SOURCE_CHANNEL_ID}: {e}")
        error_text = get_text("post_fail", user_id)
        if "Chat not found" in str(e):
            error_text += get_text("post_fail_chat_not_found", user_id)
        await update.message.reply_text(error_text, parse_mode="HTML")
    context.user_data.pop('new_post', None)
    return await admin_panel(update, context)

# --- ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА ---
def main() -> None:
    init_db()
    load_data_from_db()
    application = Application.builder().token(BOT_TOKEN).build()
    
    main_menu_handlers = [
        MessageHandler(filters.Regex(l10n_regex("catalog")), catalog),
        MessageHandler(filters.Regex(l10n_regex("find_model")), search_model_prompt),
        MessageHandler(filters.Regex(l10n_regex("filters")), filter_menu),
        MessageHandler(filters.Regex(l10n_regex("change_language")), change_language_prompt),
        MessageHandler(filters.Regex(l10n_regex("support")), show_support_contact),
    ]

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("admin", admin_panel)],
        states={
            MAIN_MENU: main_menu_handlers + [
                CallbackQueryHandler(start_checkout_flow, pattern="^pay_"), # Обработчик кнопок оплаты
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_fallback)
            ],
            LANGUAGE_SELECTION: [CallbackQueryHandler(set_language, pattern="^lang_")],
            MODEL_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_model_result)] + main_menu_handlers,
            
            # Состояния фильтров
            FILTER_MENU: [
                MessageHandler(filters.Regex(l10n_regex("set_min_price")), ask_for_min_price),
                MessageHandler(filters.Regex(l10n_regex("set_max_price")), ask_for_max_price),
                MessageHandler(filters.Regex(l10n_regex("choose_currency")), toggle_filter_currency),
                MessageHandler(filters.Regex(l10n_regex("apply_filters")), apply_filters),
                MessageHandler(filters.Regex(l10n_regex("reset_filters")), reset_filters),
                MessageHandler(filters.Regex(l10n_regex("back_to_main")), back_to_main_menu)
            ] + main_menu_handlers,
            SET_MIN_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_min_price)],
            SET_MAX_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_max_price)],

            # === Новые состояния для сбора данных ===
            GET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_city)],
            GET_NOVAPOSHTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_novaposhta_and_finalize)],

            # Админ-панель (имеет свою изолированную логику)
            ADMIN_PANEL: [
                MessageHandler(filters.Regex(l10n_regex("admin_stats")), admin_stats),
                MessageHandler(filters.Regex(l10n_regex("admin_categories")), admin_categories),
                MessageHandler(filters.Regex(l10n_regex("admin_products")), admin_products),
                MessageHandler(filters.Regex(l10n_regex("admin_posting")), admin_posting_start),
                MessageHandler(filters.Regex(l10n_regex("admin_back")), back_to_main_menu)
            ],
            ADMIN_CATEGORIES: [
                MessageHandler(filters.Regex(l10n_regex("cat_add")), admin_add_category_prompt),
                MessageHandler(filters.Regex(l10n_regex("cat_del")), admin_del_category_prompt),
                MessageHandler(filters.Regex(l10n_regex("admin_back")), back_to_admin_menu)
            ],
            ADMIN_PRODUCTS: [
                MessageHandler(filters.Regex(l10n_regex("prod_add")), admin_add_product_start),
                MessageHandler(filters.Regex(l10n_regex("prod_del")), admin_del_product_prompt),
                MessageHandler(filters.Regex(l10n_regex("admin_back")), back_to_admin_menu)
            ],
            ADMIN_ADD_CATEGORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_category_save)],
            ADMIN_DEL_CATEGORY: [CallbackQueryHandler(admin_del_category_confirm, pattern="^delcat_")],
            ADMIN_ADD_PRODUCT_STEP1_CAT: [CallbackQueryHandler(admin_add_product_name, pattern="^addprod_")],
            ADMIN_ADD_PRODUCT_STEP2_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_desc)],
            ADMIN_ADD_PRODUCT_STEP3_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_price)],
            ADMIN_ADD_PRODUCT_STEP4_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_media)],
            ADMIN_ADD_PRODUCT_STEP5_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, admin_add_product_save)],
            ADMIN_DEL_PRODUCT: [CallbackQueryHandler(admin_del_product_confirm, pattern="^delprod_")],
            ADMIN_POSTING_STEP1_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_posting_media)],
            ADMIN_POSTING_STEP2_MEDIA: [MessageHandler(filters.PHOTO, admin_posting_btn_text)],
            ADMIN_POSTING_STEP3_BTN_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_posting_btn_url)],
            ADMIN_POSTING_STEP4_BTN_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_posting_publish)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("admin", admin_panel)],
        per_message=False,
        allow_reentry=True
    )
    
    # Глобальный обработчик для кнопок, которые не меняют состояние диалога
    application.add_handler(CallbackQueryHandler(catalog_button_handler, pattern="^(cat_|prod_|buy_)"))

    # ConversationHandler должен идти после глобальных обработчиков, которые он не должен перехватывать
    application.add_handler(conv_handler)
    
    # Прочие обработчики
    application.add_handler(CommandHandler("sync", sync_channel_info))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))

    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()