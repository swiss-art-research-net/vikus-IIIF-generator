import hashlib
import requests, json, os, time, logging, sys
import asyncio
import aiohttp
import random
import time
import logging
import redis

from manifest import Manifest

class Cache:
    def __init__(self, *args, **kwargs):
        self.redis = kwargs.get('redis', redis.Redis(host='redis', port=6379))
        self.logger = kwargs.get('logger', logging.getLogger('cache'))
    
    def get(self, url):
        return self.redis.get(url)

    def clear(self):
        self.redis.flushdb()

    async def getJsonFromUrl(self,url, session, retries = 5):
        for i in range(retries):
            try:
                async with session.get(url) as response:
                    return await response.text()
            except Exception as e:
                self.logger.error(e)
                self.logger.error("retry {i} {url}" .format(i=i, url=url))
                await asyncio.sleep(1)
        return None


    async def getJson(self, url, session):
        self.logger.debug("get cache for {}".format(url))
        if self.redis.exists(url):
            self.logger.debug("cache hit")
            cached = self.redis.get(url)
            return json.loads(cached)
        else:
            self.logger.debug("cache miss")
            data = await self.getJsonFromUrl(url, session)
            if data is not None:
                self.logger.debug("cache set")
                self.redis.set(url, data)
                return json.loads(data)
            else:
                return None
class ManifestCrawler:
    def __init__(self,*args,**kwargs):
        self.url = kwargs.get('url', None)
        self.urls = kwargs.get('url', None)
        self.client = kwargs.get('client')
        self.limitRecursion = kwargs.get('limitRecursion', False)
        self.cache = kwargs.get('cache', None)
        self.semaphore = kwargs.get('semaphore', asyncio.Semaphore(self.limitRecursion and 10 or 0) )
        self.session = kwargs.get('session')
        self.logger = kwargs.get('logger', logging.getLogger('ManifestCrawler'))
        self.workers = kwargs.get('workers', 1)
        self.callback = kwargs.get('callback', None)

        self.logger.debug("init crawler")
        self.logger.debug("url: {}".format(self.url))

    async def manifestWorker(self, name, queue):
        self.logger.debug("worker {} started".format(name))
        async with aiohttp.ClientSession() as session:
            while True:
                # Get a "work item" out of the queue.
                prio, manifest = await queue.get()
                data = await self.cache.getJson(manifest.url, session)
                manifest.load(data)

                if self.callback != None and manifest.type == 'Manifest':
                    self.callback(manifest)

                if manifest.data.get('items', False):
                    for item in manifest.data.get('items'):
                        # print("{} added {}".format(name, item.get('id')))
                        child = Manifest(
                            url=item.get('id'),
                            depth=manifest.depth+1,
                            parent = manifest,
                        )
                        manifest.add(child)
                        
                        if self.limitRecursion and manifest.depth >= self.limitRecursion:
                            continue

                        if item.get('type') == 'Collection' or item.get('type') == 'Manifest':
                            queue.put_nowait((prio + 1 + random.uniform(0, 1), child))

                # Notify the queue that the "work item" has been processed.
                queue.task_done()
            
                self.logger.debug(f'{name}: {prio} {manifest.label} done with {len(manifest.children)} children, {queue.qsize()} items left')


    async def runManifestWorkers(self):
        self.logger.debug("load manifests from {}".format(self.url))
        # Create a queue that we will use to store our "workload".
        queue = asyncio.PriorityQueue()

        manifest = Manifest(url=self.url)

        queue.put_nowait((0, manifest))

        tasks = []
        for i in range(self.workers):
            task = asyncio.create_task(self.manifestWorker(f'worker-{i}', queue))
            tasks.append(task)

        await queue.join()
    
        # Cancel our worker tasks.
        for task in tasks:
            task.cancel()

        # Wait until all worker tasks are cancelled.
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error(e)
        self.logger.debug("load manifests done")
  
        return manifest

class ImageCrawler:
    def __init__(self, *args, **kwargs):
        self.client = kwargs.get('client')
        self.limitRecursion = kwargs.get('limitRecursion', False)
        self.cache = kwargs.get('cache', None)
        self.semaphore = kwargs.get('semaphore', asyncio.Semaphore(self.limitRecursion and 10 or 0) )
        self.session = kwargs.get('session')
        self.logger = kwargs.get('logger', logging.getLogger('ImageCrawler'))
        self.workers = kwargs.get('workers', 1)
        self.callback = kwargs.get('callback', None)
        self.path = kwargs.get('path', "../data")
        self.queue = asyncio.Queue()
        self.logger.debug("init crawler")
        self.tasks = []
        self.done = []
        
        self.createImageWorkers()
    
    def addFromManifest(self, manifest):
        thumbnailUrl = manifest.getThumbnail()
        print("adding {}".format(thumbnailUrl))
        if thumbnailUrl is not None:
            self.queue.put_nowait(thumbnailUrl)

    async def download(self, url, session):
        async with session.get(url) as response:
            if response.status == 200:
                self.logger.debug("downloading {}".format(url))
                data = await response.read()
                urlHash = hashlib.md5(url.encode('utf-8')).hexdigest()
                filename = urlHash + ".jpg"
                filepath = os.path.join(self.path, filename)
                with open(filepath, 'wb') as f:
                    f.write(data)
                return data, filepath
            else:
                return None

    async def imageWorker(self, name):
        self.logger.debug("imageworker {} started".format(name))
        async with aiohttp.ClientSession() as session:
            while True:
                url = await self.queue.get()
                self.logger.debug("{} downloading {}".format(name, url))
                data, filepath = await self.download(url, session)
                if data is not None:
                    self.logger.debug("{} downloaded {}".format(name, url))
                    self.done.append(filepath)
                    if self.callback != None:
                        self.callback(url, filepath)
                else:
                    self.logger.debug("{} failed to download {}".format(name, url))
                self.queue.task_done()
                
                self.logger.debug(f'{name}: {url} done, {self.queue.qsize()} items left')

    def createImageWorkers(self):
        self.logger.debug("runImageWorkers")
        # Create a queue that we will use to store our "workload".

        for i in range(self.workers):
            task = asyncio.create_task(self.imageWorker(f'worker-{i}'))
            self.tasks.append(task)
            print("task {}".format(task))

    async def run(self):
        await self.queue.join()

        # Cancel our worker tasks.
        for task in self.tasks:
            task.cancel()

        # Wait until all worker tasks are cancelled.
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.logger.debug("load images done")      
        
        return self.done
        