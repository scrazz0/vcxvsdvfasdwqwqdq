import os
import sys
import logging
import json
import base64
import hashlib
import sqlite3
import asyncio
import threading  # <-- Добавлен импорт
from flask import Flask, request, abort
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

# --- НАСТРОЙКА И КОНФИГУРАЦИЯ ---

load_dotenv()

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from config import BOT_TOKEN, ADMIN_IDS, LIQPAY_PRIVATE_KEY
except ImportError:
    print("Ошибка: Не удалось импортировать переменные из config.py.")
    print("Убедитесь, что файл config.py существует и содержит BOT_TOKEN, ADMIN_IDS, LIQPAY_PRIVATE_KEY.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)

# --- НОВАЯ ФУНКЦИЯ ДЛЯ ЗАПУСКА ASYNC ЗАДАЧ В ФОНОВОМ ПОТОКЕ ---
def run_async_in_thread(target, *args):
    """
    Безопасно запускает асинхронную функцию в новом потоке,
    чтобы не блокировать основной поток Flask.
    """
    try:
        asyncio.run(target(*args))
    except Exception as e:
        logger.error(f"Ошибка в фоновом потоке при выполнении {target.__name__}: {e}")

# --- РАБОТА С БАЗОЙ ДАННЫХ ---

def get_db_connection():
    """Безопасное подключение к базе данных SQLite."""
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_database.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return None

# --- ОСНОВНАЯ ЛОГИКА ОБРАБОТКИ ПЛАТЕЖЕЙ (без изменений) ---

async def process_successful_payment(order_id: str, payment_system: str):
    """
    Обрабатывает УСПЕШНЫЙ платеж: обновляет заказ и рассылает уведомления.
    """
    logger.info(f"Начало обработки УСПЕШНОГО платежа для заказа {order_id} через {payment_system}")
    conn = get_db_connection()
    if not conn: return

    try:
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT 
                   o.user_id, o.status, p.name as product_name,
                   o.customer_name, o.customer_phone, o.customer_city, o.customer_address
               FROM orders o 
               JOIN products p ON o.product_id = p.id 
               WHERE o.id = ?""", (order_id,)
        )
        order_info = cursor.fetchone()

        if not order_info:
            logger.warning(f"Получен вебхук для несуществующего заказа: {order_id}")
            return

        if order_info['status'] == 'paid':
            logger.info(f"Заказ {order_id} уже был оплачен. Повторная обработка отменена.")
            return

        cursor.execute("UPDATE orders SET status = 'paid' WHERE id = ? AND status != 'paid'", (order_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            logger.warning(f"Не удалось обновить статус 'paid' для заказа {order_id}. Возможно, он уже был обработан (статус: {order_info['status']}).")
            return

        logger.info(f"Статус заказа {order_id} успешно обновлен на 'paid'")

        user_id = order_info['user_id']
        product_name = order_info['product_name']
        
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"✅ Оплата за товар «{product_name}» прошла успешно! Менеджер скоро с вами свяжется."
            )
        except TelegramError as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

        user_info = f"ID: {user_id}"
        try:
            user = await bot.get_chat(user_id)
            user_info = f"{user.first_name} (@{user.username})" if user.username else user.first_name
        except TelegramError as e:
            logger.warning(f"Не удалось получить информацию о пользователе {user_id}: {e}")
        
        customer_details = (
            f"<b>Имя:</b> {order_info['customer_name']}\n"
            f"<b>Телефон:</b> {order_info['customer_phone']}\n"
            f"<b>Город:</b> {order_info['customer_city']}\n"
            f"<b>Отделение НП:</b> {order_info['customer_address']}"
        )

        admin_text = (
            f"✅ Новая УСПЕШНАЯ ОПЛАТА!\n\n"
            f"<b>Товар:</b> {product_name}\n"
            f"<b>Способ оплаты:</b> {payment_system}\n"
            f"<b>Order ID:</b> {order_id}\n\n"
            f"👤 <b>Покупатель:</b> {user_info}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"{customer_details}"
        )

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Критическая ошибка при обработке успешного платежа для заказа {order_id}: {e}")
    finally:
        if conn: conn.close()


async def process_unsuccessful_payment(order_id: str, payment_system: str, status: str):
    """
    Обрабатывает НЕУСПЕШНЫЙ платеж: логирует, обновляет статус и уведомляет админов.
    """
    logger.warning(f"Обработка НЕУСПЕШНОГО платежа для заказа {order_id} через {payment_system}. Статус: {status}")
    conn = get_db_connection()
    if not conn: return

    try:
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT o.user_id, o.status, p.name as product_name 
               FROM orders o JOIN products p ON o.product_id = p.id 
               WHERE o.id = ?""", (order_id,)
        )
        order_info = cursor.fetchone()
        
        if not order_info or order_info['status'] == 'paid':
            logger.info(f"Заказ {order_id} не найден или уже оплачен. Действий не требуется.")
            return

        cursor.execute("UPDATE orders SET status = ? WHERE id = ? AND status != 'paid'", (status, order_id))
        conn.commit()
        logger.info(f"Статус заказа {order_id} обновлен на '{status}'")

        user_id = order_info['user_id']
        product_name = order_info['product_name']
        user_info = f"ID: {user_id}"
        try:
            user = await bot.get_chat(user_id)
            user_info = f"{user.first_name} (@{user.username})" if user.username else user.first_name
        except TelegramError as e:
             logger.warning(f"Не удалось получить информацию о пользователе {user_id} для отчета о сбое: {e}")

        admin_text = (
            f"⚠️ Неуспешная попытка оплаты!\n\n"
            f"<b>Товар:</b> {product_name}\n"
            f"<b>Платежная система:</b> {payment_system}\n"
            f"<b>Статус:</b> {status}\n"
            f"<b>Пользователь:</b> {user_info}\n"
            f"<b>Order ID:</b> {order_id}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление о сбое админу {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Критическая ошибка при обработке неуспешного платежа для заказа {order_id}: {e}")
    finally:
        if conn: conn.close()

