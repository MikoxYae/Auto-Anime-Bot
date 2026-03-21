from asyncio import sleep as asleep
from traceback import format_exc

from pyrogram import filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, Var
from bot.core.database import db
from bot.core.func_utils import sendMessage
from bot.core.text_utils import TextEditor
from bot.core.tordownload import BATCH_STICKER_OPEN, BATCH_STICKER_CLOSE
from bot.modules.fsub import check_fsub

# ─── Callback data format ─────────────────────────────────────────────────────
# "batch_dl_{ani_id}_{qual}"
# Example: "batch_dl_12345_360"
# ─────────────────────────────────────────────────────────────────────────────


async def _send_batch_to_user(client, user_id: int, ani_id: int, qual: str) -> bool:
    """
    Core delivery function:
      1. Get batch file IDs from DB for this anime + quality
      2. Send: Photo+Caption → Opening Sticker → All Episode Files → Closing Sticker
    Returns True on success, False if no data found.
    """
    batch_data = await db.getBatchFiles(ani_id, qual)
    if not batch_data:
        return False

    title      = batch_data.get('title', 'Anime')
    total_eps  = batch_data.get('total_eps', 0)
    file_ids   = batch_data.get('file_ids', [])   # list of FILE_STORE message IDs (ints)
    poster     = batch_data.get('poster', None)
    orig_name  = batch_data.get('original_name', '')

    if not file_ids:
        return False

    # ── 1. Photo + Caption ────────────────────────────────────────────────────
    caption = TextEditor.get_batch_delivery_caption(
        title      = title,
        total_eps  = total_eps,
        qual       = qual,
        original_name = orig_name,
    )

    try:
        if poster:
            await client.send_photo(
                chat_id = user_id,
                photo   = poster,
                caption = caption,
            )
        else:
            await client.send_message(
                chat_id = user_id,
                text    = caption,
            )
    except FloodWait as fw:
        await asleep(fw.value + 1)
    except Exception:
        pass

    await asleep(0.5)

    # ── 2. Opening Sticker ────────────────────────────────────────────────────
    try:
        await client.send_sticker(user_id, BATCH_STICKER_OPEN)
    except Exception:
        pass

    await asleep(0.5)

    # ── 3. All Episode Files ──────────────────────────────────────────────────
    for msg_id in file_ids:
        try:
            await client.copy_message(
                chat_id     = user_id,
                from_chat_id = Var.FILE_STORE,
                message_id  = msg_id,
            )
        except FloodWait as fw:
            await asleep(fw.value + 1)
            try:
                await client.copy_message(
                    chat_id      = user_id,
                    from_chat_id = Var.FILE_STORE,
                    message_id   = msg_id,
                )
            except Exception:
                pass
        except Exception:
            pass
        await asleep(0.3)

    # ── 4. Closing Sticker ────────────────────────────────────────────────────
    try:
        await client.send_sticker(user_id, BATCH_STICKER_CLOSE)
    except Exception:
        pass

    return True


# ─── Callback Handler ─────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^batch_dl_(-?\d+)_(\d+)$"))
async def batch_download_cb(client, callback_query):
    """
    Triggered when a user taps a batch quality button on a channel post.
    callback_data format: batch_dl_{ani_id}_{qual}
    """
    user_id = callback_query.from_user.id

    # ── Batch mode gate ───────────────────────────────────────────────────────
    batch_mode = await db.getBatchMode()
    if not batch_mode:
        await callback_query.answer(
            "⚠️ Batch mode is currently disabled.",
            show_alert=True
        )
        return

    # ── FSub check ────────────────────────────────────────────────────────────
    # We need a message-like object for check_fsub — use a dummy approach:
    # Instead, build a minimal check directly
    from bot.modules.fsub import get_unjoined_channels
    unjoined = await get_unjoined_channels(client, user_id)
    if unjoined:
        buttons = []
        has_req = any(ch['request_mode'] for ch in unjoined)
        for ch in unjoined:
            if not ch['link']:
                continue
            label = f"📨 Request: {ch['title']}" if ch['request_mode'] else f"📢 Join: {ch['title']}"
            buttons.append([InlineKeyboardButton(label, url=ch['link'])])
        verify_label = "✅ I've Joined / Requested" if has_req else "✅ I've Joined"
        buttons.append([InlineKeyboardButton(verify_label, callback_data="fsub_check")])
        await callback_query.answer("🔒 Please join required channels first!", show_alert=True)
        try:
            await client.send_message(
                chat_id     = user_id,
                text        = (
                    "<b>🔒 Access Restricted!</b>\n\n"
                    "Join these channels to receive batch files:\n\n"
                    + "\n".join(f"• <b>{ch['title']}</b>" for ch in unjoined)
                    + "\n\n<i>Tap verify after joining.</i>"
                ),
                reply_markup = InlineKeyboardMarkup(buttons),
            )
        except Exception:
            pass
        return

    # ── Parse callback data ───────────────────────────────────────────────────
    ani_id = int(callback_query.matches[0].group(1))
    qual   = callback_query.matches[0].group(2)        # e.g. "360"

    await callback_query.answer("📦 Sending batch files to your DM...", show_alert=False)

    # ── Register user ─────────────────────────────────────────────────────────
    await db.addUser(user_id)

    # ── Deliver ───────────────────────────────────────────────────────────────
    try:
        success = await _send_batch_to_user(client, user_id, ani_id, qual)
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
        await db.delUser(user_id)
        return
    except Exception:
        success = False

    if not success:
        try:
            await client.send_message(
                chat_id = user_id,
                text    = "❌ <b>Batch files not found.</b>\n\n<i>They may have been removed. Contact admin.</i>",
            )
        except Exception:
            pass
