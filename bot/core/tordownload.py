import re
import struct
import socket
from os import path as ospath, listdir, walk, getcwd
from urllib.parse import urlparse, urlencode, quote_from_bytes
from asyncio import wait_for, TimeoutError as AsyncTimeoutError, sleep as asleep, create_task, CancelledError
from time import time
from math import floor

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove as aioremove, mkdir
from aiohttp import ClientSession, ClientTimeout
from anitopy import parse as anitopy_parse
from torrentp import TorrentDownloader as _TorrentDownloader

from bot import LOGS
from bot.core.func_utils import handle_logs, editMessage, convertBytes, convertTime

VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.mov', '.webm', '.flv', '.m4v'}

BATCH_STICKER_OPEN  = "CAACAgUAAxkBAAEQy2JpvmjZGXHw5ed2_jAdwFhKTBW6dQAC4BMAAp6PIFcLAAGEEdQGq4s6BA"
BATCH_STICKER_CLOSE = "CAACAgUAAxkBAAEQy2Rpvmj9bMfTK2D61weCXOcBAAHaHM4AAxMAAhJBKVd3ycv655tyYToE"


# ─── Video helpers ────────────────────────────────────────────────────────────

def _find_video_in_dir(directory: str) -> str | None:
    best      = None
    best_size = -1
    for root, dirs, files in walk(directory):
        for fname in files:
            ext = ospath.splitext(fname)[1].lower()
            if ext in VIDEO_EXTS:
                fpath = ospath.join(root, fname)
                try:
                    size = ospath.getsize(fpath)
                except OSError:
                    size = 0
                if size > best_size:
                    best_size = size
                    best      = fpath
    return best


def find_all_videos_in_dir(directory: str) -> list[str]:
    videos = []
    for root, dirs, files in walk(directory):
        for fname in files:
            ext = ospath.splitext(fname)[1].lower()
            if ext in VIDEO_EXTS:
                videos.append(ospath.join(root, fname))

    def _sort_key(path: str):
        fname = ospath.basename(path)
        try:
            pdata = anitopy_parse(fname)
            ep    = pdata.get('episode_number')
            if ep:
                ep_str = str(ep).split('-')[0].strip()
                return (0, float(ep_str))
        except Exception:
            pass
        return (1, re.sub(r'(\d+)', lambda m: m.group().zfill(10), fname.lower()))

    return sorted(videos, key=_sort_key)


# ─── Torrent activity check ───────────────────────────────────────────────────

def _hex_to_url_encoded(hex_str: str) -> str:
    raw = bytes.fromhex(hex_str)
    return quote_from_bytes(raw)


def _parse_scrape_seeders(data: bytes, info_hash_bin: bytes) -> int:
    try:
        idx = data.find(info_hash_bin)
        if idx == -1:
            m = re.search(rb'd8:completei(\d+)e', data)
            if m:
                return int(m.group(1))
            return 0
        sub = data[idx:]
        m   = re.search(rb'd8:completei(\d+)e', sub)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0


def _extract_magnet_parts(magnet: str) -> tuple[str, list[str]]:
    infohash = ""
    trackers = []

    for part in magnet.split('&'):
        if part.startswith("magnet:?"):
            part = part[8:]
        if part.startswith("xt=urn:btih:"):
            ih = part[len("xt=urn:btih:"):]
            if len(ih) == 32:
                import base64
                try:
                    infohash = base64.b32decode(ih.upper()).hex()
                except Exception:
                    infohash = ih
            else:
                infohash = ih.lower()
        elif part.startswith("tr="):
            from urllib.parse import unquote
            trackers.append(unquote(part[3:]))

    return infohash, trackers


async def _check_http_tracker(tracker_url: str, infohash_hex: str, timeout: int = 8) -> int:
    try:
        parsed  = urlparse(tracker_url)
        base    = f"{parsed.scheme}://{parsed.netloc}"
        path    = parsed.path.replace('/announce', '/scrape')
        encoded = _hex_to_url_encoded(infohash_hex)
        url     = f"{base}{path}?info_hash={encoded}"

        async with ClientSession(timeout=ClientTimeout(total=timeout)) as sess:
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data          = await resp.read()
                    info_hash_bin = bytes.fromhex(infohash_hex)
                    return _parse_scrape_seeders(data, info_hash_bin)
    except Exception:
        pass
    return 0


