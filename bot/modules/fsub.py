from pyrogram import filters
from pyrogram.errors import (
    UserNotParticipant,
    ChatAdminRequired,
    ChannelPrivate,
    PeerIdInvalid,
    FloodWait,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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


# ─── Subscription Check ───────────────────────────────────────────────────────

async def get_unjoined_channels(client, user_id: int) -> list:
    """
    Returns a list of channel dicts {id, title, invite_link} that the user
    has NOT joined yet. Empty list = user is subscribed to everything.
    """
    channels = await db.getAllFSubChannels()
    unjoined = []

    for cid in channels:
        try:
            member = await client.get_chat_member(cid, user_id)
            if member.status in (
                ChatMemberStatus.BANNED,
                ChatMemberStatus.LEFT,
            ):
                raise UserNotParticipant
        except (UserNotParticipant, ValueError):
            try:
                chat = await client.get_chat(cid)
                title = chat.title or str(cid)
                if chat.username:
                    link = f"https://t.me/{chat.username}"
                else:
                    inv  = await client.create_chat_invite_link(cid)
                    link = inv.invite_link
                unjoined.append({'id': cid, 'title': title, 'link': link})
            except Exception:
                unjoined.append({'id': cid, 'title': str(cid), 'link': None})
        except (ChatAdminRequired, ChannelPrivate, PeerIdInvalid):
            pass
        except FloodWait as fw:
            from asyncio import sleep as asleep
            await asleep(fw.value + 1)

    return unjoined


async def check_fsub(client, message) -> bool:
    """
    Call this at the top of any handler that needs force-sub enforcement.
    Returns True if the user passes (all joined or no channels set).
    Returns False after sending them the join prompt — caller should return.
    """
    user_id  = message.from_user.id
    unjoined = await get_unjoined_channels(client, user_id)

    if not unjoined:
        return True

    buttons = []
    for ch in unjoined:
        if ch['link']:
            buttons.append([InlineKeyboardButton(f"Join: {ch['title']}", url=ch['link'])])

    buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="fsub_check")])

    await sendMessage(
        message,
        "<b>🔒 Access Restricted!</b>\n\n"
        "You must join the following channel(s) to use this bot:\n\n"
        + "\n".join(f"• <b>{ch['title']}</b>" for ch in unjoined)
        + "\n\n<i>Click the buttons below to join, then tap ✅ I've Joined.</i>",
        buttons=InlineKeyboardMarkup(buttons)
    )
    return False


# ─── Callback: re-check after user claims they joined ─────────────────────────

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

    buttons = []
    for ch in unjoined:
        if ch['link']:
            buttons.append([InlineKeyboardButton(f"Join: {ch['title']}", url=ch['link'])])
    buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="fsub_check")])

    await callback_query.answer(
        "❌ You haven't joined all channels yet!",
        show_alert=True
    )
    try:
        await callback_query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        pass


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
        f"• <b>ID:</b> <code>{channel_id}</code>\n\n"
        f"<i>Users must now join this channel to use the bot.</i>"
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
        f"<i>Users no longer need to join this channel.</i>"
    )


# ─── /listchnl ────────────────────────────────────────────────────────────────

@bot.on_message(command("listchnl") & private & user(Var.ADMINS))
async def listchnl_cmd(client, message):
    channels = await db.getAllFSubChannels()

    if not channels:
        return await sendMessage(
            message,
            "<b>No force-sub channels set.</b>\n\n"
            "<i>Use /addchnl &lt;id&gt; to add one.</i>"
        )

    stat = await sendMessage(message, "<i>Fetching channel info...</i>")

    text = f"<b>🔒 Force-Sub Channels ({len(channels)}):</b>\n\n"
    for i, cid in enumerate(channels, 1):
        try:
            chat  = await client.get_chat(cid)
            title = chat.title or str(cid)
            link  = f"https://t.me/{chat.username}" if chat.username else "Private"
        except Exception:
            title = "Unknown"
            link  = "N/A"

        text += (
            f"{i}. <b>{title}</b>\n"
            f"   ID: <code>{cid}</code>\n"
            f"   Link: {link}\n\n"
        )

    text += "<i>Use /delchnl &lt;id&gt; to remove a channel.</i>"
    await editMessage(stat, text)
