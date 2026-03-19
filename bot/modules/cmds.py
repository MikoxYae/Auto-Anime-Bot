from asyncio import sleep as asleep
from traceback import format_exc
from urllib.parse import unquote

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from os import kill
from signal import SIGSTOP, SIGCONT

from bot import bot, Var, ani_cache, LOGS, ffpids_cache, ff_queue_names, ff_queue_order
from bot.core.database import db
from bot.core.func_utils import editMessage, sendMessage, encode, decode
from bot.core.text_utils import TextEditor
from bot.core.tordownload import TorDownloader
from bot.core.auto_animes import get_animes
from bot.core.reporter import rep
from bot.modules.up_posts import send_schedule_post


# ─── Filter Helpers ───────────────────────────────────────────────────────────

def command(cmd):
    return filters.command(cmd, prefixes="/")

def user(uid):
    if isinstance(uid, (list, tuple)):
        return filters.user([int(x) for x in uid])
    if isinstance(uid, int):
        return filters.user(uid)
    cleaned = str(uid).replace('[', '').replace(']', '').replace(',', ' ')
    return filters.user([int(x.strip()) for x in cleaned.split() if x.strip()])

private = filters.private

PICS_PER_PAGE = 10
VALID_QUALS   = {"360", "480", "720", "1080"}


# ─── Pending state dicts ──────────────────────────────────────────────────────

pending_connect = {}
pending_torrent = {}
pending_pic     = {}
pending_ffmpeg  = {}


# ─── Delete after helper ──────────────────────────────────────────────────────

