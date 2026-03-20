from asyncio import sleep as asleep

from pyrogram import filters
from pyrogram.errors import (
    UserNotParticipant,
    ChatAdminRequired,
    ChannelPrivate,
    PeerIdInvalid,
    FloodWait,
)
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatJoinRequest,
)
from pyrogram.enums import ChatMemberStatus

from bot import bot, Var
from bot.core.database import db
from bot.core.func_utils import sendMessage, editMessage


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

CHNL_PER_PAGE = 5


# ─── Join Request Listener ────────────────────────────────────────────────────

@bot.on_chat_join_request()
async def on_join_request(client, join_request: ChatJoinRequest):
    """
    Fires whenever a user sends a join request to any channel the bot manages.
    We record it so check_fsub can allow them through in request mode.
    """
    await db.saveJoinRequest(join_request.chat.id, join_request.from_user.id)


# ─── Subscription Check ───────────────────────────────────────────────────────

async def _is_member(client, channel_id: int, user_id: int) -> bool:
    """Returns True if the user is an active member of the channel."""
    try:
        member = await client.get_chat_member(channel_id, user_id)
        if member.status in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT):
            return False
        return True
    except (UserNotParticipant, ValueError):
        return False
    except (ChatAdminRequired, ChannelPrivate, PeerIdInvalid):
        return True
    except FloodWait as fw:
        await asleep(fw.value + 1)
        return await _is_member(client, channel_id, user_id)


async def get_unjoined_channels(client, user_id: int) -> list:
    """
    Returns list of channel dicts the user has NOT satisfied yet.
    Each dict: {id, title, link, request_mode}

    - request_mode=True  → user passes if they have a pending join request
    - request_mode=False → user must be an actual member
    """
    channels = await db.getAllFSubChannelsWithMode()
    unjoined = []

    for ch in channels:
        cid          = ch['id']
        request_mode = ch['request_mode']

        if await _is_member(client, cid, user_id):
            if request_mode:
                await db.delJoinRequest(cid, user_id)
            continue

        if request_mode and await db.hasJoinRequest(cid, user_id):
            continue

        try:
            chat  = await client.get_chat(cid)
            title = chat.title or str(cid)
            if request_mode:
                inv  = await client.create_chat_invite_link(cid, creates_join_request=True)
                link = inv.invite_link
            elif chat.username:
                link = f"https://t.me/{chat.username}"
            else:
                inv  = await client.create_chat_invite_link(cid)
                link = inv.invite_link
        except Exception:
            title = str(cid)
            link  = None

        unjoined.append({
            'id':           cid,
            'title':        title,
            'link':         link,
            'request_mode': request_mode,
        })

    return unjoined


async def check_fsub(client, message) -> bool:
    """
    Call at the top of any handler that needs force-sub enforcement.
    Returns True if the user passes (all channels satisfied or none configured).
    Returns False after sending the join prompt — caller must return immediately.

    Per-channel logic:
      • request_mode OFF → user must have actually joined
      • request_mode ON  → a pending join request is enough (no full join required)
    """
    user_id  = message.from_user.id
    unjoined = await get_unjoined_channels(client, user_id)

    if not unjoined:
        return True

    buttons = []
    has_request_mode = any(ch['request_mode'] for ch in unjoined)

    for ch in unjoined:
        if not ch['link']:
            continue
        if ch['request_mode']:
            label = f"📨 Request: {ch['title']}"
        else:
            label = f"📢 Join: {ch['title']}"
        buttons.append([InlineKeyboardButton(label, url=ch['link'])])

    if has_request_mode:
        verify_label = "✅ I've Joined / Requested"
    else:
        verify_label = "✅ I've Joined"

    buttons.append([InlineKeyboardButton(verify_label, callback_data="fsub_check")])

    channel_lines = []
    for ch in unjoined:
        mode_tag = " <i>(request ok)</i>" if ch['request_mode'] else ""
        channel_lines.append(f"• <b>{ch['title']}</b>{mode_tag}")

    await sendMessage(
        message,
        "<b>🔒 Access Restricted!</b>\n\n"
        "You must satisfy the following channel(s) to use this bot:\n\n"
        + "\n".join(channel_lines)
        + "\n\n<i>Tap the buttons below, then tap the verify button.</i>",
        buttons=InlineKeyboardMarkup(buttons)
    )
    return False


