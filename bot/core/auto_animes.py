from asyncio import gather, sleep as asleep, Event, Queue as AsyncQueue, Semaphore
from os import path as ospath
from aiofiles.os import remove as aioremove
from aioshutil import rmtree as aiormtree
from traceback import format_exc
from time import time

from anitopy import parse as anitopy_parse
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued, ff_queue_names, ff_queue_order, LOGS
from .tordownload import TorDownloader, find_all_videos_in_dir, check_torrent_active
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes, convertTime
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080': '𝟭𝟬𝟴𝟬𝗽',
    '720':  '𝟳𝟮𝟬𝗽',
    '480':  '𝟰𝟴𝟬𝗽',
    '360':  '𝟯𝟲𝟬𝗽',
}

# ─── Default sticker file_ids ─────────────────────────────────────────────────
_DEFAULT_STICKER_MAIN    = "CAACAgUAAxkBAAEQyYJpvRP7-N28QbduJUo9erWgDXv2pwACiBAAAuWgKFeB8NkyyNkOAAE6BA"
_DEFAULT_STICKER_CONNECT = "CAACAgUAAxkBAAEQyYRpvRP_pjHK_GP8eE4VjFPWw9wr7AADFQAClP0pVztrIQO4kT1IOgQ"

# ─── Batch keywords for detection ────────────────────────────────────────────
_BATCH_KEYWORDS = [
    '[batch]', 'complete series', 'complete collection',
    'complete season', 'the complete', 'bd complete',
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_batch_torrent(name: str) -> bool:
    """
    Detect if a torrent name is a season/batch pack rather than a single episode.

    Rules (any one match → batch):
      1. Contains a known batch keyword (case-insensitive)
      2. Anitopy finds a season but NO episode number
      3. Anitopy finds an episode range  e.g. '01-12'
    """
    name_lower = name.lower()

    # Rule 1 — explicit keywords
    for kw in _BATCH_KEYWORDS:
        if kw in name_lower:
            return True

    # Rules 2 & 3 — anitopy analysis
    try:
        pdata  = anitopy_parse(name)
        ep_no  = pdata.get('episode_number')
        season = pdata.get('anime_season')

        # Has season marker but no episode → batch
        if season and not ep_no:
            return True

        # Episode field is a range string like '01-12'
        if ep_no and isinstance(ep_no, str) and '-' in str(ep_no):
            return True

    except Exception:
        pass

    return False


async def _get_stickers() -> tuple[str | None, str | None]:
    """
    Returns (sticker_main, sticker_connect).
    DB value 'REMOVED' → None (no sticker sent).
    Missing DB doc   → hardcoded default.
    """
    raw_main    = await db.getStickerMain()
    raw_connect = await db.getStickerConnect()

    sticker_main    = None if raw_main    == 'REMOVED' else (raw_main    or _DEFAULT_STICKER_MAIN)
    sticker_connect = None if raw_connect == 'REMOVED' else (raw_connect or _DEFAULT_STICKER_CONNECT)

    return sticker_main, sticker_connect


async def _find_connection(ani_id, name: str, pdata: dict) -> dict | None:
    """Find a channel connection for this anime by ID, then by name."""
    if ani_id:
        conn = await db.getChannelConnection(ani_id)
        if conn:
            return conn

    name_lower   = name.lower()
    parsed_title = (pdata.get('anime_title') or '').lower()

    all_conns = await db.getAllConnections()
    for c in all_conns:
        stored     = (c.get('ani_name') or '').lower().strip()
        stored_alt = (c.get('ani_name_alt') or '').lower().strip()

        if stored and stored in name_lower:
            LOGS.info(f"Connection matched by English name: {stored}")
            return c
        if stored_alt and stored_alt in name_lower:
            LOGS.info(f"Connection matched by Romaji name: {stored_alt}")
            return c
        if stored and parsed_title and stored in parsed_title:
            LOGS.info(f"Connection matched by parsed title (English): {stored}")
            return c
        if stored_alt and parsed_title and stored_alt in parsed_title:
            LOGS.info(f"Connection matched by parsed title (Romaji): {stored_alt}")
            return c

    return None


# ─── RSS Fetch Loop ───────────────────────────────────────────────────────────

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if not ani_cache['fetch_animes']:
            continue

        db_rss    = await db.getAllRSS()
        rss_links = db_rss if db_rss else Var.RSS_ITEMS

        for link in rss_links:
            info = await getfeed(link, 0)
            if not info:
                continue

            if is_batch_torrent(info.title):
                # Route to batch processor
                bot_loop.create_task(get_batch_animes(info.title, info.link))
            else:
                bot_loop.create_task(get_animes(info.title, info.link))


# ─── Normal (single-episode) processor ───────────────────────────────────────

async def get_animes(name, torrent, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()

        ani_id = aniInfo.adata.get('id')
        ep_no  = aniInfo.pdata.get("episode_number")

        if ani_id is not None:
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
            conn           = await _find_connection(ani_id, name, aniInfo.pdata)
            upload_channel = int(conn['channel_id']) if conn else Var.MAIN_CHANNEL
            invite_link    = conn.get('invite_link', '') if conn else None

            await rep.report(f"New Anime Torrent Found!\n\n{name}", "info")

            custom_pic             = await db.getAnimePic(ani_id) if ani_id else None
            poster                 = custom_pic or await aniInfo.get_poster()
            sticker_main, sticker_connect = await _get_stickers()

            post_msg = await bot.send_photo(
                upload_channel,
                photo   = poster,
                caption = await aniInfo.get_caption()
            )

            # Sticker after channel post
            try:
                if conn:
                    if sticker_connect:
                        await bot.send_sticker(upload_channel, sticker_connect)
                else:
                    if sticker_main:
                        await bot.send_sticker(Var.MAIN_CHANNEL, sticker_main)
            except Exception:
                pass

            # Main channel mirror when connected
            if conn and invite_link:
                await bot.send_photo(
                    Var.MAIN_CHANNEL,
                    photo        = poster,
                    caption      = await aniInfo.get_caption(),
                    reply_markup = InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔗 Join Now", url=invite_link)
                    ]])
                )
                try:
                    if sticker_main:
                        await bot.send_sticker(Var.MAIN_CHANNEL, sticker_main)
                except Exception:
                    pass

            await asleep(1.5)

            stat_msg = await sendMessage(
                upload_channel,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>"
            )

            dl = await TorDownloader("./downloads").download(torrent, name)
            if not dl or not ospath.exists(dl):
                await rep.report("File Download Incomplete, Try Again", "error")
                await stat_msg.delete()
                return

            post_id              = post_msg.id
            ffEvent              = Event()
            ff_queued[post_id]   = ffEvent
            ff_queue_names[post_id] = name
            ff_queue_order.append(post_id)

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
            encode_sem   = Semaphore(2)

            async def encode_and_queue(qual, turn_index):
                filename = await aniInfo.get_upname(qual)
                if not filename:
                    safe_name = name.replace('/', '_').replace('\\', '_')
                    filename  = f"[{qual}p] {safe_name}.mkv"
                    LOGS.warning(f"get_upname returned None for {qual}p, using fallback: {filename}")

                async with encode_sem:
                    await rep.report(f"Starting Encode [{qual}p]...", "info")
                    encode_start = time()
                    try:
                        out_path = await FFEncoder(
                            stat_msg, dl, filename, qual,
                            turn_index=turn_index,
                            total_quals=total_quals
                        ).start_encode()
                    except Exception as e:
                        await rep.report(f"Encode Error [{qual}p]: {e}", "error")
                        out_path = None

                    time_taken   = convertTime(time() - encode_start)
                    titles       = aniInfo.adata.get('title') or {}
                    display_name = titles.get('english') or titles.get('romaji') or name

                    if out_path:
                        await rep.report(
                            f"✅ Encode Complete!\n\n"
                            f"‣ Anime: {display_name}\n"
                            f"‣ Quality: {qual}p\n"
                            f"‣ Time Taken: {time_taken}",
                            "info"
                        )
                    else:
                        await rep.report(
                            f"❌ Encode Failed!\n\n"
                            f"‣ Anime: {display_name}\n"
                            f"‣ Quality: {qual}p\n"
                            f"‣ Time Taken: {time_taken}",
                            "error"
                        )

                await upload_queue.put((qual, filename, out_path))

            async def upload_worker():
                bot_username = (await bot.get_me()).username

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
                        msg = await TgUploader(stat_msg, chat_id=Var.FILE_STORE).upload(out_path, qual)
                    except Exception as e:
                        await rep.report(f"Upload Error [{qual}p]: {e}", "error")
                        continue

                    await rep.report(f"Successfully Uploaded {qual}p!", "info")

                    store_msg_id = msg.id
                    link = (
                        f"https://telegram.me/{bot_username}"
                        f"?start=get-{await encode(str(store_msg_id * abs(Var.FILE_STORE)))}"
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
                    bot_loop.create_task(extra_utils(store_msg_id, Var.FILE_STORE))

            await editMessage(
                stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n"
                f"<i>Encoding {total_quals} Qualities (2 at a time)...</i>\n"
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

        if ani_id is not None:
            ani_cache['completed'].add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")
        try:
            ffLock.release()
        except Exception:
            pass


# ─── Batch processor ──────────────────────────────────────────────────────────

async def get_batch_animes(name: str, torrent: str, force: bool = False):
    """
    Full batch processing flow:
      1. Batch mode gate
      2. Torrent activity check (seeders)
      3. AniList metadata fetch
      4. Channel post (connected or main)
      5. Download all episodes
      6. For each quality → encode ALL episodes → upload all → save to DB → add button
      7. Cleanup
    """
    try:
        # ── 1. Batch mode gate ────────────────────────────────────────────────
        batch_mode = await db.getBatchMode()
        if not batch_mode:
            await rep.report(
                f"Batch torrent skipped (batch mode is OFF):\n{name}",
                "warning"
            )
            return

        # ── 2. Torrent activity check ─────────────────────────────────────────
        await rep.report(f"Checking batch torrent activity:\n{name}", "info")
        is_active = await check_torrent_active(torrent)
        if not is_active:
            await rep.report(
                f"Batch torrent appears DEAD (no seeders found):\n{name}",
                "warning"
            )
            return

        # ── 3. AniList metadata ───────────────────────────────────────────────
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()

        ani_id = aniInfo.adata.get('id')
        titles = aniInfo.adata.get('title') or {}
        display_name = titles.get('english') or titles.get('romaji') or titles.get('native') or (aniInfo.pdata.get('anime_title') or name)

        # Deduplicate: skip if this batch was already completed
        if not force and ani_id is not None and ani_id in ani_cache['completed']:
            return

        if ani_id is not None:
            ani_cache['ongoing'].add(ani_id)

        # ── 4. Channel post ───────────────────────────────────────────────────
        conn           = await _find_connection(ani_id, name, aniInfo.pdata)
        upload_channel = int(conn['channel_id']) if conn else Var.MAIN_CHANNEL
        invite_link    = conn.get('invite_link', '') if conn else None

        custom_pic             = await db.getAnimePic(ani_id) if ani_id else None
        poster                 = custom_pic or await aniInfo.get_poster()
        sticker_main, sticker_connect = await _get_stickers()

        await rep.report(f"New Batch Torrent Found!\n\n{name}", "info")

        # Placeholder caption — episode count unknown until download completes
        initial_caption = await aniInfo.get_batch_post_caption(
            total_eps     = 0,
            original_name = name,
        )

        post_msg = await bot.send_photo(
            upload_channel,
            photo   = poster,
            caption = initial_caption,
        )

        # Sticker after upload channel post
        try:
            if conn:
                if sticker_connect:
                    await bot.send_sticker(upload_channel, sticker_connect)
            else:
                if sticker_main:
                    await bot.send_sticker(Var.MAIN_CHANNEL, sticker_main)
        except Exception:
            pass

        # Mirror to main channel with invite button when connected
        if conn and invite_link:
            await bot.send_photo(
                Var.MAIN_CHANNEL,
                photo        = poster,
                caption      = initial_caption,
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔗 Join Now", url=invite_link)
                ]])
            )
            try:
                if sticker_main:
                    await bot.send_sticker(Var.MAIN_CHANNEL, sticker_main)
            except Exception:
                pass

        await asleep(1.5)

        stat_msg = await sendMessage(
            upload_channel,
            f"‣ <b>Batch :</b> <b><i>{name}</i></b>\n\n<i>Downloading all episodes...</i>"
        )

        # ── 5. Download all episodes ──────────────────────────────────────────
        video_files = await TorDownloader("./downloads").download_batch(torrent, name)

        if not video_files:
            await rep.report(
                f"Batch download failed — no video files found:\n{name}",
                "error"
            )
            await stat_msg.delete()
            if ani_id is not None:
                ani_cache['ongoing'].discard(ani_id)
            return

        total_eps = len(video_files)
        await rep.report(f"Batch download complete — {total_eps} episode(s):\n{name}", "info")

        # Update post caption with real episode count
        try:
            updated_caption = await aniInfo.get_batch_post_caption(
                total_eps     = total_eps,
                original_name = name,
            )
            await post_msg.edit_caption(updated_caption)
        except Exception:
            updated_caption = initial_caption

        # ── Queue and acquire ffLock (same as normal flow) ────────────────────
        post_id                  = post_msg.id
        ffEvent                  = Event()
        ff_queued[post_id]       = ffEvent
        ff_queue_names[post_id]  = f"[BATCH] {name}"
        ff_queue_order.append(post_id)

        if ffLock.locked():
            await editMessage(
                stat_msg,
                f"‣ <b>Batch :</b> <b><i>{name}</i></b>\n\n"
                f"<i>Queued — waiting for current task to finish...</i>"
            )
            await rep.report(f"Batch task queued:\n{name}", "info")

        await ffQueue.put(post_id)
        await ffEvent.wait()
        await ffLock.acquire()

        # ── 6. Encode quality-by-quality, all episodes per quality ────────────
        btns = []  # Inline buttons added to post_msg

        for qual in Var.QUALS:
            qual_file_ids = []   # FILE_STORE message IDs for this quality

            for ep_idx, video_path in enumerate(video_files, 1):
                ep_fname = ospath.basename(video_path)

                # Parse episode number from individual filename
                try:
                    ep_pdata = anitopy_parse(ep_fname)
                    raw_ep   = ep_pdata.get('episode_number')
                    # Handle list (multiple matches) or range string
                    if isinstance(raw_ep, list):
                        raw_ep = raw_ep[0]
                    if raw_ep and '-' in str(raw_ep):
                        raw_ep = str(raw_ep).split('-')[0].strip()
                    ep_no = str(raw_ep).zfill(2) if raw_ep else str(ep_idx).zfill(2)
                except Exception:
                    ep_no = str(ep_idx).zfill(2)

                # Progress update
                await editMessage(
                    stat_msg,
                    f"‣ <b>Batch [{qual}p] :</b> <b><i>{display_name}</i></b>\n\n"
                    f"<i>Encoding Episode {ep_no}  ({ep_idx}/{total_eps})...</i>"
                )

                # Generate filename for this episode
                filename = await aniInfo.get_batch_upname(qual, ep_no, ep_fname)
                if not filename:
                    filename = f"[{qual}p] EP{ep_no} {display_name} {Var.BRAND_UNAME}.mkv"
                    LOGS.warning(f"get_batch_upname returned None for {qual}p EP{ep_no}, using fallback")

                # Encode
                encode_start = time()
                try:
                    out_path = await FFEncoder(
                        stat_msg, video_path, filename, qual,
                        turn_index  = 0,
                        total_quals = 1,
                    ).start_encode()
                except Exception as e:
                    await rep.report(
                        f"Batch encode error [{qual}p] EP{ep_no}: {e}", "error"
                    )
                    out_path = None

                time_taken = convertTime(time() - encode_start)

                if not out_path:
                    await rep.report(
                        f"❌ Batch encode FAILED\n"
                        f"‣ Anime: {display_name}\n"
                        f"‣ Quality: {qual}p  Episode: {ep_no}\n"
                        f"‣ Time: {time_taken}",
                        "error"
                    )
                    continue

                await rep.report(
                    f"✅ Batch encode OK [{qual}p] EP{ep_no} — {time_taken}",
                    "info"
                )

                # Upload encoded episode to FILE_STORE
                await editMessage(
                    stat_msg,
                    f"‣ <b>Batch [{qual}p] :</b> <b><i>{display_name}</i></b>\n\n"
                    f"<i>Uploading Episode {ep_no}  ({ep_idx}/{total_eps})...</i>"
                )

                try:
                    msg = await TgUploader(stat_msg, chat_id=Var.FILE_STORE).upload(out_path, qual)
                    qual_file_ids.append(msg.id)
                    await rep.report(
                        f"✅ Batch upload OK [{qual}p] EP{ep_no}  ({ep_idx}/{total_eps})",
                        "info"
                    )
                    bot_loop.create_task(extra_utils(msg.id, Var.FILE_STORE))
                except Exception as e:
                    await rep.report(
                        f"Batch upload error [{qual}p] EP{ep_no}: {e}", "error"
                    )

            # No files uploaded for this quality → skip button
            if not qual_file_ids:
                await rep.report(
                    f"No files uploaded for {qual}p — skipping button", "warning"
                )
                continue

            # Save batch file IDs to DB
            await db.saveBatchFiles(
                ani_id        = ani_id,
                qual          = qual,
                file_ids      = qual_file_ids,
                title         = display_name,
                total_eps     = len(qual_file_ids),
                poster        = poster,
                original_name = name,
            )

            # Add batch button to channel post
            actual_count = len(qual_file_ids)
            btn_label    = f"📦 {btn_formatter.get(qual, qual+'p')} — Ep 1-{actual_count}"
            cb_data      = f"batch_dl_{ani_id}_{qual}"

            if btns and len(btns[-1]) == 1:
                btns[-1].append(InlineKeyboardButton(btn_label, callback_data=cb_data))
            else:
                btns.append([InlineKeyboardButton(btn_label, callback_data=cb_data)])

            try:
                await editMessage(
                    post_msg,
                    post_msg.caption.html if post_msg.caption else updated_caption,
                    InlineKeyboardMarkup(btns)
                )
            except Exception:
                pass **...**

_This response is too long to display in full._
