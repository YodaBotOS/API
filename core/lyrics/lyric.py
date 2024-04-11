import typing, re, asyncio, os, aiohttp, json, parsel, random, string, asyncpg
from lyricsgenius import Genius
from .dataclass import Lyric
from .baseclass import Tokens
from shazamio import Shazam
from core.spotify_api import Client as SpotifyClient
from urllib.parse import quote_plus
from core.db import Database

parse_text_for_url = quote_plus


class Lyrics:
    """
    The Lyrics class.

    Parameters
    ----------
    tokens: Optional[:class:`Token`]
        The Token class, this is used to authenticate to APIs.
    """

    def __init__(self, tokens: typing.Optional[Tokens] = None, psql=None, redis=None, *, loop=None):
        self.loop = loop or asyncio.get_event_loop()

        self.tokens = tokens
        
        self.genius: Genius = None

        if hasattr(tokens, 'genius'):
            self.genius: Genius = Genius(tokens.genius, verbose=False)

        self.spotify: SpotifyClient = None

        if hasattr(tokens, 'spotify'):
            self.spotify: SpotifyClient = SpotifyClient(tokens.spotify['id'], tokens.spotify['secret'])

        # if hasattr(tokens, 'musixmatch'):
        # self.musixmatch = Musixmatch(tokens.musixmatch)
        # else:
        # self.musixmatch = None

        self.shazam = Shazam()

        self.cache = {}

        self.redis = redis
        self.psql: Database = psql

    async def log(self, msg, *, quiet=True):
        print(msg)

    async def _get_genius(self, query: str):
        async with aiohttp.ClientSession() as sess:
            async with sess.get('https://some-random-api.ml/lyrics', params={'title': query}) as resp:
                js = await resp.json()

                title = js['title']
                artist = js['author']

                lyrics = js['lyrics']

                try:
                    img = js['thumbnail']['genius']
                except Exception as e:
                    img = None

        if not lyrics:
            return None

        return lyrics, title, artist, img

    async def _get_google(self, query: str):
        if not query.endswith("lyrics") and not query.endswith("lyric"):
            query += ' lyrics'

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get('https://google.com/search', params={'q': query}) as resp:
                    html_content = (await resp.read()).decode()
        except:
            return None

        selector = parsel.Selector(text=html_content)

        s = ''

        try:
            res = selector.xpath('//div[contains(@class, "ujudUb") or @jsname = "U8S5sf"]/text()').getall()
        except:
            return None
        else:
            res = '\n'.join(res)

        if not res:
            return None

        for elem in res:
            s += (elem + '\n')

        try:
            title = selector.xpath('//h2[@data-attrid = "title"]/text()').getall()
        except:
            title = None
        else:
            title = '\n'.join(title)

        try:
            artist = selector.xpath(
                '//span[@data-ved = "2ahUKEwiX25qB3ufyAhXv7XMBHSlnBcUQ2kooAXoECBAQAg"]/text()').getall()
        except:
            artist = None
        else:
            artist = '\n'.join(artist)

        return s, title, artist

    async def _get_musixmatch(self, query: str):
        query = str(query)

        # Do scrap search

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(f'https://www.musixmatch.com/search/{quote_plus(query)}') as resp:
                    html_content = (await resp.read()).decode()
        except:
            return None

        selector = parsel.Selector(text=html_content)

        s = ''

        res = selector.xpath('//a[@class = "title"]/@href').get()

        if not res:
            return None

        track_uri = res[0]

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(f'https://www.musixmatch.com/search/{quote_plus(query)}') as resp:
                    html_content = (await resp.read()).decode()
        except:
            return None

        selector = parsel.Selector(text=html_content)

        try:
            lyrics = selector.xpath('//span[@class = "lyrics__content__ok"]/text()').getall()
        except:
            return None
        else:
            lyrics = '\n'.join(lyrics)

        if not lyrics:
            return None

        for elem in res:
            s += (elem + '\n')

        try:
            title = selector.xpath('//h1[@class = "mxm-track-title__track "]/text()').getall()
        except:
            title = None
        else:
            title = '\n'.join(title).replace('Lyrics', '').strip('\n')

        try:
            artist = selector.xpath('//a[contains(@class, "mxm-track-title__artist")]/text()').getall()
        except:
            artist = None
        else:
            artist = '\n'.join(artist)

        return s, title, artist

    async def _get_async_musixmatch(self, query: str):
        search = str(query)

        preview_url = None

        try:
            js = await self.shazam.search_track(search, limit=1)

            try:
                preview_url = js['tracks']['hits'][0]['stores']['apple']['previewurl']
            except:
                if self.spotify:
                    js = await (await self.spotify.http.request("GET", "/search",
                                                                params={'q': search, 'type': 'track', 'limit': 1,
                                                                        'market': 'US', 'offset': 0})).json()
                    try:
                        preview_url = js['tracks']['items'][0]['preview_url']
                    except:
                        pass
                else:
                    pass

            async with aiohttp.ClientSession() as sess:
                async with sess.get(preview_url) as resp:
                    bytes_content = await resp.read()

            s = ''.join(random.choices(string.ascii_uppercase + string.digits, k=random.randint(10, 50)))

            with open(f'./shazam-lyrics/{s}.mp3', 'wb') as f:
                f.write(bytes_content)

            _js = await self.shazam.recognize_song('./shazam-lyrics/' + s + '.mp3')

            os.remove('./shazam-lyrics/' + s + '.mp3')

            # print(js)

            lyrics = list(filter(lambda t: t[0][1] == 'LYRICS', [list(x.items()) for x in _js['track']['sections']]))

            try:
                lyrics = '\n'.join(lyrics[1][1])
            except:
                lyrics = '\n'.join(lyrics[0][1][1])

            return lyrics, _js, js
        except Exception as e:
            return None

    @property
    def _get_async_google(self):
        return self._get_google

    @property
    def _get_async_genius(self):
        return self._get_genius

    @property
    def _get_async_scrapping_musixmatch(self):
        return self._get_musixmatch

    def parse_psql_data(self, data, *, reverse=False, ready=False):
        d = data.copy()

        if reverse:
            d['images']['background'] = data['images'].get('background') or ''
            d['images']['track'] = data['images'].get('track') or ''
        else:
            d['images'] = {}

            d['images']['track'] = data['track_img']
            d['images']['background'] = data['bg_img']

            del d['track_img']
            del d['bg_img']

        if ready:
            try:
                del d['raw_dict']
            except:
                pass

            try:
                del d['q']
            except:
                pass

        return d

    async def get_from_cache(self, query: str) -> dict:
        # if self.redis is None:
        #     return None
        #
        # x = await self.redis.get(query.lower())
        #
        # if x:
        #     return json.loads(x.decode())

        d = await self.psql.query('SELECT * FROM lyrics WHERE q = $1', query.lower())
        d = d.results[0].result

        if not d:
            return dict() 
        else:
            d = d[0]

        d = dict(d)

        if not d:
            return dict()

        d = self.parse_psql_data(d)

        return d

    async def parse_musixmatch(self, musixmatch):
        lyrics, js, old_js = musixmatch

        track = js['track']

        title = track['title']

        try:
            artist = self._get_musixmatch_artist(track)['name']
        except Exception as e:
            artist = None

        if not artist:
            try:
                artist = ', '.join([x['name'] for x in old_js['tracks']['items'][0]['artists']])
            except Exception as e:
                artist = None

            if not artist:
                try:
                    if self.spotify:
                        __js = await (await self.spotify.http.request("GET", "/search",
                                                                      params={'q': title, 'type': 'track', 'limit': 1,
                                                                              'market': 'US', 'offset': 0})).json()
                        try:
                            artist = ', '.join([x['name'] for x in __js['tracks']['items'][0]['artists']])
                        except Exception as e:
                            artist = None
                    else:
                        artist = None
                except Exception as e:
                    artist = None

        return lyrics, title, artist, js, track

    async def _get_async_evan_lol(self, query: str):
        async with aiohttp.ClientSession() as sess:
            async with sess.get('https://evan.lol/lyrics/search/top', params={'q': query}) as resp:
                js = await resp.json()
                return js['name'], ', '.join([x['name'] for x in js['artists']]), js['lyrics']

    def _get_musixmatch_artist(self, track) -> typing.Optional[dict]:
        for d in track['sections']:
            if d['type'] == 'ARTIST':
                return d

    async def get(self, query: str, *, cache=True):
        query = str(query)

        await self.log('Searching for Lyrics with query %s' % query)

        cac = await self.get_from_cache(query)
        if cac:
            if cache:
                await self.log('Query %s exists in cache. Returning cache instead.' % query)
                cac['images'] = cac.get('images') or {}
                return Lyric(**cac, images_saved_before=bool(cac.get('images')))
            else:
                await self.log('Query %s exists in cache, but forced to not use cache result.' % cache)

        js = None
        img = None

        try:
            musixmatch = await self._get_async_musixmatch(query)
        except Exception as e:
            musixmatch = None

        if musixmatch:
            lyrics, title, artist, js, track = await self.parse_musixmatch(musixmatch)

            await self.log(
                "*Async* Musixmatch works with query %s. Using *async* musixmatch with result:\n- Title: %s\n- "
                "Artist: %s" % (query, title, artist))
        else:
            try:
                genius = await self._get_async_genius(query)  # type: ignore

                if genius:
                    lyrics, title, artist, img = genius

                    await self.log(
                        "Genius works with query %s. Using genius with result:\n- Title: %s\n- Artist: %s" % (
                            query, title, artist))
                else:
                    genius = None
                    img = None
            except Exception as e:
                genius = None
                img = None

            if genius is None:
                try:
                    evan_lol = await self._get_async_evan_lol(query)
                except Exception as e:
                    evan_lol = None, None, None
                else:
                    title, artist, lyrics = evan_lol

                if not evan_lol or not evan_lol[2]:
                    try:
                        ggl = await self._get_async_google(query)  # type: ignore
                    except:
                        ggl = None

                    if ggl:
                        lyrics, title, artist = ggl

                        await self.log(
                            "Google works with query %s. Using Google with result:\n- Title: %s\n- Artist: %s" % (
                                query, title, artist))
                    else:
                        try:
                            mx = await self._get_async_scrapping_musixmatch(query)  # type: ignore

                            if mx:
                                lyrics, title, artist = mx

                                await self.log(
                                    "*Sync* Musixmatch works with query %s. Using *sync* musixmatch with result:\n- Title: %s\n- Artist: %s" % (
                                        query, title, artist))
                            else:
                                await self.log("Nothing found with query %s." % query)
                                return None
                        except:
                            await self.log("Nothing found with query %s." % query)
                            return None

        lyrics = lyrics.replace('EmbedShare', '').replace('URLCopyEmbedCopy', '').replace('Related searches', '')

        if img:
            d = {'track': img}
        else:
            d = {}

        cls = Lyric(query, title, artist, lyrics, js, d, False)

        str_data = json.dumps({'title': title, 'artist': artist, 'lyrics': lyrics, 'raw_dict': js})

        if self.redis is not None:
            await self.redis.set(query.lower(), str_data)

        await self.log("Adding/Updating query %s to cache." % query)

        return cls

    async def _start_suggest_task(self, data):
        def split(lst, max_size):
            master = []
            l = []
            n = 0
            for i in lst:
                l.append(i)
                n += 1
                if n == max_size:
                    master.append(l)
                    l = []
                    n = 0
                    
            if l:
                master.append(l)

            return master
        
        async def perf_req(key):
            async with aiohttp.ClientSession() as sess:
                async with sess.get(f'https://api.yodabot.xyz/api/lyrics/search', params={'q': key}) as resp:
                    return resp.status
                
        keys = []

        for i in data:
            keys.extend([i['title'], f"{i['title']} - {', '.join(i['artists'])}",
                         f"{i['title']} {', '.join(i['artists'])}"])
        
        s_data = split(keys, 6)
        
        for i in s_data:
            await asyncio.gather(*[perf_req(x) for x in i])
            await asyncio.sleep(.25)

    async def suggest(self, query: str, n: int):
        if n < 1 or n > 20:
            raise ValueError('n must be between 1 and 20.')
        
        res = await self.spotify.search.search(query, types='track', limit=50)
        tracks = res.tracks.items

        js = [{"title": x["name"], "artists": [artist["name"] for artist in x["artists"]]} for x in tracks]
        
        x = list(reversed(js))
        
        for i, item in enumerate(x):
            if x.count(item) > 1:
                x.pop(i)
        
        js = list(reversed(x))
                
        js = js[:n]
        
        self.loop.create_task(self._start_suggest_task(js))

        return js

    async def save(self, data):
        self.parse_psql_data(data, reverse=True)

        await self.psql.query(
            'INSERT INTO lyrics (q, title, artist, lyrics, track_img, bg_img, raw_dict) VALUES ($1, $2, $3, $4, $5, $6, $7)',
            data['q'].lower(), data['title'], data['artist'], data['lyrics'], data['images']['track'],
            data['images']['background'], json.dumps(data['raw_dict'])
        )