# ─── Callback: re-check after user claims they joined / requested ──────────────

@bot.on_callback_query(filters.regex(r"^fsub_check$"))
async def fsub_recheck_cb(client, callback_query):
    user_id  = callback_query.from_user.id
    unjoined = await get_unjoined_channels(client, user_id)

    if not unjoined:
        await callback_query.answer("✅ Access granted! You can now use the bot.", show_alert=True)
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        return

    has_request_mode = any(ch['request_mode'] for ch in unjoined)

    buttons = []
    for ch in unjoined:
        if not ch['link']:
            continue
        label = f"📨 Request: {ch['title']}" if ch['request_mode'] else f"📢 Join: {ch['title']}"
        buttons.append([InlineKeyboardButton(label, url=ch['link'])])

    verify_label = "✅ I've Joined / Requested" if has_request_mode else "✅ I've Joined"
    buttons.append([InlineKeyboardButton(verify_label, callback_data="fsub_check")])

    await callback_query.answer("❌ You haven't satisfied all channels yet!", show_alert=True)
    try:
        await callback_query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        pass


# ─── /fsub_mode ───────────────────────────────────────────────────────────────

@bot.on_message(command("fsub_mode") & private & user(Var.ADMINS))
async def fsub_mode_cmd(client, message):
    channels = await db.getAllFSubChannelsWithMode()
    if not channels:
        return await sendMessage(
            message,
            "<b>No force-sub channels configured.</b>\n\n"
            "<i>Use /addchnl &lt;id&gt; to add channels first.</i>"
        )
    text, markup = await _build_channel_list_page(client, channels, page=0)
    await sendMessage(message, text, buttons=markup)


async def _build_channel_list_page(client, channels: list, page: int):
    """Build the paginated channel list message and keyboard."""
    total       = len(channels)
    total_pages = max(1, (total + CHNL_PER_PAGE - 1) // CHNL_PER_PAGE)
    start       = page * CHNL_PER_PAGE
    page_items  = channels[start: start + CHNL_PER_PAGE]

    text = f"<b>⚙️ FSub Request Mode Settings</b>\n<i>Page {page + 1}/{total_pages}</i>\n\n"
    text += "Tap a channel to toggle its request mode:\n"

    rows = []
    for ch in page_items:
        cid  = ch['id']
        mode = ch['request_mode']
        try:
            chat_obj = await client.get_chat(cid)
            name     = chat_obj.title or str(cid)
        except Exception:
            name = str(cid)

        icon  = "📨" if mode else "📢"
        label = f"{icon} {name}"
        rows.append([InlineKeyboardButton(label, callback_data=f"fsubmode_channel_{cid}_{page}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"fsubmode_list_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"fsubmode_list_{page + 1}"))
    if nav:
        rows.append(nav)

    return text, InlineKeyboardMarkup(rows)


@bot.on_callback_query(filters.regex(r"^fsubmode_list_(\d+)$"))
async def fsubmode_list_cb(client, callback_query):
    page     = int(callback_query.matches[0].group(1))
    channels = await db.getAllFSubChannelsWithMode()
    if not channels:
        return await callback_query.answer("No channels configured.", show_alert=True)
    text, markup = await _build_channel_list_page(client, channels, page)
    try:
        await callback_query.edit_message_text(text, reply_markup=markup)
    except Exception:
        pass
    await callback_query.answer()


@bot.on_callback_query(filters.regex(r"^fsubmode_channel_(-?\d+)_(\d+)$"))
async def fsubmode_channel_cb(client, callback_query):
    cid  = int(callback_query.matches[0].group(1))
    page = int(callback_query.matches[0].group(2))

    mode = await db.getFSubChannelMode(cid)
    try:
        chat_obj = await client.get_chat(cid)
        name     = chat_obj.title or str(cid)
    except Exception:
        name = str(cid)

    mode_label = "📨 Request Mode (ON)" if mode else "📢 Join Mode (OFF)"
    text = (
        f"<b>Channel:</b> {name}\n"
        f"<b>ID:</b> <code>{cid}</code>\n\n"
        f"<b>Current Mode:</b> {mode_label}\n\n"
        f"<i>Request Mode ON</i> → user only needs to send a join request\n"
        f"<i>Request Mode OFF</i> → user must actually join the channel"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ ON" if not mode else "✅ ON (current)",
                callback_data=f"fsubmode_set_{cid}_1_{page}"
            ),
            InlineKeyboardButton(
                "❌ OFF (current)" if not mode else "❌ OFF",
                callback_data=f"fsubmode_set_{cid}_0_{page}"
            ),
        ],
        [InlineKeyboardButton("◀ Back", callback_data=f"fsubmode_list_{page}")],
    ])

    try:
        await callback_query.edit_message_text(text, reply_markup=markup)
    except Exception:
        pass
    await callback_query.answer()


