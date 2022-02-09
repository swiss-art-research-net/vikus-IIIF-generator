
# from PIL import Image
import requests, json, os, time, logging, sys
# from flask import Flask, request, jsonify
# from flask_cors import CORS
# from transformers import CLIPProcessor, CLIPModel, CLIPTokenizer
import asyncio
import aiohttp
import random
import traceback
import hashlib

from rich import pretty
from rich.logging import RichHandler
# from rich.console import Console
# from rich.theme import Theme
from rich import print
# console = Console(theme=Theme({"logging.level": "green"}))

from crawler import ManifestCrawler, ImageCrawler
from cache import Cache
from helpers import *
from manifest import Manifest

pretty.install()

debug = False
loggingLevel = logging.DEBUG if debug else logging.INFO

logging.basicConfig(
    level=loggingLevel,
    # format="%(message)s",
    datefmt="%X",
    handlers=[RichHandler(show_time=True, rich_tracebacks=True, tracebacks_show_locals=True)]
)
logger = logging.getLogger('rich')

#url = "https://iiif.wellcomecollection.org/presentation/v3/collections/genres"
#url = "https://iiif.wellcomecollection.org/presentation/collections/genres/Broadsides"
url = "https://iiif.wellcomecollection.org/presentation/collections/genres/Myths_and_legends"


@duration
async def main():

    cache = Cache()
    # cache.clear()
    
    manifest = Manifest(url=url)
    dataPath = createFolder("../data/{}".format(manifest.shortId))
    thumbPath = createFolder("{}/images/thumbs".format(dataPath))
    
    print(thumbPath)
    
    manifestCrawler = ManifestCrawler(
        cache=cache,
        workers=2,
        #callback=imageCrawler.addFromManifest
    )
    manifest = await manifestCrawler.crawl(manifest)
    
    imageCrawler = ImageCrawler(workers=2, path=thumbPath)
    for manifest in manifest.getFlatList(manifest):
        imageCrawler.addFromManifest(manifest)

    images = await imageCrawler.runImageWorkers()
    print(images)


    # print(manifest.tree)
    # print(thumbnails)
    print('Done')


if __name__ == "__main__":
    asyncio.run(main())

