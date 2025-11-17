import sqlite3
import logging
import datetime

logger = logging.getLogger(__name__)
DB_NAME = "bot_database.db"

def init_db():
    """
    Инициализирует базу данных, создает таблицы и добавляет базовые категории.
    При необходимости обновляет схему таблиц.
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # ... (остальные таблицы без изменений)
        
        # Таблица пользователей
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date TEXT
        )
        """)
        
        # Таблица категорий
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """)
        
        # Таблица товаров
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            price TEXT,
            price_numeric INTEGER,
            year INTEGER,
            photo_id TEXT,
            video_id TEXT,
            category_name TEXT,
            FOREIGN KEY (category_name) REFERENCES categories (name) ON DELETE CASCADE
        )
        """)

        # Таблица заказов
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            payment_method TEXT,
            payment_invoice_id TEXT,
            status TEXT DEFAULT 'pending', -- pending, processing, paid, failed, canceled
            created_at TEXT,
            customer_phone TEXT,
            customer_name TEXT,
            customer_city TEXT,
            customer_address TEXT
        )
        """)

        base_categories = [("Iphone",), ("MacBook",), ("AirPods",), ("Apple Watch",)]
        cursor.executemany("INSERT OR IGNORE INTO categories (name) VALUES (?)", base_categories)
        
        # Миграция: добавление столбцов в products
        try:
            cursor.execute("SELECT price_numeric, year FROM products LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Обновление схемы 'products': добавление 'price_numeric' и 'year'.")
            cursor.execute("ALTER TABLE products ADD COLUMN price_numeric INTEGER")
            cursor.execute("ALTER TABLE products ADD COLUMN year INTEGER")

        # Миграция: добавление столбцов в orders
        try:
            cursor.execute("SELECT customer_phone FROM orders LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Обновление схемы 'orders': добавление полей для данных клиента.")
            cursor.execute("ALTER TABLE orders ADD COLUMN customer_phone TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN customer_name TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN customer_city TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN customer_address TEXT")

        conn.commit()
        logger.info("База данных успешно инициализирована.")


def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    """
    Универсальная функция для выполнения запросов к БД.
    """
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        result = None
        if fetchone:
            result = cursor.fetchone()
        elif fetchall:
            result = cursor.fetchall()
            
        if commit:
            conn.commit()
            
        return result

def register_user(user_id: int, username: str, first_name: str):
    """
    Добавляет нового пользователя в БД, если он еще не зарегистрирован.
    """
    db_query(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, join_date) VALUES (?, ?, ?, ?)",
        (user_id, username, first_name, datetime.datetime.now().isoformat()),
        commit=True
    )