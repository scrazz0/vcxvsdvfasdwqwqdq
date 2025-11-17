
import base64
import hashlib
import json
import logging
import requests
from config import (
    LIQPAY_PUBLIC_KEY, LIQPAY_PRIVATE_KEY, # Оставлено на случай, если захотите вернуть
    MONOBANK_API_TOKEN,
    WEBHOOK_DOMAIN,
    BOT_USERNAME
)

# Настройка логирования
logger = logging.getLogger(__name__)


# --- LIQPAY INTEGRATION --- (без изменений, но больше не используется в main.py)
def generate_liqpay_link(order_id: str, amount: int, description: str) -> str:
    try:
        if not BOT_USERNAME or BOT_USERNAME == "YourBotUsername":
            logger.warning("BOT_USERNAME не установлен в config.py. Ссылка возврата может быть некорректной.")
            result_url = "" 
        else:
            result_url = f'https://t.me/{BOT_USERNAME}'

        params = {
            'action': 'pay',
            'amount': str(amount / 100), 
            'currency': 'UAH',
            'description': description,
            'order_id': order_id,
            'version': '3',
            'public_key': LIQPAY_PUBLIC_KEY,
            'result_url': result_url, 
            'server_url': f'{WEBHOOK_DOMAIN}/webhook/liqpay',
        }
        
        data_to_encode = json.dumps(params).encode('utf-8')
        data = base64.b64encode(data_to_encode).decode('utf-8')
        
        checkout_url = f"https://www.liqpay.ua/api/3/checkout?data={data}"
        
        return checkout_url
    except Exception as e:
        logger.error(f"Ошибка при генерации ссылки LiqPay: {e}")
        return None


# --- MONOBANK INTEGRATION ---

def _create_mono_invoice(order_id: str, amount: int, description: str, payment_type: str) -> dict | None:
    """
    Универсальная функция для создания счета Monobank.
    payment_type: 'debit' (оплата картой) или 'ib' (покупка частями).
    """
    try:
        if not BOT_USERNAME or BOT_USERNAME == "YourBotUsername":
            logger.warning("BOT_USERNAME не установлен в config.py. Ссылка возврата может быть некорректной.")
            redirect_url = ""
        else:
            redirect_url = f'https://t.me/{BOT_USERNAME}'

        invoice_details = {
            "amount": amount,
            "ccy": 980, # Код валюты UAH
            "merchantPaymInfo": {
                "reference": order_id,
                "destination": description,
                "basketOrder": [
                    {
                        "name": description[:127], 
                        "qty": 1,
                        "sum": amount,
                        "code": str(order_id)
                    }
                ]
            },
            "redirectUrl": redirect_url,
            "webHookUrl": f'{WEBHOOK_DOMAIN}/webhook/monobank',
            "paymentType": payment_type,
        }
        # Для "Покупки Частями" требуется дополнительное поле
        if payment_type == "ib":
            invoice_details["merchantPaymInfo"]["paymentDetails"] = description

        headers = {
            "X-Token": MONOBANK_API_TOKEN.strip(),
        }

        response = requests.post("https://api.monobank.ua/api/merchant/invoice/create", json=invoice_details, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "pageUrl" in data:
            return {
                "url": data.get("pageUrl"),
                "invoice_id": data.get("invoiceId")
            }
        else:
            logger.error(f"Ошибка от API Monobank: {data.get('errText')}")
            return None
            
    except requests.exceptions.RequestException as e:
        error_details = "Нет ответа от сервера"
        if e.response is not None:
            try:
                error_details = e.response.json()
            except json.JSONDecodeError:
                error_details = e.response.text
        logger.error(f"Ошибка создания счета Monobank: {e}. Детали: {error_details}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при создании счета Monobank: {e}")
        return None

def generate_mono_card_invoice(order_id: str, amount: int, description: str) -> dict:
    """
    Создает счет для обычной оплаты картой Monobank (debit).
    """
    logger.info(f"Создание счета Monobank (Оплата картой) для заказа {order_id}")
    return _create_mono_invoice(order_id, amount, description, "debit")

def generate_mono_parts_invoice(order_id: str, amount: int, description: str) -> dict:
    """
    Создает счет для "Покупки Частинами" Monobank (ib).
    ВАЖНО: Для работы этого метода в боевом режиме требуется соответствующий эквайринг.
    Тестовый токен может не поддерживать тип 'ib'.
    """
    logger.info(f"Создание счета Monobank (Покупка Частинами) для заказа {order_id}")
    return _create_mono_invoice(order_id, amount, description, "ib")