async def _replace_after_delete(file_msg, warn_msg, delay, file_name, start_param):
    await asleep(delay)
    try:
        await file_msg.delete()
    except Exception:
        pass
    try:
        me = await bot.get_me()
        click_url = f"https://t.me/{me.username}?start={start_param}"
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Click Here", url=click_url),
                InlineKeyboardButton("Close", callback_data="close_file"),
            ]
        ])
        await warn_msg.edit(
            f"<b>{file_name}</b>",
            reply_markup=buttons,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ─── Pics page builder ────────────────────────────────────────────────────────

def _build_pics_page(all_pics, page):
    total       = len(all_pics)
    total_pages = max(1, (total + PICS_PER_PAGE - 1) // PICS_PER_PAGE)
    start       = page * PICS_PER_PAGE
    end         = start + PICS_PER_PAGE
    page_items  = all_pics[start:end]

    if not page_items:
        return "<b>No custom pic set.</b>", None

    text = f"<b>Custom Pics — Page {page + 1}/{total_pages} ({total} total):</b>\n\n"
    for i, item in enumerate(page_items, start + 1):
        name   = item.get('ani_name_pic') or 'Unknown'
        ani_id = item['_id']
        text  += f"{i}. <b>{name}</b>\n   └ <code>{ani_id}</code>\n\n"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"listpics_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"listpics_{page + 1}"))

    markup = InlineKeyboardMarkup([nav]) if nav else None
    return text, markup


# ─── /start ───────────────────────────────────────────────────────────────────

@bot.on_message(command("start") & private)
async def start_cmd(client, message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("get-"):
        try:
            data   = await decode(args[1][4:])
            msg_id = int(data) // abs(Var.FILE_STORE)
            msg    = await client.get_messages(Var.FILE_STORE, message_ids=msg_id)
            sent   = await msg.copy(message.chat.id)
            if Var.AUTO_DEL:
                warn_msg = await sendMessage(
                    message.chat.id,
                    f"⚠️ <i>This file will be automatically deleted in <b>{Var.DEL_TIMER} seconds</b>.</i>"
                )
                file_name = (
                    getattr(sent.document, 'file_name', None)
                    or getattr(sent.video, 'file_name', None)
                    or "File"
                )
                bot.loop.create_task(
                    _replace_after_delete(sent, warn_msg, Var.DEL_TIMER, file_name, args[1])
                )
        except Exception:
            await sendMessage(message, "File not found or expired.")
    else:
        await sendMessage(
            message,
            f"<b>Hello {message.from_user.mention}!</b>\n\nI am <b>Auto Anime Bot</b>.\n"
            f"I automatically fetch, encode and upload anime episodes.\n\n"
            f"<i>Powered by @Matiz_Tech</i>"
        )


# ─── /help ────────────────────────────────────────────────────────────────────

@bot.on_message(command("help") & private & user(Var.ADMINS))
async def help_cmd(client, message):
    await sendMessage(
        message,
        "<b>Available Commands:</b>\n\n"
        "<b>General:</b>\n"
        "/start - Start the bot\n"
        "/help - Show this message\n"
        "/status - Bot status\n\n"
        "<b>Anime:</b>\n"
        "/fetch - Toggle auto fetch on/off\n"
        "/addmagnet - Add magnet link manually\n"
        "/addtorrent - Add torrent file manually\n"
        "/schedule - Send today's anime schedule to main channel\n\n"
        "<b>Encoding Control:</b>\n"
        "/pause - Pause current encoding task\n"
        "/resume - Resume paused encoding task\n"
        "/queue - View queue and change priority\n\n"
        "<b>FFmpeg Config:</b>\n"
        "/setffmpeg <code>&lt;quality&gt;</code> - Set custom FFmpeg command\n"
        "/listffmpeg - List all saved FFmpeg configs\n"
        "/delffmpeg <code>&lt;quality&gt;</code> - Delete a FFmpeg config\n\n"
        "<b>Channel Connections:</b>\n"
        "/connect <code>&lt;anime name&gt;</code> - Connect anime to a channel\n"
        "/disconnect <code>&lt;anilist id&gt;</code> - Remove a connection\n"
        "/connections - List all connections\n\n"
        "<b>Custom Picture:</b>\n"
        "/addpic <code>&lt;anime name&gt;</code> - Set custom pic for anime\n"
        "/delpic <code>&lt;anilist id&gt;</code> - Remove custom pic\n"
        "/listpics - List all anime with custom pics\n\n"
        "<b>Database:</b>\n"
        "/delanime <code>&lt;anilist id&gt;</code> - Delete anime data from DB\n"
        "/users - Total bot users\n\n"
        "<b>RSS Feeds:</b>\n"
        "/addrss <code>&lt;url&gt;</code> - Add a custom RSS feed URL\n"
        "/delrss <code>&lt;url&gt;</code> - Remove a saved RSS feed URL\n"
        "/listrss - List all saved RSS feeds (shows .env default if none saved)"
    )


# ─── /status ──────────────────────────────────────────────────────────────────

@bot.on_message(command("status") & private & user(Var.ADMINS))
async def status_cmd(client, message):
    fetch_status = "Running" if ani_cache['fetch_animes'] else "Stopped"
    ongoing      = len(ani_cache['ongoing'])
    completed    = len(ani_cache['completed'])
    connections  = await db.getAllConnections()

    await sendMessage(
        message,
        f"<b>Bot Status:</b>\n\n"
        f"• <b>Auto Fetch:</b> {fetch_status}\n"
        f"• <b>Ongoing Animes:</b> {ongoing}\n"
        f"• <b>Completed Animes:</b> {completed}\n"
        f"• <b>Channel Connections:</b> {len(connections)}"
    )


# ─── /fetch ───────────────────────────────────────────────────────────────────

@bot.on_message(command("fetch") & private & user(Var.ADMINS))
async def fetch_cmd(client, message):
    ani_cache['fetch_animes'] = not ani_cache['fetch_animes']
    state = "Enabled" if ani_cache['fetch_animes'] else "Disabled"
    await sendMessage(message, f"Auto Fetch: <b>{state}</b>")


# ─── /pause ───────────────────────────────────────────────────────────────────

@bot.on_message(command("pause") & private & user(Var.ADMINS))
async def pause_cmd(client, message):
    if not ffpids_cache:
        return await sendMessage(message, "<b>No encoding task is currently running.</b>")

    paused = 0
    for pid in ffpids_cache:
        try:
            kill(pid, SIGSTOP)
            paused += 1
        except Exception:
            pass

    if not paused:
        return await sendMessage(message, "<b>Could not pause. Process may have already finished.</b>")

    pending = [p for p in ff_queue_order if p in ff_queue_names]

    if not pending:
        return await sendMessage(
            message,
            "<b>Encoding paused.</b>\n\n"
            "No tasks are waiting in queue.\n"
            "Send /resume to continue current task."
        )

    text = "<b>Encoding Paused!</b>\n\n<b>Queue — Choose which anime to run next:</b>\n\n"
    btn_row = []
    for i, post_id in enumerate(pending, 1):
        name = ff_queue_names.get(post_id, f"Task {post_id}")
        text += f"<b>{i}.</b> <i>{name}</i>\n"
        btn_row.append(InlineKeyboardButton(str(i), callback_data=f"qpriority_{post_id}"))

    text += "\n<i>Tap a number to move that anime to the top and resume encoding.</i>"
    await sendMessage(message, text, buttons=InlineKeyboardMarkup([btn_row]))


# ─── /resume ──────────────────────────────────────────────────────────────────

@bot.on_message(command("resume") & private & user(Var.ADMINS))
async def resume_cmd(client, message):
    if not ffpids_cache:
        return await sendMessage(message, "<b>No encoding task is currently running.</b>")
    resumed = 0
    for pid in ffpids_cache:
        try:
            kill(pid, SIGCONT)
            resumed += 1
        except Exception:
            pass
    if resumed:
        await sendMessage(message, "<b>Encoding resumed.</b>")
    else:
        await sendMessage(message, "<b>Could not resume. Process may have already finished.</b>")


# ─── /queue ───────────────────────────────────────────────────────────────────

@bot.on_message(command("queue") & private & user(Var.ADMINS))
async def queue_cmd(client, message):
    pending = [p for p in ff_queue_order if p in ff_queue_names]
    if not pending:
        return await sendMessage(message, "<b>Queue is empty.</b>\n\nNo tasks are waiting.")

    text = "<b>Encoding Queue:</b>\n\n"
    btn_row = []
    for i, post_id in enumerate(pending, 1):
        name = ff_queue_names.get(post_id, f"Task {post_id}")
        text += f"<b>{i}.</b> <i>{name}</i>\n"
        btn_row.append(InlineKeyboardButton(str(i), callback_data=f"qpriority_{post_id}"))

    text += "\n<i>Tap a number to move that task to the top.</i>"
    await sendMessage(message, text, buttons=InlineKeyboardMarkup([btn_row]))


# ─── Callback: queue priority ─────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^qpriority_(\d+)$") & user(Var.ADMINS))
async def queue_priority_cb(client, callback_query):
    post_id = int(callback_query.matches[0].group(1))

    if post_id not in ff_queue_order:
        await callback_query.answer("This task is no longer in the queue.", show_alert=True)
        return

    ff_queue_order.remove(post_id)
    ff_queue_order.insert(0, post_id)

    for pid in ffpids_cache:
        try:
            kill(pid, SIGCONT)
        except Exception:
            pass

    name = ff_queue_names.get(post_id, f"Task {post_id}")
    await callback_query.answer(
        f"'{name}' set as next. Current task resumed — it will finish first, then your selection runs.",
        show_alert=True
    )

    pending = [p for p in ff_queue_order if p in ff_queue_names]
    if not pending:
        await callback_query.edit_message_text("<b>Queue is empty.</b>")
        return

    text = "<b>Encoding Queue (Updated):</b>\n\n"
    btn_row = []
    for i, pid in enumerate(pending, 1):
        n = ff_queue_names.get(pid, f"Task {pid}")
        text += f"<b>{i}.</b> <i>{n}</i>\n"
        btn_row.append(InlineKeyboardButton(str(i), callback_data=f"qpriority_{pid}"))

    text += "\n<i>Tap a number to move that task to the top.</i>"
    await callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([btn_row]))


# ─── /setffmpeg ───────────────────────────────────────────────────────────────

@bot.on_message(command("setffmpeg") & private & user(Var.ADMINS))
async def setffmpeg_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1 or args[1].strip() not in VALID_QUALS:
        return await sendMessage(
            message,
            "Usage: /setffmpeg <code>&lt;quality&gt;</code>\n\n"
            "Valid qualities: <code>360</code>, <code>480</code>, <code>720</code>, <code>1080</code>\n\n"
            "Example: <code>/setffmpeg 1080</code>"
        )

    qual = args[1].strip()
    pending_ffmpeg[message.from_user.id] = qual

    await sendMessage(
        message,
        f"Quality selected: <b>{qual}p</b>\n\n"
        f"Now send the full FFmpeg command.\n"
        f"Use <code>{{}}</code> as placeholders:\n"
        f"• 1st <code>{{}}</code> = input file\n"
        f"• 2nd <code>{{}}</code> = progress file\n"
        f"• 3rd <code>{{}}</code> = output file\n\n"
        f"<i>Example:</i>\n"
        f"<code>ffmpeg -i '{{}}' -progress '{{}}' -c:v libx264 -crf 26 -s 1920x1080 '{{}}' -y</code>"
    )


# ─── FFmpeg text input handler ────────────────────────────────────────────────
# NOTE: filters.regex(r'^[^/]') ensures command messages (starting with /)
#       never trigger this handler — fixes all-commands-broken bug.

@bot.on_message(filters.text & filters.regex(r'^[^/]') & private & user(Var.ADMINS))
async def handle_ffmpeg_input(client, message):
    uid = message.from_user.id
    if uid not in pending_ffmpeg:
        return

    qual    = pending_ffmpeg.pop(uid)
    cmd_txt = message.text.strip()

    if cmd_txt.count("{}") != 3:
        return await sendMessage(
            message,
            "<b>Invalid command.</b>\n\n"
            "Exactly <b>3</b> <code>{}</code> placeholders needed: input, progress, output.\n\n"
            "Try /setffmpeg again."
        )

    await db.saveFFConfig(qual, cmd_txt)
    short = cmd_txt[:80] + "..." if len(cmd_txt) > 80 else cmd_txt
    await sendMessage(
        message,
        f"<b>FFmpeg Config Saved!</b>\n\n"
        f"• <b>Quality:</b> {qual}p\n"
        f"• <b>Command:</b> <code>{short}</code>"
    )


# ─── /listffmpeg ──────────────────────────────────────────────────────────────

@bot.on_message(command("listffmpeg") & private & user(Var.ADMINS))
async def listffmpeg_cmd(client, message):
    configs = await db.getAllFFConfigs()

    if not configs:
        return await sendMessage(
            message,
            "<b>No FFmpeg configs saved.</b>\n\nUse /setffmpeg to add one."
        )

    text = "<b>FFmpeg Configs:</b>\n\n"
    for doc in sorted(configs, key=lambda x: x["_id"]):
        qual  = doc["_id"]
        cmd   = doc["command"]
        short = cmd[:60] + "..." if len(cmd) > 60 else cmd
        text += f"<b>{qual}p</b>\n<code>{short}</code>\n\n"

    text += "<i>Use /delffmpeg &lt;quality&gt; to remove a config.</i>"
    await sendMessage(message, text)


# ─── /delffmpeg ───────────────────────────────────────────────────────────────

@bot.on_message(command("delffmpeg") & private & user(Var.ADMINS))
async def delffmpeg_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1 or args[1].strip() not in VALID_QUALS:
        return await sendMessage(
            message,
            "Usage: /delffmpeg <code>&lt;quality&gt;</code>\n\n"
            "Valid qualities: <code>360</code>, <code>480</code>, <code>720</code>, <code>1080</code>"
        )

    qual = args[1].strip()
    await db.delFFConfig(qual)
    await sendMessage(
        message,
        f"<b>{qual}p config deleted.</b>\n\n"
        f"<i>Bot will now use the .env fallback for {qual}p.</i>"
    )


# ─── /addmagnet ───────────────────────────────────────────────────────────────

@bot.on_message(command("addmagnet") & private & user(Var.ADMINS))
async def addmagnet_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(message, "Usage: /addmagnet <code>&lt;magnet link&gt;</code>")

    magnet = args[1].strip()
    if not magnet.startswith("magnet:"):
        return await sendMessage(message, "Invalid magnet link.")

    stat     = await sendMessage(message, "<i>Processing magnet link...</i>")
    ani_name = unquote(magnet.split("dn=")[-1].split("&")[0])
    bot.loop.create_task(get_animes(ani_name, magnet, force=True))
    await editMessage(stat, "<i>Magnet added to queue!</i>")


# ─── /addtorrent ──────────────────────────────────────────────────────────────

@bot.on_message(command("addtorrent") & private & user(Var.ADMINS))
async def addtorrent_cmd(client, message):
    pending_torrent[message.from_user.id] = True
    await sendMessage(message, "Send the <b>.torrent</b> file now.")


@bot.on_message(filters.document & private & user(Var.ADMINS))
async def handle_torrent_doc(client, message):
    uid = message.from_user.id
    if uid not in pending_torrent:
        return
    pending_torrent.pop(uid)

    if not message.document.file_name.endswith(".torrent"):
        return await sendMessage(message, "Invalid file. Send a <b>.torrent</b> file.")

    stat = await sendMessage(message, "<i>Processing torrent file...</i>")
    path = await message.download(f"torrents/{message.document.file_name}")
    name = await TorDownloader.get_name_from_torfile(path) or message.document.file_name
    bot.loop.create_task(get_animes(name, path, force=True))
    await editMessage(stat, "<i>Torrent added to queue!</i>")


# ─── /addpic ──────────────────────────────────────────────────────────────────

@bot.on_message(command("addpic") & private & user(Var.ADMINS))
async def addpic_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "Usage: /addpic <code>&lt;anime name&gt;</code>\n\n"
            "Example: /addpic <code>Rooster Fighter</code>"
        )

    anime_name = args[1].strip()
    stat       = await sendMessage(message, f"<i>Searching AniList for:</i> <b>{anime_name}</b>...")

    aniInfo = TextEditor(anime_name)
    await aniInfo.load_anilist()
    ani_id = aniInfo.adata.get('id')

    if not ani_id:
        return await editMessage(
            stat,
            f"Anime not found on AniList: <b>{anime_name}</b>\nTry a different name."
        )

    titles       = aniInfo.adata.get('title', {})
    display_name = titles.get('english') or titles.get('romaji') or anime_name

    pending_pic[message.from_user.id] = {
        'ani_id':   ani_id,
        'ani_name': display_name
    }

    await editMessage(
        stat,
        f"<b>Anime Found:</b> <i>{display_name}</i>\n"
        f"<b>AniList ID:</b> <code>{ani_id}</code>\n\n"
        f"Now send the <b>picture</b> you want to set for this anime."
    )


# ─── Photo handler for /addpic ────────────────────────────────────────────────

@bot.on_message(filters.photo & private & user(Var.ADMINS))
async def handle_pic(client, message):
    uid = message.from_user.id
    if uid not in pending_pic:
        return

    info    = pending_pic.pop(uid)
    file_id = message.photo.file_id

    await db.saveAnimePic(info['ani_id'], file_id, ani_name=info['ani_name'])

    await sendMessage(
        message,
        f"<b>Picture Set Successfully!</b>\n\n"
        f"• <b>Anime:</b> {info['ani_name']}\n"
        f"• <b>AniList ID:</b> <code>{info['ani_id']}</code>"
    )


# ─── /delpic ──────────────────────────────────────────────────────────────────

@bot.on_message(command("delpic") & private & user(Var.ADMINS))
async def delpic_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(message, "Usage: /delpic <code>&lt;anilist id&gt;</code>")

    try:
        ani_id = int(args[1].strip())
    except ValueError:
        return await sendMessage(message, "Invalid AniList ID. Must be a number.")

    await db.delAnimePic(ani_id)
    await sendMessage(
        message,
        f"Custom picture removed for <code>{ani_id}</code>.\n\n"
        f"<i>AniList default poster will be used now.</i>"
    )


# ─── /listpics ────────────────────────────────────────────────────────────────

@bot.on_message(command("listpics") & private & user(Var.ADMINS))
async def listpics_cmd(client, message):
    all_pics = await db.getAllAnimePics()

    if not all_pics:
        return await sendMessage(message, "No custom pics set.\n\nUse /addpic to add one.")

    text, markup = _build_pics_page(all_pics, 0)
    await sendMessage(message, text, buttons=markup)


# ─── Callback: listpics pagination ────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^listpics_(\d+)$") & user(Var.ADMINS))
async def listpics_page_cb(client, callback_query):
    page     = int(callback_query.matches[0].group(1))
    all_pics = await db.getAllAnimePics()
    text, markup = _build_pics_page(all_pics, page)

    await callback_query.edit_message_text(
        text,
        reply_markup=markup,
        disable_web_page_preview=True
    )
    await callback_query.answer()


# ─── Callback: close auto-delete message ──────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^close_file$"))
async def close_file_cb(client, callback_query):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


# ─── /connect ─────────────────────────────────────────────────────────────────

@bot.on_message(command("connect") & private & user(Var.ADMINS))
async def connect_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "Usage: /connect <code>&lt;anime name&gt;</code>\n\n"
            "Example: /connect <code>Hell's Paradise</code>"
        )

    anime_name = args[1].strip()
    stat       = await sendMessage(message, f"<i>Searching AniList for:</i> <b>{anime_name}</b>...")

    aniInfo = TextEditor(anime_name)
    await aniInfo.load_anilist()
    ani_id = aniInfo.adata.get('id')

    if not ani_id:
        return await editMessage(
            stat,
            f"Anime not found on AniList: <b>{anime_name}</b>\nTry a different name."
        )

    titles       = aniInfo.adata.get('title', {})
    display_name = titles.get('english') or titles.get('romaji') or anime_name

    pending_connect[message.from_user.id] = {
        'ani_id':   ani_id,
        'ani_name': display_name
    }

    await editMessage(
        stat,
        f"<b>Anime Found:</b> <i>{display_name}</i>\n"
        f"<b>AniList ID:</b> <code>{ani_id}</code>\n\n"
        f"Now <b>forward any message</b> from the channel you want to connect.\n"
        f"<i>(Bot must be admin in that channel)</i>"
    )


