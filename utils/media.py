# utils/media.py
import logging
import aiohttp
from aiogram.types import InputMediaPhoto, BufferedInputFile
import services.data_store as store

logger = logging.getLogger(__name__)

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://www.apple.com/",
}

def get_stub(cat, model=""):
    """Супер-умный поиск картинок-заглушек в настройках"""
    if not cat: return ""
    cat_lower = str(cat).lower()
    
    # Диагностика: если настройки не загрузились вообще
    if not store.SETTINGS:
        logger.error("❌ store.SETTINGS пуст! Проверьте заголовки 'Категория' и 'Ссылка' на листе Settings (строка 1).")
        return ""

    # 1. Приводим базовые категории к ожидаемым ключам
    keys_map = {
        "iphone":  "iPhone_STUB",
        "ipad":    "iPad_STUB",
        "mac":     "MacBook_STUB" if "imac" not in str(model).lower() else "iMac_STUB",
        "watch":   "AppleWatch_STUB",
        "airpods": "AirPods_STUB",
        "dyson":   "Dyson_STUB",
        "xiaomi":  "Xiaomi_STUB"
    }
    
    target_key = keys_map.get(cat_lower)
    
    # 2. Ищем строгое совпадение по ключу
    if target_key and target_key in store.SETTINGS:
        val = str(store.SETTINGS[target_key]).strip()
        if val.startswith("http"): 
            return val
            
    # 3. Ищем частичное совпадение имени категории
    for k, v in store.SETTINGS.items():
        k_str = str(k).lower()
        v_str = str(v).strip()
        
        if not v_str.startswith("http"): 
            continue # Игнорируем строки без ссылок
            
        if cat_lower in k_str:
            return v_str
            
    logger.warning(f"❌ Картинка для категории {cat} НЕ НАЙДЕНА в store.SETTINGS!")
    return ""

async def fetch_image_bytes(url: str) -> bytes | None:
    if not url or not url.startswith("http"):
        return None
    try:
        async with aiohttp.ClientSession(headers=FETCH_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return data
                logger.error(f"❌ Ошибка скачивания фото (Код {resp.status}) по ссылке: {url[:60]}")
                return None
    except Exception as e:
        logger.warning(f"❌ fetch_image_bytes error: {e}")
        return None

async def send_photo_safe(target, url: str, caption: str, reply_markup, is_edit: bool = False):
    if not url:
        if is_edit: await target.edit_caption(caption=caption, reply_markup=reply_markup)
        else: await target.answer(caption, reply_markup=reply_markup)
        return

    async def _as_buffered(photo_bytes: bytes):
        buf = BufferedInputFile(photo_bytes, filename="photo.jpg")
        if is_edit:
            await target.edit_media(InputMediaPhoto(media=buf, caption=caption), reply_markup=reply_markup)
        else:
            await target.answer_photo(buf, caption=caption, reply_markup=reply_markup)

    try:
        # Сначала пробуем отправить ссылку напрямую
        if is_edit:
            await target.edit_media(InputMediaPhoto(media=url, caption=caption), reply_markup=reply_markup)
        else:
            await target.answer_photo(url, caption=caption, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"⚠️ Прямая ссылка не сработала ({e}), качаю байты для {url[:40]}...")
        # Если Телеграм ругается на формат ссылки, качаем сами
        photo_bytes = await fetch_image_bytes(url)
        if photo_bytes:
            await _as_buffered(photo_bytes)
        else:
            logger.error("❌ Не удалось ни отправить ссылку, ни скачать байты. Отправляем голый текст.")
            if is_edit:
                await target.edit_caption(caption=caption, reply_markup=reply_markup)
            else:
                await target.answer(caption, reply_markup=reply_markup)
