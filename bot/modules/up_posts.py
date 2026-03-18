from json import loads as jloads
from os import path as ospath, execl
from sys import executable

from aiohttp import ClientSession
from bot import Var, bot, ffQueue, ffLock
from bot.core.text_utils import TextEditor
from bot.core.reporter import rep

SCHEDULE_PIC = "https://graph.org/file/bd605fb26b3452322732e-254c582dc215a686bb.jpg"

TD_SCHR = None


async def send_schedule_post():
    global TD_SCHR
    try:
        async with ClientSession() as ses:
            res = await ses.get("https://subsplease.org/api/?f=schedule&h=true&tz=Asia/Kolkata")
            aniContent = jloads(await res.text())["schedule"]

        text = "<b>📆 Today's Anime Releases Schedule [IST]</b>\n\n"
        for i in aniContent:
            aname = TextEditor(i["title"])
            await aname.load_anilist()
            text += f''' <a href="https://subsplease.org/shows/{i['page']}">{aname.adata.get('title', {}).get('english') or i['title']}</a>\n    • <b>Time</b> : {i["time"]} hrs\n\n'''

        TD_SCHR = await bot.send_photo(
            Var.MAIN_CHANNEL,
            photo=SCHEDULE_PIC,
            caption=text
        )
        await (await TD_SCHR.pin()).delete()

    except Exception as err:
        await rep.report(str(err), "error")


async def upcoming_animes():
    if Var.SEND_SCHEDULE:
        await send_schedule_post()

    if not ffQueue.empty() or ffLock.locked():
        await rep.report("Tasks pending, waiting for all tasks to complete before restart...", "info")
        await ffQueue.join()
        if ffLock.locked():
            async with ffLock:
                pass

    await rep.report("Auto Restarting..!!", "info")
    execl(executable, executable, "-m", "bot")


async def update_shdr(name, link):
    if TD_SCHR is not None:
        TD_lines = TD_SCHR.caption.split('\n')
        for i, line in enumerate(TD_lines):
            if name.lower() in line.lower():
                TD_lines[i] += f"\n    • <b>Status :</b> ✅ Uploaded\n    • <b>Link :</b> {link}"
        await TD_SCHR.edit_caption("\n".join(TD_lines))