async def _check_udp_tracker(tracker_url: str, infohash_hex: str, timeout: int = 8) -> int:
    try:
        parsed = urlparse(tracker_url)
        host   = parsed.hostname
        port   = parsed.port or 6969
        ip     = socket.gethostbyname(host)
        loop   = __import__('asyncio').get_event_loop()

        conn_req = struct.pack('>QII', 0x41727101980, 0, __import__('random').randint(0, 0xFFFFFFFF))

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _UDPTrackerProtocol(conn_req, infohash_hex, timeout),
            remote_addr=(ip, port)
        )
        try:
            seeders = await wait_for(protocol.result, timeout=timeout)
            return seeders
        except (AsyncTimeoutError, Exception):
            return 0
        finally:
            transport.close()
    except Exception:
        pass
    return 0


class _UDPTrackerProtocol(__import__('asyncio').DatagramProtocol):
    def __init__(self, conn_req: bytes, infohash_hex: str, timeout: int):
        self._conn_req     = conn_req
        self._infohash_hex = infohash_hex
        self._timeout      = timeout
        self._conn_id      = None
        self._transport    = None
        import asyncio
        self.result        = asyncio.get_event_loop().create_future()

    def connection_made(self, transport):
        self._transport = transport
        self._transport.sendto(self._conn_req)

    def datagram_received(self, data, addr):
        try:
            if len(data) < 16:
                return
            action = struct.unpack('>I', data[:4])[0]
            if action == 0 and self._conn_id is None:
                self._conn_id = data[8:16]
                tid           = __import__('random').randint(0, 0xFFFFFFFF)
                ih_bin        = bytes.fromhex(self._infohash_hex)
                scrape_req    = self._conn_id + struct.pack('>II', 2, tid) + ih_bin
                self._transport.sendto(scrape_req)
            elif action == 2:
                if len(data) >= 20:
                    seeders = struct.unpack('>I', data[8:12])[0]
                    if not self.result.done():
                        self.result.set_result(seeders)
        except Exception:
            if not self.result.done():
                self.result.set_result(0)

    def error_received(self, exc):
        if not self.result.done():
            self.result.set_result(0)

    def connection_lost(self, exc):
        if not self.result.done():
            self.result.set_result(0)


async def check_torrent_active(magnet_or_url: str, min_seeders: int = 1, timeout: int = 15) -> bool:
    if not magnet_or_url.startswith("magnet:"):
        LOGS.info("Non-magnet torrent URL — skipping activity check, attempting download")
        return True

    infohash, trackers = _extract_magnet_parts(magnet_or_url)

    if not infohash:
        LOGS.warning("Could not extract infohash from magnet — skipping activity check")
        return True

    if not trackers:
        LOGS.warning("No trackers in magnet link — skipping activity check")
        return True

    LOGS.info(f"Checking torrent activity for {infohash[:8]}... via {len(trackers)} tracker(s)")

    for tracker in trackers:
        try:
            if tracker.startswith("http://") or tracker.startswith("https://"):
                seeders = await _check_http_tracker(tracker, infohash, timeout=timeout)
            elif tracker.startswith("udp://"):
                seeders = await _check_udp_tracker(tracker, infohash, timeout=timeout)
            else:
                continue

            if seeders >= min_seeders:
                LOGS.info(f"Torrent active — {seeders} seeder(s) on {tracker}")
                return True

        except Exception as e:
            LOGS.warning(f"Tracker check failed [{tracker}]: {e}")
            continue

    LOGS.warning(f"Torrent appears dead — no seeders found across {len(trackers)} tracker(s)")
    return False


# ─── Download helpers ─────────────────────────────────────────────────────────

def _get_dir_size(path: str) -> int:
    total = 0
    try:
        for root, _, files in walk(path):
            for fname in files:
                try:
                    total += ospath.getsize(ospath.join(root, fname))
                except OSError:
                    pass
    except Exception:
        pass
    return total