@bot.on_callback_query(filters.regex(r"^fsubmode_set_(-?\d+)_([01])_(\d+)$"))
async def fsubmode_set_cb(client, callback_query):
    cid      = int(callback_query.matches[0].group(1))
    new_mode = callback_query.matches[0].group(2) == "1"
    page     = int(callback_query.matches[0].group(3))

    await db.setFSubChannelMode(cid, new_mode)

    try:
        chat_obj = await client.get_chat(cid)
        name     = chat_obj.title or str(cid)
    except Exception:
        name = str(cid)

    mode_label = "📨 Request Mode (ON)" if new_mode else "📢 Join Mode (OFF)"
    result_msg = "✅ Request Mode ON" if new_mode else "✅ Join Mode (Request Mode OFF)"

    await callback_query.answer(result_msg, show_alert=True)

    text = (
        f"<b>Channel:</b> {name}\n"
        f"<b>ID:</b> <code>{cid}</code>\n\n"
        f"<b>Current Mode:</b> {mode_label}\n\n"
        f"<i>Request Mode ON</i> → user only needs to send a join request\n"
        f"<i>Request Mode OFF</i> → user must actually join the channel"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ ON" if not new_mode else "✅ ON (current)",
                callback_data=f"fsubmode_set_{cid}_1_{page}"
            ),
            InlineKeyboardButton(
                "❌ OFF (current)" if not new_mode else "❌ OFF",
                callback_data=f"fsubmode_set_{cid}_0_{page}"
            ),
        ],
        [InlineKeyboardButton("◀ Back", callback_data=f"fsubmode_list_{page}")],
    ])

    try:
        await callback_query.edit_message_text(text, reply_markup=markup)
    except Exception:
        pass


# ─── /fsubstats ───────────────────────────────────────────────────────────────

@bot.on_message(command("fsubstats") & private & user(Var.ADMINS))
async def fsubstats_cmd(client, message):
    channels = await db.getAllFSubChannelsWithMode()
    if not channels:
        return await sendMessage(
            message,
            "<b>No force-sub channels configured.</b>\n\n"
            "<i>Use /addchnl &lt;id&gt; to add channels first.</i>"
        )

    stat = await sendMessage(message, "<i>Fetching statistics...</i>")

    total_requests = await db.getTotalJoinRequests()
    text = f"<b>📊 FSub Statistics</b>\n\n"

    for i, ch in enumerate(channels, 1):
        cid          = ch['id']
        request_mode = ch['request_mode']

        try:
            chat_obj      = await client.get_chat(cid)
            name          = chat_obj.title or str(cid)
            members_count = chat_obj.members_count or 0
        except Exception:
            name          = str(cid)
            members_count = 0

        req_count  = await db.getJoinRequestCount(cid)
        mode_label = "📨 Request Mode" if request_mode else "📢 Join Mode"

        text += (
            f"<b>{i}. {name}</b>\n"
            f"   • <b>Mode:</b> {mode_label}\n"
            f"   • <b>Members:</b> {members_count:,}\n"
            f"   • <b>Pending Requests:</b> {req_count:,}\n"
            f"   • <b>ID:</b> <code>{cid}</code>\n\n"
        )

    text += f"<b>Total Pending Requests (all channels):</b> {total_requests:,}"
    await editMessage(stat, text)


# ─── /addchnl ─────────────────────────────────────────────────────────────────

