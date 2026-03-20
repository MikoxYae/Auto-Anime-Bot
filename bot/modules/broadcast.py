from asyncio import sleep as asleep
from time import time

from pyrogram import filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid

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


# ─── Progress Bar Helper ──────────────────────────────────────────────────────

def _build_bar(done, total, width=12):
    filled = round((done / max(total, 1)) * width)
    return "█" * filled + "▒" * (width - filled)

def _elapsed_str(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s" if m else f"{s}s"

def _progress_text(label, done, success, failed, total, elapsed):
    pct       = round((done / max(total, 1)) * 100, 1)
    bar       = _build_bar(done, total)
    remaining = total - done
    return (
        f"📢 <b>{label}</b>\n\n"
        f"<code>[{bar}]</code> <b>{pct}%</b>\n\n"
        f"✅ <b>Success:</b> {success}  |  ❌ <b>Failed:</b> {failed}\n"
        f"⏳ <b>Remaining:</b> {remaining} / {total}\n"
        f"⌛ <b>Elapsed:</b> {_elapsed_str(elapsed)}"
    )


# ─── Core Broadcast Engine ────────────────────────────────────────────────────

async def _do_broadcast(stat_msg, users, action, label="Broadcasting..."):
    total       = len(users)
    success     = 0
    failed      = 0
    msg_map     = {}
    start       = time()
    last_update = start

    for i, uid in enumerate(users, 1):
        try:
            sent = await action(uid)
            if sent:
                success += 1
                msg_map[str(uid)] = sent.id
            else:
                failed += 1

        except FloodWait as fw:
            await asleep(fw.value + 1)
            try:
                sent = await action(uid)
                if sent:
                    success += 1
                    msg_map[str(uid)] = sent.id
                else:
                    failed += 1
            except Exception:
                failed += 1

        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            failed += 1
            await db.delUser(uid)

        except Exception:
            failed += 1

        now = time()
        if now - last_update >= 60:
            last_update = now
            try:
                await editMessage(
                    stat_msg,
                    _progress_text(label, i, success, failed, total, now - start)
                )
            except Exception:
                pass

        await asleep(0.05)

    elapsed = time() - start
    await editMessage(
        stat_msg,
        f"✅ <b>{label.replace('...', '')} Complete!</b>\n\n"
        f"👥 <b>Total Users:</b> {total}\n"
        f"✅ <b>Success:</b> {success}\n"
        f"❌ <b>Failed:</b> {failed}\n"
        f"⌛ <b>Time Taken:</b> {_elapsed_str(elapsed)}"
    )

    return msg_map


# ─── /broadcast ───────────────────────────────────────────────────────────────

@bot.on_message(command("broadcast") & private & user(Var.ADMINS))
async def broadcast_cmd(client, message):
    reply = message.reply_to_message
    if not reply:
        return await sendMessage(
            message,
            "<b>Usage:</b> Reply to any message with /broadcast\n\n"
            "<i>Sends that message to all bot users.</i>"
        )

    users = await db.getAllUsers()
    if not users:
        return await sendMessage(message, "<b>No users found in database.</b>")

    stat = await sendMessage(
        message,
        f"📢 <b>Broadcasting...</b>\n\n"
        f"👥 <b>Total Users:</b> {len(users)}\n"
        f"<i>Progress updates every 1 minute.</i>"
    )

    broadcast_id = int(time())

    async def action(uid):
        return await reply.copy(uid)

    msg_map = await _do_broadcast(stat, users, action, "Broadcasting...")

    if msg_map:
        await db.saveBroadcast(broadcast_id, msg_map)
        await sendMessage(
            message,
            f"📌 <b>Broadcast ID:</b> <code>{broadcast_id}</code>\n\n"
            f"<i>Use this ID with /dbroadcast to delete or /pbroadcast to pin.</i>"
        )


# ─── /fbroadcast ──────────────────────────────────────────────────────────────

@bot.on_message(command("fbroadcast") & private & user(Var.ADMINS))
async def fbroadcast_cmd(client, message):
    reply = message.reply_to_message
    if not reply:
        return await sendMessage(
            message,
            "<b>Usage:</b> Reply to any message with /fbroadcast\n\n"
            "<i>Forwards that message to all users (keeps the original sender tag).</i>"
        )

    users = await db.getAllUsers()
    if not users:
        return await sendMessage(message, "<b>No users found in database.</b>")

    stat = await sendMessage(
        message,
        f"📢 <b>Forward Broadcasting...</b>\n\n"
        f"👥 <b>Total Users:</b> {len(users)}\n"
        f"<i>Progress updates every 1 minute.</i>"
    )

    broadcast_id = int(time())

    async def action(uid):
        return await client.forward_messages(uid, reply.chat.id, reply.id)

    msg_map = await _do_broadcast(stat, users, action, "Forward Broadcasting...")

    if msg_map:
        await db.saveBroadcast(broadcast_id, msg_map)
        await sendMessage(
            message,
            f"📌 <b>Broadcast ID:</b> <code>{broadcast_id}</code>\n\n"
            f"<i>Use this ID with /dbroadcast to delete later.</i>"
        )


# ─── /pbroadcast ──────────────────────────────────────────────────────────────

@bot.on_message(command("pbroadcast") & private & user(Var.ADMINS))
async def pbroadcast_cmd(client, message):
    reply = message.reply_to_message
    if not reply:
        return await sendMessage(
            message,
            "<b>Usage:</b> Reply to any message with /pbroadcast\n\n"
            "<i>Sends and pins that message in all users' DMs.</i>"
        )

    users = await db.getAllUsers()
    if not users:
        return await sendMessage(message, "<b>No users found in database.</b>")

    stat = await sendMessage(
        message,
        f"📌 <b>Pin Broadcasting...</b>\n\n"
        f"👥 <b>Total Users:</b> {len(users)}\n"
        f"<i>Progress updates every 1 minute.</i>"
    )

    broadcast_id = int(time())

    async def action(uid):
        sent = await reply.copy(uid)
        try:
            await client.pin_chat_message(uid, sent.id, disable_notification=True)
        except Exception:
            pass
        return sent

    msg_map = await _do_broadcast(stat, users, action, "Pin Broadcasting...")

    if msg_map:
        await db.saveBroadcast(broadcast_id, msg_map)
        await sendMessage(
            message,
            f"📌 <b>Broadcast ID:</b> <code>{broadcast_id}</code>\n\n"
            f"<i>Use this ID with /dbroadcast to delete later.</i>"
        )


# ─── /dbroadcast ──────────────────────────────────────────────────────────────

@bot.on_message(command("dbroadcast") & private & user(Var.ADMINS))
async def dbroadcast_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1:
        return await sendMessage(
            message,
            "<b>Usage:</b> /dbroadcast <code>&lt;broadcast_id&gt;</code>\n\n"
            "<i>The broadcast ID is shown after every broadcast.</i>"
        )

    try:
        broadcast_id = int(args[1].strip())
    except ValueError:
        return await sendMessage(message, "<b>Invalid ID.</b> Must be a number.")

    msg_map = await db.getBroadcast(broadcast_id)
    if not msg_map:
        return await sendMessage(
            message,
            f"<b>No broadcast found</b> with ID: <code>{broadcast_id}</code>"
        )

    users       = list(msg_map.keys())
    total       = len(users)
    success     = 0
    failed      = 0
    start       = time()
    last_update = start

    stat = await sendMessage(
        message,
        f"🗑 <b>Deleting Broadcast...</b>\n\n"
        f"👥 <b>Total:</b> {total}\n"
        f"<i>Progress updates every 1 minute.</i>"
    )

    for i, uid_str in enumerate(users, 1):
        uid    = int(uid_str)
        msg_id = msg_map[uid_str]
        try:
            await client.delete_messages(uid, msg_id)
            success += 1

        except FloodWait as fw:
            await asleep(fw.value + 1)
            try:
                await client.delete_messages(uid, msg_id)
                success += 1
            except Exception:
                failed += 1

        except Exception:
            failed += 1

        now = time()
        if now - last_update >= 60:
            last_update = now
            try:
                await editMessage(
                    stat,
                    _progress_text("Deleting Broadcast...", i, success, failed, total, now - start)
                )
            except Exception:
                pass

        await asleep(0.05)

    elapsed = time() - start
    await db.delBroadcast(broadcast_id)
    await editMessage(
        stat,
        f"🗑 <b>Delete Complete!</b>\n\n"
        f"✅ <b>Deleted:</b> {success}\n"
        f"❌ <b>Failed:</b> {failed}\n"
        f"⌛ <b>Time Taken:</b> {_elapsed_str(elapsed)}"
    )
