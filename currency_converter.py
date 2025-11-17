

import logging
import time
import requests

logger = logging.getLogger(__name__)

# Кеш для хранения курса валют
# Структура: {'usd_uah': {'rate': 39.5, 'timestamp': 1678886400}}
CURRENCY_CACHE = {}
CACHE_LIFETIME_SECONDS = 3600  # 1 час

def get_usd_to_uah_rate() -> float | None:
    """
    Получает и кеширует курс продажи USD к UAH из API ПриватБанка.
    Возвращает курс или None в случае ошибки.
    """
    cache_key = 'usd_uah'
    
    # Проверяем, есть ли свежие данные в кеше
    if cache_key in CURRENCY_CACHE:
        cache_entry = CURRENCY_CACHE[cache_key]
        if time.time() - cache_entry['timestamp'] < CACHE_LIFETIME_SECONDS:
            logger.info(f"Используем курс USD из кеша: {cache_entry['rate']}")
            return cache_entry['rate']

    # Если в кеше нет или данные устарели, делаем запрос
    try:
        logger.info("Обновляем курс USD из API ПриватБанка...")
        # API ПриватБанка для получения наличного курса
        response = requests.get('https://api.privatbank.ua/p24api/pubinfo?json&exchange&coursid=5')
        response.raise_for_status()
        data = response.json()
        
        usd_rate = None
        for currency in data:
            if currency['ccy'] == 'USD':
                # Используем курс продажи (sale)
                usd_rate = float(currency['sale'])
                break
        
        if usd_rate:
            # Сохраняем в кеш
            CURRENCY_CACHE[cache_key] = {
                'rate': usd_rate,
                'timestamp': time.time()
            }
            logger.info(f"Новый курс USD получен и закеширован: {usd_rate}")
            return usd_rate
        else:
            logger.error("Не удалось найти курс USD в ответе API.")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе курса валют: {e}")
        return None
    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"Ошибка при парсинге ответа API курсов валют: {e}")
        return None