# ─── Forward handler for /connect ─────────────────────────────────────────────

@bot.on_message(filters.forwarded & private & user(Var.ADMINS))
async def handle_forward(client, message):
    uid = message.from_user.id
    if uid not in pending_connect:
        return

    ani_info = pending_connect.pop(uid)

    if not message.forward_from_chat:
        return await sendMessage(
            message,
            "Could not get channel info.\n\n"
            "Make sure:\n"
            "• You forwarded from a <b>channel</b> (not a group)\n"
            "• The channel's forward privacy is not restricted"
        )

    channel      = message.forward_from_chat
    channel_id   = channel.id
    channel_name = channel.title or "Unknown"

    try:
        invite      = await client.create_chat_invite_link(channel_id)
        invite_link = invite.invite_link
    except Exception:
        invite_link = f"https://t.me/{channel.username}" if channel.username else ""

    await db.connectChannel(
        ani_info['ani_id'],
        ani_info['ani_name'],
        channel_id,
        channel_name,
        invite_link
    )

    await sendMessage(
        message,
        f"<b>Channel Connected Successfully!</b>\n\n"
        f"• <b>Anime:</b> {ani_info['ani_name']}\n"
        f"• <b>AniList ID:</b> <code>{ani_info['ani_id']}</code>\n"
        f"• <b>Channel:</b> {channel_name}\n"
        f"• <b>Channel ID:</b> <code>{channel_id}</code>\n"
        f"• <b>Invite Link:</b> {invite_link}\n\n"
        f"<i>From now, this anime will be uploaded to the connected channel.</i>"
    )


