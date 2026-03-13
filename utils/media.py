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
    keys = {
        "iPhone":  "iPhone_STUB",
        "iPad":    "iPad_STUB",
        "Watch":   "AppleWatch_STUB",
        "AirPods": "AirPods_STUB",
    }
    key = keys.get(cat, "MacBook_STUB" if "iMac" not in model else "iMac_STUB")
    return store.SETTINGS.get(key)

async def fetch_image_bytes(url: str) -> bytes | None:
    if not url or not url.startswith("http"):
        return None
    try:
        async with aiohttp.ClientSession(headers=FETCH_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return data
                logger.warning(f"fetch_image_bytes: HTTP {resp.status} for {url[:60]}")
                return None
    except Exception as e:
        logger.warning(f"fetch_image_bytes error: {e}")
        return None

async def send_photo_safe(target, url: str, caption: str, reply_markup, is_edit: bool = False):
    async def _as_buffered(photo_bytes: bytes):
        buf = BufferedInputFile(photo_bytes, filename="photo.jpg")
        if is_edit:
            await target.edit_media(InputMediaPhoto(media=buf, caption=caption), reply_markup=reply_markup)
        else:
            await target.answer_photo(buf, caption=caption, reply_markup=reply_markup)

    try:
        if is_edit:
            await target.edit_media(InputMediaPhoto(media=url, caption=caption), reply_markup=reply_markup)
        else:
            await target.answer_photo(url, caption=caption, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"send_photo_safe: прямой URL не сработал ({e}), качаю байты...")
        photo_bytes = await fetch_image_bytes(url)
        if photo_bytes:
            await _as_buffered(photo_bytes)
        else:
            if is_edit:
                await target.edit_caption(caption=caption, reply_markup=reply_markup)
            else:
                await target.answer(caption, reply_markup=reply_markup)
