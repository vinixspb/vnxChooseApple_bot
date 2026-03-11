import aiohttp
import asyncio
import logging
import json
import base64

logger = logging.getLogger(__name__)


def _detect_mime(photo_bytes: bytes) -> str:
    """Определяем тип файла по magic bytes, не доверяем Telegram."""
    if photo_bytes[:4] == b'\x89PNG':
        return "image/png"
    if photo_bytes[:2] == b'\xff\xd8':
        return "image/jpeg"
    if photo_bytes[:4] == b'RIFF' and photo_bytes[8:12] == b'WEBP':
        return "image/webp"
    # Фолбэк — Telegram почти всегда отдаёт JPEG
    return "image/jpeg"


class KieService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.kie.ai/api/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def generate_magic_image(self, photo_bytes: bytes, product_title: str) -> str:
        if not self.api_key:
            logger.error("KIE: api_key не задан")
            return None

        mime = _detect_mime(photo_bytes)
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        # nano-banana-2 принимает чистый base64 БЕЗ data URI префикса
        # Если снова упадёт с 500 — раскомментируй строку data_uri и замени ниже
        # data_uri = f"data:{mime};base64,{base64_image}"

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
                "image_input": [base64_image],   # чистый base64, без data: префикса
                "aspect_ratio": "9:16",
                "output_format": "png",
            }
        }

        # Логируем payload БЕЗ base64 — чтобы не засорять логи
        logger.info(
            f"KIE createTask → model=nano-banana-2, "
            f"mime={mime}, b64_len={len(base64_image)}, "
            f"prompt_len={len(prompt)}"
        )

        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                # ── 1. Создание задачи ──────────────────────────────────────
                async with session.post(
                    f"{self.base_url}/jobs/createTask", json=payload
                ) as resp:
                    raw = await resp.text()
                    logger.info(f"KIE createTask raw response: {raw[:300]}")

                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.error(f"KIE: ответ не JSON: {raw[:300]}")
                        return None

                    if data.get("code") != 200:
                        logger.error(f"KIE createTask Error: {data}")
                        return None

                    task_id = data.get("data", {}).get("taskId")

                if not task_id:
                    logger.error("KIE: taskId не получен")
                    return None

                logger.info(f"KIE task created: {task_id}")

                # ── 2. Поллинг результата ───────────────────────────────────
                for attempt in range(60):  # до 4 минут (60 × 4s)
                    await asyncio.sleep(4)
                    async with session.get(
                        f"{self.base_url}/jobs/recordInfo",
                        params={"taskId": task_id}
                    ) as r_resp:
                        res_data = await r_resp.json()

                    if res_data.get("code") != 200:
                        logger.warning(f"KIE poll [{attempt}]: code={res_data.get('code')}")
                        continue

                    info = res_data.get("data", {})
                    state = info.get("state")
                    logger.info(f"KIE poll [{attempt}]: state={state}")

                    if state == "success":
                        result_json = json.loads(info.get("resultJson", "{}"))
                        urls = result_json.get("resultUrls", [])
                        if urls:
                            return urls[0]
                        logger.error(f"KIE: state=success но resultUrls пуст: {result_json}")
                        return None

                    if state == "fail":
                        logger.error(f"KIE Task Failed: {info.get('failMsg')}")
                        return None

                logger.error("KIE: таймаут поллинга (60 попыток)")
                return None

            except Exception as e:
                logger.exception(f"KIE Network Exception: {e}")
                return None
