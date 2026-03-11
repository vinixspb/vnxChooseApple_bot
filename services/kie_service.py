import aiohttp
import asyncio
import logging
import json
import base64

logger = logging.getLogger(__name__)

UPLOAD_BASE_URL = "https://kieai.redpandaai.co"
API_BASE_URL    = "https://api.kie.ai/api/v1"


def _detect_mime(photo_bytes: bytes) -> str:
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

    async def _upload_image(self, session: aiohttp.ClientSession, photo_bytes: bytes, label: str = "") -> str | None:
        """Загружаем фото в KIE File Upload API, возвращаем downloadUrl."""
        mime = _detect_mime(photo_bytes)
        b64 = base64.b64encode(photo_bytes).decode("utf-8")
        data_uri = f"data:{mime};base64,{b64}"

        logger.info(f"KIE upload [{label}] → mime={mime}, b64_len={len(b64)}")

        async with session.post(
            f"{UPLOAD_BASE_URL}/api/file-base64-upload",
            json={"base64Data": data_uri, "uploadPath": "images/tgbot"}
        ) as resp:
            raw = await resp.text()
            logger.info(f"KIE upload [{label}] response: {raw[:200]}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"KIE upload [{label}]: не JSON: {raw[:200]}")
                return None

            if not data.get("success") and data.get("code") != 200:
                logger.error(f"KIE upload [{label}] failed: {data}")
                return None

            url = data.get("data", {}).get("downloadUrl")
            if not url:
                logger.error(f"KIE upload [{label}]: downloadUrl отсутствует")
                return None

            logger.info(f"KIE upload [{label}] success → {url[:80]}")
            return url

    @staticmethod
    def _build_prompt(product_title: str, has_product_ref: bool) -> str:
        """
        Строим промпт.
        Если есть референс-фото товара (has_product_ref=True) — просим модель
        взять девайс ИМЕННО с той картинки, не придумывать.
        Если референса нет — описываем дизайн словами.
        """
        title = product_title.strip()

        if has_product_ref:
            # Второй элемент image_input[] — это фото товара.
            # Говорим модели явно: возьми девайс оттуда.
            device_instruction = (
                f"The exact device to place in the person's hands is shown "
                f"in the SECOND reference image — use that device precisely as-is, "
                f"including its exact color, shape, camera layout, and design details. "
                f"Do NOT substitute it with any other phone model or generation. "
                f"The product is: {title}."
            )
        else:
            # Фолбэк: описываем дизайн словами
            if "17 Pro" in title:
                device_instruction = (
                    f"Place a brand new Apple iPhone 17 Pro in the person's hands. "
                    f"The phone has a horizontal 'camera plateau' bar spanning the full "
                    f"width of the upper back — NOT a square bump in the corner. "
                    f"Three camera lenses in triangular layout inside the bar, "
                    f"flash and LiDAR to the right of the lenses. Flat aluminum frame."
                )
            elif "iPhone 17" in title and "Air" not in title:
                device_instruction = (
                    f"Place a brand new Apple iPhone 17 in the person's hands. "
                    f"Flat aluminum frame, glass back, vertical dual-camera on the left."
                )
            elif "17 Air" in title:
                device_instruction = (
                    f"Place a brand new Apple iPhone 17 Air in the person's hands. "
                    f"Extremely thin profile, single rear camera, ultra-slim aluminum edges."
                )
            elif "16 Pro" in title:
                device_instruction = (
                    f"Place a brand new Apple iPhone 16 Pro in the person's hands. "
                    f"Titanium frame, square camera bump upper-left with three lenses in triangle."
                )
            else:
                device_instruction = (
                    f"Place a brand new {title} in the person's hands."
                )

        return (
            f"A photorealistic high-quality composited image. "
            f"The FIRST reference image shows the person — keep their identity, "
            f"face, clothes, pose, and background exactly the same. "
            f"{device_instruction} "
            f"The person is naturally holding the device with the BACK facing the viewer "
            f"— the camera system must be clearly visible, screen facing away. "
            f"Integrate the device realistically: correct perspective, lighting, "
            f"reflections and shadows matching the scene. "
            f"Apply very subtle, natural beauty retouching to the person face only: "
            f"smooth minor skin imperfections, remove any visible blemishes, cold sores "
            f"or temporary skin issues, gently even out skin tone — keep it realistic "
            f"and natural, not plastic or over-processed. "
            f"Final result must look like a professional lifestyle photograph."
        )

    async def _create_task(
        self,
        session: aiohttp.ClientSession,
        user_photo_url: str,
        product_image_url: str | None,
        product_title: str,
    ) -> str | None:
        has_ref = bool(product_image_url)

        # image_input: сначала фото человека, потом (если есть) фото товара
        image_inputs = [user_photo_url]
        if product_image_url:
            image_inputs.append(product_image_url)

        prompt = self._build_prompt(product_title, has_ref)
        logger.info(
            f"KIE createTask → refs={len(image_inputs)}, "
            f"has_product_ref={has_ref}, prompt_len={len(prompt)}"
        )

        payload = {
            "model": "nano-banana-2",
            "input": {
                "prompt": prompt,
                "image_input": image_inputs,
                "aspect_ratio": "9:16",
                "output_format": "png",
                "resolution": "1K",
            }
        }

        async with session.post(f"{API_BASE_URL}/jobs/createTask", json=payload) as resp:
            raw = await resp.text()
            logger.info(f"KIE createTask response: {raw[:300]}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"KIE createTask: не JSON: {raw[:300]}")
                return None

            if data.get("code") == 402:
                logger.error("KIE: недостаточно кредитов — пополни баланс на kie.ai")
                raise RuntimeError("CREDITS_INSUFFICIENT")

            if data.get("code") != 200:
                logger.error(f"KIE createTask Error: {data}")
                return None

            task_id = data.get("data", {}).get("taskId")
            if not task_id:
                logger.error(f"KIE createTask: taskId отсутствует: {data}")
                return None

            logger.info(f"KIE task created → {task_id}")
            return task_id

    async def _poll_result(self, session: aiohttp.ClientSession, task_id: str) -> str | None:
        for attempt in range(60):
            await asyncio.sleep(4)
            async with session.get(
                f"{API_BASE_URL}/jobs/recordInfo", params={"taskId": task_id}
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
                logger.error(f"KIE: resultUrls пуст: {result}")
                return None

            if state == "fail":
                logger.error(f"KIE Task Failed: {info.get('failMsg')}")
                return None

        logger.error("KIE: таймаут поллинга (60 × 4s)")
        return None

    async def generate_magic_image(
        self,
        user_photo_bytes: bytes,
        product_title: str,
        product_image_bytes: bytes | None = None,
    ) -> str | None:
        """
        Генерация. Шаги:
          1. Загрузить фото пользователя → URL
          2. Загрузить фото товара → URL  (если передан)
          3. Создать задачу с обоими URL в image_input[]
          4. Поллинг результата
        """
        if not self.api_key:
            logger.error("KIE: api_key не задан")
            return None

        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                user_url = await self._upload_image(session, user_photo_bytes, label="user")
                if not user_url:
                    return None

                product_url = None
                if product_image_bytes:
                    product_url = await self._upload_image(
                        session, product_image_bytes, label="product"
                    )
                    # Если не удалось загрузить товар — работаем без него (не фатально)
                    if not product_url:
                        logger.warning("KIE: фото товара не загружено, продолжаем без референса")

                task_id = await self._create_task(
                    session, user_url, product_url, product_title
                )
                if not task_id:
                    return None

                return await self._poll_result(session, task_id)

            except RuntimeError:
                raise   # пробрасываем CREDITS_INSUFFICIENT наверх
            except Exception as e:
                logger.exception(f"KIE Exception: {e}")
                return None
