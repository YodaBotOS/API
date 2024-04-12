import os
import json
import asyncio

import sentry_sdk
from fastapi import FastAPI as App
from fastapi.responses import Response
from api_analytics.fastapi import Analytics

import config

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = config.GOOGLE_CREDENTIALS_PATH

# from .db import init_db
from routes import init_router


def setup_sentry():
    return
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,

        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production,
        traces_sample_rate=1.0,
    )


def on_startup(app: App):
    async def _():
        # db = await init_db(sync=False)
        #
        # with open('assets/schema.sql', 'r') as f:
        #     query = f.read()
        #
        # async with db.acquire() as conn:
        #     await conn.execute(query)

        pass

    return _


def on_shutdown(app: App):
    async def _():
        # await app.db.close()
        pass

    return _


def make_tmp_dir(app: App):
    try:
        os.mkdir("tmp")
    except FileExistsError:
        pass


def add_routes(app: App):
    routes = [("1", init_router)]

    for name, route in routes:
        r = route(app)
        app.include_router(r, tags=[f"v{name}"], include_in_schema=False)


def add_analytics(app: App):
    app.add_middleware(Analytics, api_key=config.API_ANALYTICS_KEY)


def init_database(app: App):
    # app.db = init_db(sync=True)
    pass


def callback(app: App):
    funcs = (init_database, add_routes, make_tmp_dir, add_analytics)

    for func in funcs:
        func(app)

    return app