# --- ЭНДПОИНТЫ (URL) ДЛЯ ПРИЕМА ВЕБХУКОВ ---

@app.route('/webhook/liqpay', methods=['POST'])
def liqpay_webhook():
    try:
        data = request.form.get('data')
        signature_from_liqpay = request.form.get('signature')
        if not data or not signature_from_liqpay: abort(400)

        expected_signature = base64.b64encode(hashlib.sha1(
            (LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY).encode('utf-8')
        ).digest()).decode('utf-8')

        if expected_signature != signature_from_liqpay:
            logger.error("!!! КРИТИЧЕСКИЙ: ПОДДЕЛКА ПОДПИСИ В ВЕБХУКЕ LIQPAY !!!")
            abort(403)

        decoded_data = json.loads(base64.b64decode(data).decode('utf-8'))
        logger.info(f"Получен валидный вебхук от LiqPay: {decoded_data}")

        order_id = decoded_data.get('order_id')
        status = decoded_data.get('status')

        if not order_id or not status: abort(400)
        
        # === ИЗМЕНЕНИЕ: ЗАПУСК В ФОНОВОМ ПОТОКЕ ===
        if status.lower() in ['success', 'sandbox']:
            thread = threading.Thread(target=run_async_in_thread, args=(process_successful_payment, order_id, "LiqPay"))
            thread.start()
        else:
            thread = threading.Thread(target=run_async_in_thread, args=(process_unsuccessful_payment, order_id, "LiqPay", status))
            thread.start()
        
        # Мгновенно отвечаем OK
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике вебхука LiqPay: {e}")
        abort(500)

@app.route('/webhook/monobank', methods=['POST'])
def monobank_webhook():
    try:
        data = request.json
        logger.info(f"Получен вебхук от Monobank: {data}")
        if not data: abort(400)
            
        order_id = data.get('reference')
        status = data.get('status')
        
        if not order_id or not status:
            return 'OK', 200 
        
        # === ИЗМЕНЕНИЕ: ЗАПУСК В ФОНОВОМ ПОТОКЕ ===
        if status.lower() == 'success':
            thread = threading.Thread(target=run_async_in_thread, args=(process_successful_payment, order_id, "Monobank"))
            thread.start()
            
        elif status in ['created', 'processing']:
            logger.info(f"Получен промежуточный статус '{status}' для заказа {order_id}. Ожидаем финальный статус.")
            # Это быстрая операция, ее можно оставить в основном потоке
            conn = get_db_connection()
            if conn:
                conn.execute("UPDATE orders SET status = ? WHERE id = ? AND status = 'pending'", (status, order_id))
                conn.commit()
                conn.close()
        else: 
            thread = threading.Thread(target=run_async_in_thread, args=(process_unsuccessful_payment, order_id, "Monobank", status))
            thread.start()
        
        # Мгновенно отвечаем OK
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка в обработчике вебхука Monobank: {e}")
        abort(500)

# --- ЗАПУСК СЕРВЕРА ---

if __name__ == '__main__':
    logger.info("Запуск веб-сервера для вебхуков...")
    # Для продакшена используйте gunicorn или waitress вместо app.run()
    app.run(host='0.0.0.0', port=8000, debug=False)