@bot.on_message(command("addchnl") & private & user(Var.ADMINS))
async def addchnl_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "<b>Usage:</b> /addchnl <code>&lt;channel_id&gt;</code>\n\n"
            "Example: /addchnl <code>-1001234567890</code>\n\n"
            "<i>The bot must be an admin in the channel.\n"
            "Channel ID is always a negative number starting with -100</i>"
        )

    raw = args[1].strip()
    try:
        channel_id = int(raw)
    except ValueError:
        return await sendMessage(
            message,
            "<b>Invalid ID.</b> Channel ID must be a number.\n\n"
            "Example: <code>-1001234567890</code>"
        )

    if channel_id > 0:
        channel_id = int(f"-100{channel_id}")

    stat = await sendMessage(message, "<i>Verifying channel...</i>")

    try:
        chat  = await client.get_chat(channel_id)
        title = chat.title or str(channel_id)
    except Exception:
        return await editMessage(
            stat,
            "<b>Could not find that channel.</b>\n\n"
            "Make sure:\n"
            "• The ID is correct\n"
            "• The bot is an admin in that channel"
        )

    added = await db.addFSubChannel(channel_id)
    if not added:
        return await editMessage(
            stat,
            f"<b>Already added!</b>\n\n"
            f"• <b>Channel:</b> {title}\n"
            f"• <b>ID:</b> <code>{channel_id}</code>\n\n"
            f"<i>This channel is already in the force-sub list.</i>"
        )

    await editMessage(
        stat,
        f"<b>✅ Force-Sub Channel Added!</b>\n\n"
        f"• <b>Channel:</b> {title}\n"
        f"• <b>ID:</b> <code>{channel_id}</code>\n"
        f"• <b>Mode:</b> 📢 Join Mode (default)\n\n"
        f"<i>Use /fsub_mode to switch to Request Mode for this channel.</i>"
    )


# ─── /delchnl ─────────────────────────────────────────────────────────────────

@bot.on_message(command("delchnl") & private & user(Var.ADMINS))
async def delchnl_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "<b>Usage:</b> /delchnl <code>&lt;channel_id&gt;</code>\n\n"
            "<i>Use /listchnl to see all saved channel IDs.</i>"
        )

    raw = args[1].strip()
    try:
        channel_id = int(raw)
    except ValueError:
        return await sendMessage(
            message,
            "<b>Invalid ID.</b> Channel ID must be a number."
        )

    if channel_id > 0:
        channel_id = int(f"-100{channel_id}")

    deleted = await db.delFSubChannel(channel_id)
    if not deleted:
        return await sendMessage(
            message,
            f"<b>Not found!</b>\n\n"
            f"No force-sub channel with ID: <code>{channel_id}</code>\n\n"
            f"<i>Use /listchnl to see saved channels.</i>"
        )

    try:
        chat  = await client.get_chat(channel_id)
        title = chat.title or str(channel_id)
    except Exception:
        title = str(channel_id)

    await sendMessage(
        message,
        f"<b>🗑 Force-Sub Channel Removed!</b>\n\n"
        f"• <b>Channel:</b> {title}\n"
        f"• <b>ID:</b> <code>{channel_id}</code>\n\n"
        f"<i>Users no longer need to join this channel.\n"
        f"All stored join requests for this channel have been cleared.</i>"
    )


# ─── /listchnl ────────────────────────────────────────────────────────────────

@bot.on_message(command("listchnl") & private & user(Var.ADMINS))
async def listchnl_cmd(client, message):
    channels = await db.getAllFSubChannelsWithMode()

    if not channels:
        return await sendMessage(
            message,
            "<b>No force-sub channels set.</b>\n\n"
            "<i>Use /addchnl &lt;id&gt; to add one.</i>"
        )

    stat = await sendMessage(message, "<i>Fetching channel info...</i>")

    text = f"<b>🔒 Force-Sub Channels ({len(channels)}):</b>\n\n"
    for i, ch in enumerate(channels, 1):
        cid          = ch['id']
        request_mode = ch['request_mode']
        try:
            chat_obj = await client.get_chat(cid)
            title    = chat_obj.title or str(cid)
            link     = f"https://t.me/{chat_obj.username}" if chat_obj.username else "Private"
        except Exception:
            title = "Unknown"
            link  = "N/A"

        mode_label = "📨 Request Mode" if request_mode else "📢 Join Mode"
        text += (
            f"{i}. <b>{title}</b>\n"
            f"   ID: <code>{cid}</code>\n"
            f"   Link: {link}\n"
            f"   Mode: {mode_label}\n\n"
        )

    text += "<i>Use /fsub_mode to manage request modes.\nUse /delchnl &lt;id&gt; to remove a channel.</i>"
    await editMessage(stat, text)
