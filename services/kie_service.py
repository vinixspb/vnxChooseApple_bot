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

    @staticmethod
    def _build_prompt(product_title: str) -> str:
        """
        Строим промпт с явным визуальным описанием девайса.
        Для новых моделей (iPhone 17 Pro и новее) модель может не знать дизайн —
        поэтому описываем его словами, а не надеемся на знания AI.
        """
        title = product_title.strip()

        # ── iPhone 17 Pro / Pro Max ─────────────────────────────────────────
        if "17 Pro" in title:
            device_description = (
                "a brand new Apple iPhone 17 Pro smartphone. "
                "The phone has a rectangular aluminum unibody design. "
                "On the back there is a wide horizontal 'camera plateau' bar "
                "that spans almost the full width of the upper portion of the phone — "
                "NOT a square bump in the corner. "
                "Inside this horizontal bar, three camera lenses are arranged "
                "in a triangular layout, with the True Tone flash and LiDAR sensor "
                "positioned to the right of the lenses. "
                "The back surface below the camera plateau is smooth aluminum. "
                "The phone has squared-off flat edges."
            )

        # ── iPhone 17 (базовый) ─────────────────────────────────────────────
        elif "iPhone 17" in title and "Air" not in title:
            device_description = (
                "a brand new Apple iPhone 17 smartphone. "
                "The phone has a flat aluminum frame with a glass back. "
                "On the back there is a vertical dual-camera module on the left side. "
                "Clean minimalist design with squared-off flat edges."
            )

        # ── iPhone 17 Air ───────────────────────────────────────────────────
        elif "17 Air" in title:
            device_description = (
                "a brand new Apple iPhone 17 Air smartphone. "
                "Extremely thin profile, the thinnest iPhone ever made. "
                "Single rear camera lens. Ultra-slim flat aluminum edges."
            )

        # ── iPhone 16 Pro / Pro Max ─────────────────────────────────────────
        elif "16 Pro" in title:
            device_description = (
                "a brand new Apple iPhone 16 Pro smartphone. "
                "Titanium frame with a glass back. "
                "Square camera bump in the upper-left corner of the back "
                "containing three camera lenses arranged in a triangle, "
                "with the flash below them. Flat squared-off edges."
            )

        # ── Фолбэк для всех остальных моделей ──────────────────────────────
        else:
            device_description = f"a brand new {title} smartphone by Apple"

        return (
            f"A photorealistic high-quality image. "
            f"The person from the input image is now naturally holding "
            f"{device_description} "
            f"in their hands, screen facing the viewer. "
            f"Keep the original person's identity, face, clothes, and background "
            f"exactly the same as in the original photo. "
            f"Integrate the phone realistically with correct lighting, "
            f"reflections and shadows matching the scene. "
            f"The device must look exactly as described above — "
            f"do NOT substitute with any other phone model or design."
        )

    async def _create_task(self, session: aiohttp.ClientSession, image_url: str, product_title: str) -> str | None:
        """
        Шаг 2: создаём задачу генерации, передаём URL из шага 1.
        Возвращает taskId или None.
        """
        prompt = self._build_prompt(product_title)

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