def _apply_fast_settings(torp) -> None:
    fast_settings = {
        'connections_limit':      500,
        'active_downloads':       10,
        'active_seeds':           5,
        'upload_rate_limit':      0,
        'download_rate_limit':    0,
        'unchoke_slots_limit':    8,
        'request_queue_time':     3,
        'max_out_request_queue':  1500,
        'whole_pieces_threshold': 20,
        'peer_connect_timeout':   4,
        'inactivity_timeout':     60,
    }

    ses = None
    for attr in ('session', '_session', 'ses', '_ses', 'lt_session', '_lt_session'):
        ses = getattr(torp, attr, None)
        if ses is not None:
            break

    if ses is None:
        for attr in vars(torp):
            obj = getattr(torp, attr, None)
            if obj is not None and callable(getattr(obj, 'apply_settings', None)):
                ses = obj
                break

    if ses is None:
        LOGS.warning("libtorrent session not found — fast settings not applied (speed may be limited)")
        return

    try:
        ses.apply_settings(fast_settings)
        LOGS.info("libtorrent fast settings applied successfully")
    except Exception as e:
        LOGS.warning(f"Could not apply libtorrent fast settings: {e}")


async def _progress_monitor(torp, stat_msg, name: str, downdir: str, interval: int = 30) -> None:
    start_time = time()
    last_bytes = 0

    await asleep(5)

    while True:
        await asleep(interval)
        try:
            elapsed = time() - start_time

            handle = (
                getattr(torp, 'handle',  None)
                or getattr(torp, '_handle', None)
            )

            if handle is not None and hasattr(handle, 'status'):
                s          = handle.status()
                downloaded = int(s.total_wanted_done)
                total      = int(s.total_wanted)
                dl_rate    = int(s.download_rate)

                speed_str  = f"{convertBytes(dl_rate)}/s" if dl_rate > 0 else "—"
                eta_secs   = ((total - downloaded) / dl_rate) if dl_rate > 0 else 0
                eta_str    = convertTime(eta_secs) if eta_secs > 0 else "—"
                percent    = round((downloaded / total) * 100, 1) if total > 0 else 0
                bar        = floor(percent / 8) * "█" + (12 - floor(percent / 8)) * "▒"

                progress_str = (
                    f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n"
                    f"<blockquote>⬇️ <b>Downloading...</b>\n"
                    f"   <code>[{bar}]</code> {percent}%\n\n"
                    f"   ‣ <b>Downloaded :</b> {convertBytes(downloaded)} / {convertBytes(total)}\n"
                    f"   ‣ <b>Speed :</b> {speed_str}\n"
                    f"   ‣ <b>ETA :</b> {eta_str}\n"
                    f"   ‣ <b>Elapsed :</b> {convertTime(elapsed)}</blockquote>"
                )

            else:
                cur_bytes  = _get_dir_size(downdir)
                delta      = cur_bytes - last_bytes
                speed      = delta / interval if interval > 0 else 0
                last_bytes = cur_bytes

                speed_str  = f"{convertBytes(speed)}/s" if speed > 0 else "—"

                progress_str = (
                    f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n"
                    f"<blockquote>⬇️ <b>Downloading...</b>\n\n"
                    f"   ‣ <b>Downloaded :</b> {convertBytes(cur_bytes)}\n"
                    f"   ‣ <b>Speed :</b> {speed_str}\n"
                    f"   ‣ <b>Elapsed :</b> {convertTime(elapsed)}</blockquote>"
                )

            await editMessage(stat_msg, progress_str)

        except CancelledError:
            break
        except Exception as e:
            LOGS.warning(f"Download progress update error: {e}")


# ─── TorDownloader ────────────────────────────────────────────────────────────

