from os import path as ospath, listdir
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove as aioremove, mkdir

from aiohttp import ClientSession
from torrentp import TorrentDownloader as _TorrentDownloader
from bot import LOGS
from bot.core.func_utils import handle_logs


class TorDownloader:
    def __init__(self, path="."):
        self.__downdir = path
        self.__torpath = "torrents/"

    @handle_logs
    async def download(self, torrent, name=None):
        before = set(listdir(self.__downdir)) if ospath.exists(self.__downdir) else set()

        if torrent.startswith("magnet:"):
            torp = _TorrentDownloader(torrent, self.__downdir)
            await torp.start_download()
        elif torfile := await self.get_torfile(torrent):
            torp = _TorrentDownloader(torfile, self.__downdir)
            await torp.start_download()
            await aioremove(torfile)
        else:
            return None

        after = set(listdir(self.__downdir))
        new_files = after - before
        if new_files:
            actual_name = new_files.pop()
            LOGS.info(f"Downloaded file detected: {actual_name}")
            return ospath.join(self.__downdir, actual_name)

        LOGS.warning("Could not detect downloaded file, falling back to dn= name")
        return ospath.join(self.__downdir, name) if name else None

    @handle_logs
    async def get_torfile(self, url):
        if url.startswith("torrents/") and ospath.exists(url):
            return url

        if not await aiopath.isdir(self.__torpath):
            await mkdir(self.__torpath)

        tor_name = url.split('/')[-1]
        des_dir = ospath.join(self.__torpath, tor_name)

        async with ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    async with aiopen(des_dir, 'wb') as file:
                        async for chunk in response.content.iter_any():
                            await file.write(chunk)
                    return des_dir
        return None

    @staticmethod
    async def get_name_from_torfile(torfile_path):
        try:
            import libtorrent as lt
            info = lt.torrent_info(torfile_path)
            return info.name()
        except Exception:
            pass
        try:
            async with aiopen(torfile_path, 'rb') as f:
                data = await f.read()
            import re
            match = re.search(rb'4:name(\d+):', data)
            if match:
                length = int(match.group(1))
                start = match.end()
                return data[start:start + length].decode('utf-8', errors='ignore')
        except Exception as e:
            LOGS.error(f"Torrent name extraction failed: {e}")
        return None