# ─── /disconnect ──────────────────────────────────────────────────────────────

@bot.on_message(command("disconnect") & private & user(Var.ADMINS))
async def disconnect_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "Usage: /disconnect <code>&lt;anilist id&gt;</code>\n\n"
            "Use /connections to see all connected anime IDs."
        )

    try:
        ani_id = int(args[1].strip())
    except ValueError:
        return await sendMessage(message, "Invalid AniList ID. Must be a number.")

    conn = await db.getChannelConnection(ani_id)
    if not conn:
        return await sendMessage(
            message,
            f"No connection found for AniList ID: <code>{ani_id}</code>"
        )

    await db.disconnectChannel(ani_id)
    await sendMessage(
        message,
        f"<b>Disconnected!</b>\n\n"
        f"• <b>Anime:</b> {conn.get('ani_name', 'Unknown')}\n"
        f"• <b>Channel:</b> {conn.get('channel_name', 'Unknown')}\n\n"
        f"<i>This anime will now upload to main channel.</i>"
    )


# ─── /connections ─────────────────────────────────────────────────────────────

@bot.on_message(command("connections") & private & user(Var.ADMINS))
async def connections_cmd(client, message):
    all_conn = await db.getAllConnections()

    if not all_conn:
        return await sendMessage(
            message,
            "No channel connections found.\n\nUse /connect to add one."
        )

    text = f"<b>Channel Connections ({len(all_conn)}):</b>\n\n"
    for i, conn in enumerate(all_conn, 1):
        text += (
            f"{i}. <b>{conn.get('ani_name', 'Unknown')}</b>\n"
            f"   AniList ID: <code>{conn['_id']}</code>\n"
            f"   Channel: {conn.get('channel_name', 'Unknown')}\n"
            f"   Link: {conn.get('invite_link', 'N/A')}\n\n"
        )

    text += "<i>Use /disconnect &lt;anilist id&gt; to remove a connection.</i>"
    await sendMessage(message, text)


