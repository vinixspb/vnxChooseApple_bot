import aiohttp
import asyncio
import logging
import json
import base64
import os

logger = logging.getLogger(__name__)

UPLOAD_BASE_URL = "https://kieai.redpandaai.co"
API_BASE_URL    = "https://api.kie.ai/api/v1"

# ── Уведомления Админу через @vnxSYSNOTIFY_bot ───────────────────────────────
async def notify_admin(text: str):
    """Экстренная отправка сообщения админу (MANAGER_ID) через бота уведомлений"""
    token = os.getenv("NOTIFY_BOT_TOKEN")
    admin_id = os.getenv("MANAGER_ID")
    if not token or not admin_id:
        logger.warning("NOTIFY_BOT_TOKEN или MANAGER_ID не заданы. Уведомление не отправлено.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        logger.error(f"Admin notification failed: {e}")

def _detect_mime(photo_bytes: bytes) -> str:
    if photo_bytes[:4] == b'\x89PNG': return "image/png"
    if photo_bytes[:2] == b'\xff\xd8': return "image/jpeg"
    if photo_bytes[:4] == b'RIFF' and photo_bytes[8:12] == b'WEBP': return "image/webp"
    return "image/jpeg"

class KieService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _upload_image(self, session: aiohttp.ClientSession, photo_bytes: bytes) -> str | None:
        mime = _detect_mime(photo_bytes)
        b64 = base64.b64encode(photo_bytes).decode("utf-8")
        data_uri = f"data:{mime};base64,{b64}"
        payload = {"base64Data": data_uri, "uploadPath": "images/tgbot"}

        async with session.post(f"{UPLOAD_BASE_URL}/api/file-base64-upload", json=payload) as resp:
            data = await resp.json()
            return data.get("data", {}).get("downloadUrl")

    async def _create_task(self, session: aiohttp.ClientSession, image_url: str, product_title: str) -> str | None:
        prompt = (
            f"A photorealistic high-quality image. The person from the input image is now naturally holding "
            f"a brand new {product_title} in their hands. Keep the original person's identity, face, clothes, "
            f"and background exactly the same as in the original photo. Integrate the device realistically."
        )
        payload = {
            "model": "nano-banana-2",
            "input": {
                "prompt": prompt,
                "image_input": [image_url],
                "aspect_ratio": "9:16",
                "output_format": "png",
                "resolution": "1K"
            }
        }
        async with session.post(f"{API_BASE_URL}/jobs/createTask", json=payload) as resp:
            data = await resp.json()
            
            # Проверка баланса: KIE возвращает ошибку о кредитах
            msg_text = str(data.get("msg", "")).lower()
            if "credit" in msg_text or data.get("code") in [402, 4003]:
                await notify_admin("🚨 <b>Внимание!</b> Закончились кредиты на балансе <b>KIE.ai</b> (Магия).")
                
            return data.get("data", {}).get("taskId") if data.get("code") == 200 else None

    async def _poll_result(self, session: aiohttp.ClientSession, task_id: str) -> str | None:
        for _ in range(60):
            await asyncio.sleep(4)
            async with session.get(f"{API_BASE_URL}/jobs/recordInfo", params={"taskId": task_id}) as resp:
                res_data = await resp.json()
                if res_data.get("code") != 200: continue
                info = res_data.get("data", {})
                if info.get("state") == "success":
                    result = json.loads(info.get("resultJson", "{}"))
                    return result.get("resultUrls", [None])[0]
                if info.get("state") == "fail": return None
        return None

    async def generate_magic_image(self, photo_bytes: bytes, product_title: str) -> str | None:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                url = await self._upload_image(session, photo_bytes)
                if not url: return None
                tid = await self._create_task(session, url, product_title)
                if not tid: return None
                return await self._poll_result(session, tid)
            except Exception as e:
                logger.exception(f"KIE Error: {e}")
                return None
