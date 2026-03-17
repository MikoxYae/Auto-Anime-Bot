from asyncio import gather, sleep as asleep, Event, Queue as AsyncQueue
from os import path as ospath
from aiofiles.os import remove as aioremove
from traceback import format_exc

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued, LOGS
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080': '𝟭𝟬𝟴𝟬𝗽',
    '720':  '𝟳𝟮𝟬𝗽',
    '480':  '𝟰𝟴𝟬𝗽',
    '360':  '𝟯𝟲𝟬𝗽'
}


async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if ani_cache['fetch_animes']:
            for link in Var.RSS_ITEMS:
                if (info := await getfeed(link, 0)):
                    bot_loop.create_task(get_animes(info.title, info.link))


async def get_animes(name, torrent, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()

        ani_id = aniInfo.adata.get('id')
        ep_no  = aniInfo.pdata.get("episode_number")

        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)
        elif not force:
            return

        if not force and ani_id in ani_cache['completed']:
            return

        if force or (
            not (ani_data := await db.getAnime(ani_id))
            or (ani_data and not (qual_data := ani_data.get(ep_no)))
            or (ani_data and qual_data and not all(qual for qual in qual_data.values()))
        ):
            if "[Batch]" in name:
                await rep.report(f"Torrent Skipped!\n\n{name}", "warning")
                return

            # ── Check for connected channel ───────────────────────────────
            conn = await db.getChannelConnection(ani_id) if ani_id else None

            # Agar ani_id nahi mila, name se fuzzy match karo
            if not conn:
                all_conns = await db.getAllConnections()
                for c in all_conns:
                    stored = c.get('ani_name', '').lower()
                    if stored and stored in name.lower():
                        conn = c
                        LOGS.info(f"Matched connection by name: {stored}")
                        break

            if conn:
                upload_channel = int(conn['channel_id'])
                invite_link    = conn.get('invite_link', '')
                LOGS.info(f"Connected channel found → {conn['channel_name']}")
            else:
                upload_channel = Var.MAIN_CHANNEL
                invite_link    = None

            await rep.report(f"New Anime Torrent Found!\n\n{name}", "info")

            # ── Post to upload channel (poster + caption) ─────────────────
            post_msg = await bot.send_photo(
                upload_channel,
                photo=await aniInfo.get_poster(),
                caption=await aniInfo.get_caption()
            )

            # ── If connected channel: post join button in main channel ─────
            if conn and invite_link:
                await bot.send_photo(
                    Var.MAIN_CHANNEL,
                    photo=await aniInfo.get_poster(),
                    caption=await aniInfo.get_caption(),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔗 Join Now", url=invite_link)
                    ]])
                )

            await asleep(1.5)

            stat_msg = await sendMessage(
                upload_channel,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>"
            )

            # ── Download ──────────────────────────────────────────────────
            dl = await TorDownloader("./downloads").download(torrent, name)
            if not dl or not ospath.exists(dl):
                await rep.report("File Download Incomplete, Try Again", "error")
                await stat_msg.delete()
                return

            # ── Encode queue ──────────────────────────────────────────────
            post_id  = post_msg.id
            ffEvent  = Event()
            ff_queued[post_id] = ffEvent

            if ffLock.locked():
                await editMessage(
                    stat_msg,
                    f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>"
                )
                await rep.report("Added Task to Queue...", "info")

            await ffQueue.put(post_id)
            await ffEvent.wait()
            await ffLock.acquire()

            total_quals  = len(Var.QUALS)
            btns         = []
            upload_queue = AsyncQueue()

            # ── Encode one quality and push to upload queue ───────────────
            async def encode_and_queue(qual, turn_index):
                filename = await aniInfo.get_upname(qual)
                if not filename:
                    safe_name = name.replace('/', '_').replace('\\', '_')
                    filename  = f"[{qual}p] {safe_name}.mkv"
                    LOGS.warning(f"get_upname returned None for {qual}p, using fallback: {filename}")

                await rep.report(f"Starting Encode [{qual}p]...", "info")
                try:
                    out_path = await FFEncoder(
                        stat_msg, dl, filename, qual,
                        turn_index=turn_index,
                        total_quals=total_quals
                    ).start_encode()
                except Exception as e:
                    await rep.report(f"Encode Error [{qual}p]: {e}", "error")
                    out_path = None

                await upload_queue.put((qual, filename, out_path))

            # ── Upload worker ─────────────────────────────────────────────
            async def upload_worker():
                for _ in range(total_quals):
                    qual, filename, out_path = await upload_queue.get()

                    if not out_path:
                        await rep.report(f"Skipping upload for {qual}p — encode failed", "warning")
                        continue

                    await editMessage(
                        stat_msg,
                        f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n"
                        f"<i>Uploading {qual}p...</i>"
                    )
                    await asleep(1.5)

                    try:
                        msg = await TgUploader(stat_msg, chat_id=upload_channel).upload(out_path, qual)
                    except Exception as e:
                        await rep.report(f"Upload Error [{qual}p]: {e}", "error")
                        continue

                    await rep.report(f"Successfully Uploaded {qual}p!", "info")
                    msg_id = msg.id

                    link = (
                        f"https://telegram.me/{(await bot.get_me()).username}"
                        f"?start={await encode('get-' + str(msg_id * abs(Var.FILE_STORE)))}"
                    )

                    if post_msg:
                        btn_label = (
                            f"{btn_formatter.get(qual, qual + 'p')} "
                            f"- {convertBytes(msg.document.file_size)}"
                        )
                        if btns and len(btns[-1]) == 1:
                            btns[-1].append(InlineKeyboardButton(btn_label, url=link))
                        else:
                            btns.append([InlineKeyboardButton(btn_label, url=link)])

                        await editMessage(
                            post_msg,
                            post_msg.caption.html if post_msg.caption else "",
                            InlineKeyboardMarkup(btns)
                        )

                    await db.saveAnime(ani_id, ep_no, qual, post_id)
                    bot_loop.create_task(extra_utils(msg_id, upload_channel))

            await editMessage(
                stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n"
                f"<i>Encoding {total_quals} Qualities Simultaneously...</i>\n"
                f"<b>Qualities:</b> <code>{' | '.join(q + 'p' for q in Var.QUALS)}</code>"
            )

            await gather(
                *[encode_and_queue(qual, i) for i, qual in enumerate(Var.QUALS)],
                upload_worker()
            )

            ffLock.release()
            await stat_msg.delete()
            if ospath.exists(dl):
                await aioremove(dl)

        ani_cache['completed'].add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")
        try:
            ffLock.release()
        except Exception:
            pass


async def extra_utils(msg_id, chat_id=None):
    target_chat = chat_id or Var.FILE_STORE
    msg = await bot.get_messages(target_chat, message_ids=msg_id)
    if Var.BACKUP_CHANNEL != 0:
        for cid in str(Var.BACKUP_CHANNEL).split():
            await msg.copy(int(cid))