# ─── /delanime ────────────────────────────────────────────────────────────────

@bot.on_message(command("delanime") & private & user(Var.ADMINS))
async def delanime_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(message, "Usage: /delanime <code>&lt;anilist id&gt;</code>")

    try:
        ani_id = int(args[1].strip())
    except ValueError:
        return await sendMessage(message, "Invalid AniList ID. Must be a number.")

    await db.delAnime(ani_id)
    ani_cache['completed'].discard(ani_id)
    ani_cache['ongoing'].discard(ani_id)

    await sendMessage(message, f"Anime <code>{ani_id}</code> deleted from database.")


# ─── /users ───────────────────────────────────────────────────────────────────

@bot.on_message(command("users") & private & user(Var.ADMINS))
async def users_cmd(client, message):
    await sendMessage(message, "This feature requires user tracking setup.")


# ─── /addrss ──────────────────────────────────────────────────────────────────

@bot.on_message(command("addrss") & private & user(Var.ADMINS))
async def addrss_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "Usage: /addrss <code>&lt;url&gt;</code>\n\n"
            "Example:\n"
            "<code>/addrss https://subsplease.org/rss/?r=1080</code>"
        )

    url = args[1].strip()
    if not url.startswith("http"):
        return await sendMessage(message, "<b>Invalid URL.</b> Must start with <code>http</code>.")

    added = await db.addRSS(url)
    if not added:
        return await sendMessage(
            message,
            f"<b>Already exists!</b>\n\n"
            f"<code>{url}</code>\n\n"
            f"<i>This RSS feed is already saved.</i>"
        )

    await sendMessage(
        message,
        f"<b>RSS Feed Added!</b>\n\n"
        f"<code>{url}</code>\n\n"
        f"<i>This feed will be used instead of .env default (if any feeds are saved).</i>"
    )


