import asyncio
import io

import aiohttp

from .dataclass import *


class GenerateStyleArt:
    URL = "https://api.luan.tools/api"

    def __init__(self, s3, key: str):
        self.s3, self.bucket, self.host = s3

        self.key = key

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    async def get_styles(self, *, raw: bool = False, return_js: bool = False) -> list[Style] | dict[str, list[Style]]:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(self.URL + "/styles/", headers=self._get_headers()) as resp:
                js = await resp.json()

        if return_js:
            return js

        if raw:
            return [Style(**style) for style in js]

        d = {}

        for style in js:
            if style["model_type"] not in d:
                d[style["model_type"]] = []

            d[style["model_type"]].append(Style(**style))

        return d

    async def get_style_from_name(self, name: str, *, lower: bool = True) -> Style | None:
        styles = await self.get_styles(raw=True)

        for style in styles:
            if lower:
                if style.name.lower() == name.lower():
                    return style
            else:
                if style.name == name:
                    return style

        return None

    async def get_style(self, _id: int) -> Style | None:
        styles = await self.get_styles(raw=True)

        for style in styles:
            if style.id == _id:
                return style

        return None

    async def create_task(self):
        data = {"use_target_image": False}

        async with aiohttp.ClientSession() as sess:
            async with sess.post(self.URL + "/tasks/", json=data, headers=self._get_headers()) as resp:
                js = await resp.json()

        return js

    async def update_task(self, task_id: str, prompt: str, style: Style, *, height: int = None, width: int = None,
                          target_image_weight: float = 0.5):
        height = height or 1568
        width = width or 960

        data = {
            "input_spec": {
                "prompt": prompt,
                "style": style.id,
                "height": height,
                "width": width,
                "target_image_weight": target_image_weight
            }
        }

        async with aiohttp.ClientSession() as sess:
            async with sess.put(self.URL + f"/tasks/{task_id}", json=data, headers=self._get_headers()) as resp:
                js = await resp.json()

        return js

    async def get_task(self, task_id: str):
        async with aiohttp.ClientSession() as sess:
            async with sess.get(self.URL + f"/tasks/{task_id}", headers=self._get_headers()) as resp:
                js = await resp.json()

        return js

    async def _upload_to_cdn(self, images: list[GeneratedImage]):
        for i, image in enumerate(images):
            original_url = image.result
            img_id = image.id

            async with aiohttp.ClientSession() as sess:
                async with sess.get(original_url) as resp:
                    data = await resp.read()

            # Upload to S3
            self.s3.upload_fileobj(
                io.BytesIO(data),
                Bucket=self.bucket,
                Key=f"art/style/{image.id}/{i+1}.png"
            )

            image.result = f"{self.host}/art/style/{img_id}/{i+1}.png"

        return images

    async def generate(self, prompt: str, style: Style, n: int = 1, *, height: int = None,
                       width: int = None) -> list[GeneratedImage]:
        images = []

        for i in range(n):
            task = await self.create_task()
            await self.update_task(task["id"], prompt, style, height=height, width=width)

            while task["state"] not in ["completed", "failed"]:
                task = await self.get_task(task["id"])
                await asyncio.sleep(1)

            images.append(GeneratedImage(**task))

        images = await self._upload_to_cdn(images)

        return images
