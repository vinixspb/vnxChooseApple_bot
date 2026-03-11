import aiohttp
import asyncio
import logging
import json
import base64

logger = logging.getLogger(__name__)

class KieService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.kie.ai/api/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def generate_magic_image(self, photo_bytes: bytes, product_title: str) -> str:
        """Генерация изображения через nano-banana-2 с поллингом результата."""
        if not self.api_key:
            return None

        # Конвертация в base64
        base64_image = base64.b64encode(photo_bytes).decode('utf-8')
        data_uri = f"data:image/jpeg;base64,{base64_image}"

        # Промпт для Nano-Banana-2
        prompt = (
            f"A photorealistic high-quality image. The person from the input image is now naturally holding a brand new {product_title} in their hands. "
            f"Keep the original person's identity, face, clothes, and background exactly the same as the original photo. "
            f"Integrate the {product_title} realistically with correct lighting."
        )

        payload = {
            "model": "nano-banana-2",
            "input": {
                "prompt": prompt,
                "image_input": [data_uri],
                "aspect_ratio": "9:16",
                "output_format": "png",
                "image_size": "auto"
            }
        }

        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                # 1. Создание задачи
                async with session.post(f"{self.base_url}/jobs/createTask", json=payload) as resp:
                    data = await resp.json()
                    if data.get("code") != 200:
                        logger.error(f"KIE Error: {data}")
                        return None
                    task_id = data.get("data", {}).get("taskId")

                if not task_id: return None

                # 2. Поллинг результата
                for _ in range(60): # Ждем до 3 минут
                    await asyncio.sleep(4)
                    async with session.get(f"{self.base_url}/jobs/recordInfo?taskId={task_id}") as r_resp:
                        res_data = await r_resp.json()
                        if res_data.get("code") != 200: continue
                        
                        info = res_data.get("data", {})
                        if info.get("state") == "success":
                            res_json = json.loads(info.get("resultJson", "{}"))
                            return res_json.get("resultUrls", [None])[0]
                        elif info.get("state") == "fail":
                            logger.error(f"KIE Task Failed: {info.get('failMsg')}")
                            return None
            except Exception as e:
                logger.error(f"KIE Network Exception: {e}")
                return None
        return None
