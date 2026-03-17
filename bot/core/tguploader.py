from time import time
from asyncio import sleep as asleep
from traceback import format_exc
from math import floor
from os import path as ospath
from aiofiles.os import remove as aioremove
from pyrogram.errors import FloodWait

from bot import bot, Var
from .func_utils import editMessage, convertBytes, convertTime
from .reporter import rep

THUMB_PATH = "thumb.jpg"

class TgUploader:
    def __init__(self, message):
        self.cancelled = False
        self.message = message
        self.__name = ""
        self.__qual = ""
        self.__client = bot
        self.__start = time()
        self.__updater = time()

    async def upload(self, path, qual):
        self.__name = ospath.basename(path)
        self.__qual = qual
        thumb = THUMB_PATH if ospath.exists(THUMB_PATH) else None
        try:
            if Var.AS_DOC:
                return await self.__client.send_document(
                    chat_id=Var.FILE_STORE,
                    document=path,
                    thumb=thumb,
                    caption=f"<i>{self.__name}</i>",
                    force_document=True,
                    progress=self.progress_status
                )
            else:
                return await self.__client.send_video(
                    chat_id=Var.FILE_STORE,
                    video=path,
                    thumb=thumb,
                    caption=f"<i>{self.__name}</i>",
                    progress=self.progress_status
                )
        except FloodWait as e:
            await asleep(e.value * 1.5)
            return await self.upload(path, qual)
        except Exception as e:
            await rep.report(format_exc(), "error")
            raise e
        finally:
            if ospath.exists(path):
                await aioremove(path)

    async def progress_status(self, current, total):
        if self.cancelled:
            self.__client.stop_transmission()
        now = time()
        diff = now - self.__start
        if (now - self.__updater) >= 10 or current == total:
            self.__updater = now
            percent = round(current / total * 100, 2)
            speed = current / diff
            eta = round((total - current) / speed)
            bar = floor(percent / 8) * "█" + (12 - floor(percent / 8)) * "▒"
            progress_str = f"""‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b>

‣ <b>Status :</b> <i>Uploading {self.__qual}p</i>
    <code>[{bar}]</code> {percent}%

    ‣ <b>Size :</b> {convertBytes(current)} out of ~ {convertBytes(total)}
    ‣ <b>Speed :</b> {convertBytes(speed)}/s
    ‣ <b>Time Took :</b> {convertTime(diff)}
    ‣ <b>Time Left :</b> {convertTime(eta)}"""

            await editMessage(self.message, progress_str)
