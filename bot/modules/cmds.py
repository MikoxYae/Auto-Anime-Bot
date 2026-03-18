from asyncio import sleep as asleep
from traceback import format_exc
from urllib.parse import unquote

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from bot import bot, Var, ani_cache, LOGS
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


# ─── Pending state dicts ──────────────────────────────────────────────────────

pending_connect = {}
pending_torrent = {}
pending_pic     = {}


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
        return "<b>Koi custom pic set nahi hai.</b>", None

    text = f"<b>🖼 Custom Pics — Page {page + 1}/{total_pages} ({total} total):</b>\n\n"
    for i, item in enumerate(page_items, start + 1):
        name   = item.get('ani_name_pic') or 'Unknown'
        ani_id = item['_id']
        text  += f"{i}. <b>{name}</b>\n   └ <code>{ani_id}</code>\n\n"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"listpics_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"listpics_{page + 1}"))

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
                bot.loop.create_task(_replace_after_delete(sent, warn_msg, Var.DEL_TIMER, file_name, args[1]))
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
        "/users - Total bot users"
    )


# ─── /status ──────────────────────────────────────────────────────────────────

@bot.on_message(command("status") & private & user(Var.ADMINS))
async def status_cmd(client, message):
    fetch_status = "✅ Running" if ani_cache['fetch_animes'] else "🔴 Stopped"
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
    state = "✅ Enabled" if ani_cache['fetch_animes'] else "🔴 Disabled"
    await sendMessage(message, f"Auto Fetch: <b>{state}</b>")


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
        f"✅ <b>Anime Found:</b> <i>{display_name}</i>\n"
        f"<b>AniList ID:</b> <code>{ani_id}</code>\n\n"
        f"Ab <b>picture send karo</b> jo is anime ke liye set karni hai."
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
        f"✅ <b>Picture Set Successfully!</b>\n\n"
        f"• <b>Anime:</b> {info['ani_name']}\n"
        f"• <b>AniList ID:</b> <code>{info['ani_id']}</code>\n\n"
        f"<i>Ab se is anime ke liye yeh picture use hogi.</i>"
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
        f"✅ Custom picture removed for <code>{ani_id}</code>.\n\n"
        f"<i>AniList default poster use hoga ab se.</i>"
    )


# ─── /listpics ────────────────────────────────────────────────────────────────

@bot.on_message(command("listpics") & private & user(Var.ADMINS))
async def listpics_cmd(client, message):
    all_pics = await db.getAllAnimePics()

    if not all_pics:
        return await sendMessage(message, "Koi custom pic set nahi hai.\n\nUse /addpic to add one.")

    text, markup = _build_pics_page(all_pics, 0)
    await sendMessage(message, text, buttons=markup)


# ─── Callback: listpics pagination ───────────────────────────────────────────

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


# ─── Callback: close auto-delete message ─────────────────────────────────────

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
        f"✅ <b>Anime Found:</b> <i>{display_name}</i>\n"
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
        f"✅ <b>Channel Connected Successfully!</b>\n\n"
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
        f"✅ <b>Disconnected!</b>\n\n"
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
            f"   ├ <b>AniList ID:</b> <code>{conn['_id']}</code>\n"
            f"   ├ <b>Channel:</b> {conn.get('channel_name', 'Unknown')}\n"
            f"   └ <b>Link:</b> {conn.get('invite_link', 'N/A')}\n\n"
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

    await sendMessage(message, f"✅ Anime <code>{ani_id}</code> deleted from database.")


# ─── /users ───────────────────────────────────────────────────────────────────

@bot.on_message(command("users") & private & user(Var.ADMINS))
async def users_cmd(client, message):
    await sendMessage(message, "This feature requires user tracking setup.")


# ─── /schedule ────────────────────────────────────────────────────────────────

@bot.on_message(command("schedule") & private & user(Var.ADMINS))
async def schedule_cmd(client, message):
    stat = await sendMessage(message, "<i>Fetching today's anime schedule...</i>")
    await send_schedule_post()
    await editMessage(stat, "✅ <b>Schedule sent to main channel!</b>")
