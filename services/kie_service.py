import aiohttp
import asyncio
import logging
import json
import base64

logger = logging.getLogger(__name__)

# Два разных хоста — это задокументировано в KIE docs
UPLOAD_BASE_URL = "https://kieai.redpandaai.co"   # File Upload API
API_BASE_URL    = "https://api.kie.ai/api/v1"      # Task API


def _detect_mime(photo_bytes: bytes) -> str:
    """Определяем тип по magic bytes."""
    if photo_bytes[:4] == b'\x89PNG':
        return "image/png"
    if photo_bytes[:2] == b'\xff\xd8':
        return "image/jpeg"
    if photo_bytes[:4] == b'RIFF' and photo_bytes[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"


class KieService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _upload_image(self, session: aiohttp.ClientSession, photo_bytes: bytes) -> str | None:
        """
        Шаг 1: загружаем фото через File Upload API.
        Возвращает downloadUrl (публичный URL файла) или None.

        Endpoint: POST https://kieai.redpandaai.co/api/file-base64-upload
        Принимает: data URI формат (data:image/jpeg;base64,...)
        Возвращает: { data: { downloadUrl: "https://tempfile.redpandaai.co/..." } }
        """
        mime = _detect_mime(photo_bytes)
        b64 = base64.b64encode(photo_bytes).decode("utf-8")
        data_uri = f"data:{mime};base64,{b64}"

        payload = {
            "base64Data": data_uri,
            "uploadPath": "images/tgbot"
        }

        logger.info(f"KIE upload → mime={mime}, b64_len={len(b64)}")

        async with session.post(
            f"{UPLOAD_BASE_URL}/api/file-base64-upload",
            json=payload
        ) as resp:
            raw = await resp.text()
            logger.info(f"KIE upload raw response: {raw[:300]}")

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"KIE upload: ответ не JSON: {raw[:300]}")
                return None

            if not data.get("success") and data.get("code") != 200:
                logger.error(f"KIE upload failed: {data}")
                return None

            url = data.get("data", {}).get("downloadUrl")
            if not url:
                logger.error(f"KIE upload: downloadUrl не получен: {data}")
                return None

            logger.info(f"KIE upload success → {url}")
            return url

    async def _create_task(self, session: aiohttp.ClientSession, image_url: str, product_title: str) -> str | None:
        """
        Шаг 2: создаём задачу генерации, передаём URL из шага 1.
        Возвращает taskId или None.
        """
        prompt = (
            f"A photorealistic high-quality image. "
            f"The person from the input image is now naturally holding "
            f"a brand new {product_title} in their hands. "
            f"Keep the original person's identity, face, clothes, and background "
            f"exactly the same as in the original photo. "
            f"Integrate the {product_title} realistically with correct lighting and shadows."
        )

        payload = {
            "model": "nano-banana-2",
            "input": {
                "prompt": prompt,
                "image_input": [image_url],   # URL из File Upload API
                "aspect_ratio": "9:16",
                "output_format": "png",
                "resolution": "1K"
            }
        }

        logger.info(f"KIE createTask → image_url={image_url[:60]}...")

        async with session.post(
            f"{API_BASE_URL}/jobs/createTask",
            json=payload
        ) as resp:
            raw = await resp.text()
            logger.info(f"KIE createTask raw response: {raw[:300]}")

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"KIE createTask: ответ не JSON: {raw[:300]}")
                return None

            if data.get("code") != 200:
                logger.error(f"KIE createTask Error: {data}")
                return None

            task_id = data.get("data", {}).get("taskId")
            if not task_id:
                logger.error(f"KIE createTask: taskId не получен: {data}")
                return None

            logger.info(f"KIE task created → {task_id}")
            return task_id

    async def _poll_result(self, session: aiohttp.ClientSession, task_id: str) -> str | None:
        """
        Шаг 3: ждём результата поллингом.
        Возвращает URL готового изображения или None.
        """
        for attempt in range(60):   # до 4 минут (60 x 4s)
            await asyncio.sleep(4)

            async with session.get(
                f"{API_BASE_URL}/jobs/recordInfo",
                params={"taskId": task_id}
            ) as resp:
                res_data = await resp.json()

            if res_data.get("code") != 200:
                logger.warning(f"KIE poll [{attempt}]: code={res_data.get('code')}")
                continue

            info  = res_data.get("data", {})
            state = info.get("state")
            logger.info(f"KIE poll [{attempt}]: state={state}")

            if state == "success":
                result = json.loads(info.get("resultJson", "{}"))
                urls = result.get("resultUrls", [])
                if urls:
                    return urls[0]
                logger.error(f"KIE: state=success но resultUrls пуст: {result}")
                return None

            if state == "fail":
                logger.error(f"KIE Task Failed: {info.get('failMsg')}")
                return None

        logger.error("KIE: таймаут поллинга (60 попыток x 4s)")
        return None

    async def generate_magic_image(self, photo_bytes: bytes, product_title: str) -> str | None:
        """
        Публичный метод. Три шага:
          1. Загрузить фото -> получить URL
          2. Создать задачу генерации с этим URL
          3. Поллинг до получения результата
        """
        if not self.api_key:
            logger.error("KIE: api_key не задан")
            return None

        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                # Шаг 1
                image_url = await self._upload_image(session, photo_bytes)
                if not image_url:
                    return None

                # Шаг 2
                task_id = await self._create_task(session, image_url, product_title)
                if not task_id:
                    return None

                # Шаг 3
                return await self._poll_result(session, task_id)

            except Exception as e:
                logger.exception(f"KIE Exception: {e}")
                return None