class TorDownloader:
    def __init__(self, path="."):
        self.__downdir = path
        self.__torpath = "torrents/"

    @handle_logs
    async def download(self, torrent, name=None, stat_msg=None):
        before = set(listdir(self.__downdir)) if ospath.exists(self.__downdir) else set()

        torp = None
        torfile_to_remove = None

        if torrent.startswith("magnet:"):
            torp = _TorrentDownloader(torrent, self.__downdir)
        elif torfile := await self.get_torfile(torrent):
            torp = _TorrentDownloader(torfile, self.__downdir)
            torfile_to_remove = torfile
        else:
            return None

        _apply_fast_settings(torp)

        progress_task = None
        if stat_msg and name:
            progress_task = create_task(
                _progress_monitor(torp, stat_msg, name, self.__downdir, interval=30)
            )

        try:
            await torp.start_download()
        finally:
            if progress_task and not progress_task.done():
                progress_task.cancel()
                try:
                    await progress_task
                except (CancelledError, Exception):
                    pass
            if torfile_to_remove:
                try:
                    await aioremove(torfile_to_remove)
                except Exception:
                    pass

        after       = set(listdir(self.__downdir))
        new_entries = after - before

        if not new_entries:
            handle = getattr(torp, 'handle', None) or getattr(torp, '_handle', None)
            if handle:
                try:
                    actual_name = handle.name()
                    if actual_name and actual_name in after:
                        LOGS.info(f"Pre-existing folder detected as completed download: {actual_name}")
                        new_entries = {actual_name}
                except Exception:
                    pass

        if new_entries:
            entry_name = new_entries.pop()
            entry_path = ospath.join(self.__downdir, entry_name)

            if ospath.isdir(entry_path):
                video = _find_video_in_dir(entry_path)
                if video:
                    LOGS.info(f"Downloaded video found in folder: {video}")
                    return video
                LOGS.warning(f"No video file found inside folder: {entry_path}")
                return entry_path

            LOGS.info(f"Downloaded file detected: {entry_path}")
            return entry_path

        LOGS.warning("Could not detect downloaded file, falling back to dn= name")
        return ospath.join(self.__downdir, name) if name else None

    @handle_logs
    async def download_batch(self, torrent, name=None, stat_msg=None) -> list[str]:
        before = set(listdir(self.__downdir)) if ospath.exists(self.__downdir) else set()

        torp = None
        torfile_to_remove = None

        if torrent.startswith("magnet:"):
            torp = _TorrentDownloader(torrent, self.__downdir)
        elif torfile := await self.get_torfile(torrent):
            torp = _TorrentDownloader(torfile, self.__downdir)
            torfile_to_remove = torfile
        else:
            return []

        _apply_fast_settings(torp)

        progress_task = None
        if stat_msg and name:
            progress_task = create_task(
                _progress_monitor(torp, stat_msg, name, self.__downdir, interval=30)
            )

        try:
            await torp.start_download()
        finally:
            if progress_task and not progress_task.done():
                progress_task.cancel()
                try:
                    await progress_task
                except (CancelledError, Exception):
                    pass
            if torfile_to_remove:
                try:
                    await aioremove(torfile_to_remove)
                except Exception:
                    pass

        after       = set(listdir(self.__downdir))
        new_entries = after - before

        if not new_entries:
            handle = getattr(torp, 'handle', None) or getattr(torp, '_handle', None)
            if handle:
                try:
                    actual_name = handle.name()
                    if actual_name and actual_name in after:
                        LOGS.info(f"Batch: pre-existing folder detected as completed download: {actual_name}")
                        new_entries = {actual_name}
                except Exception:
                    pass

        if not new_entries:
            LOGS.warning("Batch download: could not detect any new files")
            return []

        entry_name = new_entries.pop()
        entry_path = ospath.join(self.__downdir, entry_name)

        if ospath.isdir(entry_path):
            videos = find_all_videos_in_dir(entry_path)
            LOGS.info(f"Batch download: found {len(videos)} video file(s) in {entry_path}")
            return videos

        ext = ospath.splitext(entry_path)[1].lower()
        if ext in VIDEO_EXTS:
            LOGS.info(f"Batch download: single video file {entry_path}")
            return [entry_path]

        LOGS.warning(f"Batch download: entry is not a video or directory: {entry_path}")
        return []

    @handle_logs
    async def get_torfile(self, url):
        if url.startswith("torrents/") and ospath.exists(url):
            return url

        if not await aiopath.isdir(self.__torpath):
            await mkdir(self.__torpath)

        tor_name = url.split('/')[-1]
        des_dir  = ospath.join(self.__torpath, tor_name)

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
            match = re.search(rb'4:name(\d+):', data)
            if match:
                length = int(match.group(1))
                start  = match.end()
                return data[start:start + length].decode('utf-8', errors='ignore')
        except Exception as e:
            LOGS.error(f"Torrent name extraction failed: {e}")
        return None
