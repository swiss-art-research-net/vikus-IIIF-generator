from typing import List
import asyncio
from imp import reload
import json
import uuid
from warnings import catch_warnings
from sklearn.metrics import consensus_score
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pathlib import Path
from aioredis import Redis
from fastapi.params import Depends
import async_timeout


import os
import math
import logging
import os
from functools import wraps
import shutil
import uuid

# from cache import Cache
from playground import create_config_json, crawlCollection, crawlImages, cache

LOGGER = logging.getLogger(__name__)

DATA_DIR = "../data"

# cache = Cache()

app = FastAPI()

origins = [
    # "http://localhost",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

InstanceManager = {}


@app.get("/")
def home():
    return {"Hello": "World"}


@app.get("/instances")
def list_instances():
    instances = []
    paths = sorted(filter(os.path.isdir, Path(DATA_DIR).iterdir()),
                   key=os.path.getmtime, reverse=True)
    for dir in paths:
        instance = {
            "id": dir.name,
            "absolutePath": dir.resolve(),
            "label": dir.name,
        }
        instances.append(instance)
    return instances


@app.get("/instances/{instance_id}")
def read_instance(instance_id: str):
    path = os.path.join(DATA_DIR, instance_id)
    if not os.path.isdir(path):
        return {"error": "Instance {} doesn't exist".format(instance_id)}, 404
    configFile = os.path.join(path, "instance.json")
    if not os.path.isfile(configFile):
        return {"error": "Instance {} doesn't have a config file".format(instance_id)}, 404
    with open(configFile, "r") as f:
        config = json.load(f)
    return config


@app.get("/instances/{instance_id}/crawlCollection")
async def crawl_collection(instance_id: str):
    config = read_instance(instance_id)
    # print(config)
    # if config["status"] != "created":
    #     return {"error": "Instance {} is already crawled".format(instance_id)}, 404

    # config["status"] = "crawling"
    # with open(os.path.join(config["path"], "instance.json"), "w") as f:
    #     f.write(json.dumps(config, indent=4))

    manifests = await crawlCollection(config["iiif_url"], instance_id)

    # config["status"] = "crawled"
    # with open(os.path.join(config["path"], "instance.json"), "w") as f:
    #     f.write(json.dumps(config, indent=4))

    # return InstanceManager[instance_id]

    config["status"] = "crawledCollection"
    config["manifests"] = len(manifests)
    with open(os.path.join(config["path"], "instance.json"), "w") as f:
        f.write(json.dumps(config, indent=4))

    InstanceManager[instance_id] = {
        "config": config,
        "manifests": manifests,
        "status": "crawledCollection",
    }

    return config


@app.get("/instances/{instance_id}/crawlImages")
async def crawl_images(instance_id: str):
    if instance_id not in InstanceManager:
        return {"error": "Instance {} doesn't exist".format(instance_id)}, 404
    config = InstanceManager[instance_id]["config"]
    if config["status"] != "crawledCollection":
        return {"error": "Instance {} is not crawled".format(instance_id)}, 404
    # config["status"] = "crawlingImages"
    # with open(os.path.join(config["path"], "instance.json"), "w") as f:
    #     f.write(json.dumps(config, indent=4))

    manifests = InstanceManager[instance_id]["manifests"]

    images = await crawlImages(manifests, instance_id)
    # print(images)

    config["status"] = "crawledImages"
    config["images"] = len(images)
    with open(os.path.join(config["path"], "instance.json"), "w") as f:
        f.write(json.dumps(config, indent=4))

    InstanceManager[instance_id] = {
        "config": config,
        "images": images,
        "manifests": manifests,
        "status": "crawledImages",
    }

    return config


@app.delete("/instances/{instance_id}")
def delete_instance(instance_id: str):
    path = os.path.join(DATA_DIR, instance_id)
    if not os.path.isdir(path):
        return {"error": "Instance {} doesn't exist".format(instance_id)}, 404
    shutil.rmtree(path)
    return {"id": instance_id, "absolutePath": path, "label": instance_id, "status": "deleted"}


@app.post("/instances")
async def create_instance(url: str, label: str = None):
    config = create_config_json(url, label)
    print(config)
    return config


@app.get("/instances/{instance_id}/events")
async def stream(req: Request, instance_id: str = "default"):
    return EventSourceResponse(subscribe( req, instance_id))

async def subscribe(req: Request, instance_id: str = "default"):
    try:
        async with cache.psub as p:
            print("start subscribe")
            try:
                await p.subscribe(instance_id)
            except Exception as e:
                print("subscribe error", e)

            print("subscribed")
            yield {"event": "open", "data": "subscribed to {}".format(instance_id)}
            while True:
                disconnected = await req.is_disconnected()
                if disconnected:
                    print(f"Disconnecting client {req.client}")
                    break
                message = await p.get_message(ignore_subscribe_messages=True)
                print("message")
                if message is not None:
                    # print(message)
                    yield {"event": "message", "data": message["data"].decode("utf-8")}
                await asyncio.sleep(0.01)
    except asyncio.CancelledError as e:
    # except Exception as e:
        print(f"Cancelled {e}")
        
    finally:
        print(f"Closing client {req.client}")
        
    await p.unsubscribe(instance_id)
    yield {"event": "close", "data": "unsubscribed from {}".format(instance_id)}

        # finally:
        #     yield {"event": "ping", "data": "ping"}
        #     await p.unsubscribe(channel)

    # yield {"event": "open", "data": "subscribed to {}".format(channel)}
    # while True:
    #     # message = await InstanceManager[channel]["pubsub"].get()
    #     yield {"event": "message", "data": "message from {}".format(channel)}
    #     await asyncio.sleep(0.3)
    # subscription = await cache.psub.subscribe(channel)
    # while await subscription.wait_message():
    #     yield {"event": "message", "data": await subscription.get()}


async def reader(channel):
    while True:
        try:
            async with async_timeout.timeout(1):
                message = await channel.get_message(ignore_subscribe_messages=True)
                if message is not None:
                    print(f"(Reader) Message Received: {message}")
                await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            pass

if __name__ == "__main__":
    uvicorn.run("apiFast:app", host="0.0.0.0", port=5000, reload=True, log_level="debug")
