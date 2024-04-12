import re
import os
import json
from urllib.parse import quote as safe_text_url

import boto3
import aiohttp
import fastapi  # type: ignore
from fastapi import *
from fastapi.responses import *

import config

from core.lyrics import Lyrics, Tokens
from core.utils import JSONResponse
from core.db import Database

router = APIRouter(
    prefix="/lyrics",
)

db = Database(config.DATABASE_HOST, config.DATABASE_AUTH)
tokens = Tokens(**config.LYRIC_TOKENS)
lyrics = Lyrics(tokens, db)


s3 = boto3.client("s3", endpoint_url=config.R2_ENDPOINT_URL, aws_access_key_id=config.R2_ACCESS_KEY_ID,
                  aws_secret_access_key=config.R2_SECRET_ACCESS_KEY)
cdn_url = f'{config.R2_HOST}/lyrics'

for i in ['lyric-images', 'shazam-lyrics']:
    try:
        os.mkdir(f'./{i}')
    except:
        continue


def query_check(q):
    q = q.replace('+', ' ').strip()

    regex_res = re.findall(r'\(.*\)', q)
    for i in regex_res:
        q = q.replace(i, '')

    return q


@router.get("/", include_in_schema=False)
async def root():
    return PlainTextResponse("Hello World! Version v3 lyrics")


@router.get("/search")
async def search(q: str):
    q = query_check(q)

    if not q:
        return JSONResponse({'error': {'code': 400}, 'message': 'No query provided.'}, status_code=400)

    res = await lyrics.get(q)

    if not res:
        return JSONResponse({'title': None, 'artist': None, 'lyrics': None, 'images': {}}, status_code=404)

    if not res.title:
        return JSONResponse({'title': None, 'artist': None, 'lyrics': None, 'images': {}}, status_code=404)

    res_title = res.title.replace(" ", "_").replace("/", "")
    res_artist = (res.artist or "unknown").replace(" ", "_").replace("/", "")

    if res._images_saved_before and res.images:
        images = res.images
    else:
        images = {}

        try:
            if not os.path.exists(f'./lyric-images/{res_title}-{res_artist}'):
                os.mkdir(f'./lyric-images/{res_title}-{res_artist}')

            for image_name, url in res.images.items():
                try:
                    if url and image_name:
                        async with aiohttp.ClientSession() as sess:
                            async with sess.get(url) as resp:
                                image_content = await resp.read()

                        with open(f'./lyric-images/{res_title}-{res_artist}/{image_name}.jpg', 'wb') as f:
                            f.write(image_content)

                        s3.upload_file(
                            f'./lyric-images/{res_title}-{res_artist}/{image_name}.jpg',
                            config.R2_BUCKET,
                            f'lyrics/{res_title}-{res_artist}/{image_name}.jpg'
                        )

                        x = safe_text_url(res_title + '-' + res_artist)

                        images[image_name] = f'{x}/{image_name}.jpg'

                        os.remove(f'./lyric-images/{res_title}-{res_artist}/{image_name}.jpg')
                except:
                    continue

            os.remove(f'./lyric-images/{res_title}-{res_artist}')
        except:
            pass

    i = {}

    for name, endpoint in images.items():
        url = f'https://{cdn_url}/{endpoint}'
        url = url.replace(f'https://{cdn_url}/https://{cdn_url}/', f'https://{cdn_url}/')  # idk why this happens
        i[name] = url

    title = res.title
    lyric = str(res)
    artist = res.artist

    d = {'title': str(title), 'artist': str(artist), 'lyrics': lyric, 'images': i}
    db_d = d.copy()
    db_d['raw_dict'] = res.raw_dict
    db_d['q'] = q

    try:
        await lyrics.save(db_d)
    except:
        pass

    return JSONResponse(d)


@router.get("/suggest")
async def suggest_tracks(q: str, amount: int = 10):
    q = query_check(q)

    if not q:
        return JSONResponse({'error': {'code': 400}, 'message': 'No query provided.'}, status_code=400)

    if amount < 1 or amount > 20:
        return JSONResponse({'error': {'code': 400}, 'message': 'amount must be between 1 and 20.'}, status_code=400)

    res = await lyrics.suggest(q, amount)

    return JSONResponse(res)


def init_router(app):
    return router
