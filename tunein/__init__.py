import os
import requests
from dead_simple_cache import SimpleCache
from tunein.xml_helper import xml2dict
from tunein.parse import fuzzy_match

BASE_DIR = os.getenv("HOME") or os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE_PATH = os.path.join(BASE_DIR, ".cache", "radios")


class TuneInStation:
    def __init__(self, raw):
        self.raw = raw

    @property
    def title(self):
        return self.raw.get("title", "")

    @property
    def artist(self):
        return self.raw.get("artist", "")

    @property
    def image(self):
        return self.raw.get("image")

    @property
    def description(self):
        return self.raw.get("description", "")

    @property
    def stream(self):
        return self.raw.get("stream")

    def match(self, phrase=None):
        phrase = phrase or self.raw.get("query")
        if not phrase:
            return 0
        return fuzzy_match(phrase.lower(), self.title.lower()) * 100

    def __str__(self):
        return self.title

    def __repr__(self):
        return self.title

    @property
    def dict(self):
        """Return a dict representation of the station."""
        return {
            "artist": self.artist,
            "description": self.description,
            "image": self.image,
            "match": self.match(),
            "stream": self.stream,
            "title": self.title,
        }


class TuneIn:
    search_url = "http://opml.radiotime.com/Search.ashx"
    featured_url = "http://opml.radiotime.com/Browse.ashx?c=local"  # local stations
    cache = SimpleCache(file_path=DEFAULT_CACHE_PATH)

    @staticmethod
    def get_stream_url(url):
        res = requests.get(url)
        for url in res.text.splitlines():
            if (len(url) > 4):
                if url[-3:] == 'm3u':
                    return url[:-4]
                if url[-3:] == 'pls':
                    res2 = requests.get(url)
                    # Loop through the data looking for the first url
                    for line in res2.text.splitlines():
                        if line.startswith("File1="):
                            return line[6:]
                else:
                    return url

    @staticmethod
    def featured():
        res = requests.post(TuneIn.featured_url)
        return list(TuneIn._get_stations(res))

    @staticmethod
    def search_cache(query):
        """Search for cached stations."""
        items = TuneIn.cache.get(query, fuzzy=True)
        server_alive = {}
        for key, stations in items.items():
            for station in stations:
                url = station["url"]
                if url not in server_alive:
                    response = requests.head(url, timeout=1)
                    code = response.status_code
                    server_alive[url] = str(code).startswith('2') or str(code).startswith('3')
                if not server_alive[url]:
                    stations.remove(station)
        for key, stations in items.items():
            if stations:
                TuneIn.cache.replace(key=key, data=stations)
            else:
                TuneIn.cache.delete(key=key)
        return sum(list(items.values()), [])

    @staticmethod
    def search(query):
        cached_items = TuneIn.search_cache(query)
        if cached_items:
            stations = [TuneInStation(item) for item in cached_items]
        else:
            # Search again
            response = requests.post(
                TuneIn.search_url,
                data={"query": query, "formats": "mp3,aac,ogg,html,hls"}
            )
            stations = list(TuneIn._get_stations(response, query))
            # Update cache
            for station in stations:
                TuneIn.cache.add(key=query, data=station.raw)
        return stations

    @staticmethod
    def _get_stations(res: requests.Response, query: str = ""):
        res = xml2dict(res.text)
        if not res.get("opml"):
            return
        # stations might be nested based on Playlist/Search
        outline = res['opml']['body']["outline"]

        if not isinstance(outline, list):
            return
        if outline[0].get("outline"):
            stations = outline[0]["outline"]
        else:
            stations = outline

        for entry in stations:
            try:
                if not entry.get("key") == "unavailable" \
                        and entry.get("type") == "audio" \
                        and entry.get("item") == "station":
                    yield TuneInStation(
                        {"stream": TuneIn.get_stream_url(entry["URL"]),
                         "url": entry["URL"],
                         "title": entry.get("current_track") or entry.get("text"),
                         "artist": entry.get("text"),
                         "description": entry.get("subtext"),
                         "image": entry.get("image"),
                         "query": query
                         })
            except:
                continue