# ─── /delrss ──────────────────────────────────────────────────────────────────

@bot.on_message(command("delrss") & private & user(Var.ADMINS))
async def delrss_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "Usage: /delrss <code>&lt;url&gt;</code>\n\n"
            "Use /listrss to see saved feed URLs."
        )

    url = args[1].strip()
    deleted = await db.delRSS(url)

    if not deleted:
        return await sendMessage(
            message,
            f"<b>Not found!</b>\n\n"
            f"<code>{url}</code>\n\n"
            f"<i>No saved RSS feed with that URL. Use /listrss to check.</i>"
        )

    await sendMessage(
        message,
        f"<b>RSS Feed Removed!</b>\n\n"
        f"<code>{url}</code>\n\n"
        f"<i>If no feeds remain, bot will fall back to .env default.</i>"
    )


# ─── /listrss ─────────────────────────────────────────────────────────────────

@bot.on_message(command("listrss") & private & user(Var.ADMINS))
async def listrss_cmd(client, message):
    db_rss = await db.getAllRSS()

    if not db_rss:
        default_list = "\n".join(f"<code>{u}</code>" for u in Var.RSS_ITEMS)
        return await sendMessage(
            message,
            "<b>No custom RSS feeds saved.</b>\n\n"
            "<b>Using .env default(s):</b>\n"
            f"{default_list}\n\n"
            "<i>Use /addrss &lt;url&gt; to add a custom feed.</i>"
        )

    text = f"<b>Saved RSS Feeds ({len(db_rss)}):</b>\n\n"
    for i, url in enumerate(db_rss, 1):
        text += f"{i}. <code>{url}</code>\n\n"

    text += "<i>Use /delrss &lt;url&gt; to remove a feed.</i>"
    await sendMessage(message, text)


# ─── /schedule ────────────────────────────────────────────────────────────────

@bot.on_message(command("schedule") & private & user(Var.ADMINS))
async def schedule_cmd(client, message):
    stat = await sendMessage(message, "<i>Fetching today's anime schedule...</i>")
    await send_schedule_post()
    await editMessage(stat, "<b>Schedule sent to main channel!</b>")
