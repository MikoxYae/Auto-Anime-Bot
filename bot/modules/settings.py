from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import bot, Var
from bot.core.database import db
from bot.core.func_utils import sendMessage


# ─── Filter Helpers ───────────────────────────────────────────────────────────

def command(cmd):
    return filters.command(cmd, prefixes="/")

def admin_filter():
    return filters.user([int(x) for x in Var.ADMINS])

private = filters.private


# ─── Pending state dicts ──────────────────────────────────────────────────────

pending_add_subadmin = {}   # uid → True
pending_set_timer    = {}   # uid → True


# ─── Auth Helper ─────────────────────────────────────────────────────────────

async def _is_authorized(user_id: int) -> bool:
    if user_id in Var.ADMINS:
        return True
    return await db.isSubAdmin(user_id)


# ─── Panel Builders ───────────────────────────────────────────────────────────

async def _settings_text() -> str:
    sub_admins = await db.getAllSubAdmins()
    db_timer   = await db.getDelTimer()
    db_autodel = await db.getAutoDelete()

    timer_val  = db_timer if db_timer is not None else Var.DEL_TIMER
    auto_del   = db_autodel if db_autodel is not None else Var.AUTO_DEL
    mins, secs = divmod(timer_val, 60)
    ad_status  = "ON ✅" if auto_del else "OFF ❌"
    sa_count   = len(sub_admins)

    return (
        "⚙️ <b>Bot Settings</b>\n\n"
        f"• <b>Main Channel:</b>  <code>{Var.MAIN_CHANNEL}</code>\n"
        f"• <b>File Store:</b>    <code>{Var.FILE_STORE}</code>\n"
        f"• <b>Auto Delete:</b>   {ad_status}\n"
        f"• <b>Delete Timer:</b>  <code>{timer_val}s</code>  ({mins}m {secs}s)\n"
        f"• <b>Sub Admins:</b>    <code>{sa_count}</code>\n\n"
        "<i>Tap a button below to manage settings.</i>"
    )

async def _settings_markup() -> InlineKeyboardMarkup:
    db_autodel = await db.getAutoDelete()
    auto_del   = db_autodel if db_autodel is not None else Var.AUTO_DEL
    ad_label   = "🟢 Auto Delete: ON" if auto_del else "🔴 Auto Delete: OFF"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Sub Admins",  callback_data="stg_subadmin"),
            InlineKeyboardButton("⏱ Delete Time", callback_data="stg_deltime"),
        ],
        [
            InlineKeyboardButton(ad_label, callback_data="stg_toggle_autodel"),
        ]
    ])


async def _subadmin_text_markup():
    sub_admins = await db.getAllSubAdmins()

    text = "👥 <b>Sub Admin Management</b>\n\n"
    if not sub_admins:
        text += "<i>No sub admins added yet.</i>\n"
    else:
        for i, uid in enumerate(sub_admins, 1):
            text += f"<b>{i}.</b> <code>{uid}</code>\n"

    rows = []
    for uid in sub_admins:
        rows.append([
            InlineKeyboardButton(f"🗑 Remove {uid}", callback_data=f"stg_del_sa_{uid}")
        ])
    rows.append([
        InlineKeyboardButton("➕ Add Sub Admin", callback_data="stg_add_sa"),
        InlineKeyboardButton("◀️ Back",          callback_data="stg_back"),
    ])

    return text, InlineKeyboardMarkup(rows)


async def _deltime_text_markup():
    db_timer   = await db.getDelTimer()
    timer_val  = db_timer if db_timer is not None else Var.DEL_TIMER
    mins, secs = divmod(timer_val, 60)
    source     = "Database" if db_timer is not None else ".env default"

    text = (
        "⏱ <b>Delete Time Settings</b>\n\n"
        f"• <b>Current Timer:</b> <code>{timer_val}s</code>  ({mins}m {secs}s)\n"
        f"• <b>Source:</b> {source}\n\n"
        "<i>Files are auto-deleted after this duration.\n"
        "Tap the button and send value in seconds.</i>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set Timer", callback_data="stg_set_timer")],
        [InlineKeyboardButton("◀️ Back",      callback_data="stg_back")],
    ])

    return text, markup


# ─── /settings command ────────────────────────────────────────────────────────

@bot.on_message(command("settings") & private & admin_filter())
async def settings_cmd(client, message):
    text   = await _settings_text()
    markup = await _settings_markup()
    await sendMessage(message, text, buttons=markup)


# ─── Callback: back to main panel ────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_back$"))
async def stg_back_cb(client, cq):
    if not await _is_authorized(cq.from_user.id):
        return await cq.answer("You are not authorized.", show_alert=True)

    text   = await _settings_text()
    markup = await _settings_markup()
    await cq.edit_message_text(text, reply_markup=markup)
    await cq.answer()


# ─── Callback: Auto Delete toggle ────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_toggle_autodel$"))
async def stg_toggle_autodel_cb(client, cq):
    if not await _is_authorized(cq.from_user.id):
        return await cq.answer("You are not authorized.", show_alert=True)

    db_autodel  = await db.getAutoDelete()
    current     = db_autodel if db_autodel is not None else Var.AUTO_DEL
    new_val     = not current

    await db.setAutoDelete(new_val)
    Var.AUTO_DEL = new_val

    status = "ON ✅" if new_val else "OFF ❌"
    await cq.answer(f"Auto Delete is now {status}", show_alert=True)

    text   = await _settings_text()
    markup = await _settings_markup()
    await cq.edit_message_text(text, reply_markup=markup)


# ─── Callback: Sub Admins panel ───────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_subadmin$"))
async def stg_subadmin_cb(client, cq):
    if cq.from_user.id not in Var.ADMINS:
        return await cq.answer("Only main admins can manage sub admins.", show_alert=True)

    text, markup = await _subadmin_text_markup()
    await cq.edit_message_text(text, reply_markup=markup)
    await cq.answer()


# ─── Callback: Add Sub Admin trigger ─────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_add_sa$"))
async def stg_add_sa_cb(client, cq):
    if cq.from_user.id not in Var.ADMINS:
        return await cq.answer("Only main admins can add sub admins.", show_alert=True)

    pending_add_subadmin[cq.from_user.id] = True

    await cq.edit_message_text(
        "👥 <b>Add Sub Admin</b>\n\n"
        "Send the <b>Telegram User ID</b> of the new sub admin.\n\n"
        "<i>They will be able to manage Delete Time settings.</i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="stg_add_sa_cancel")]
        ])
    )
    await cq.answer()


# ─── Callback: Cancel Add Sub Admin ──────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_add_sa_cancel$"))
async def stg_add_sa_cancel_cb(client, cq):
    pending_add_subadmin.pop(cq.from_user.id, None)
    text, markup = await _subadmin_text_markup()
    await cq.edit_message_text(text, reply_markup=markup)
    await cq.answer("Cancelled.")


# ─── Callback: Remove Sub Admin ──────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_del_sa_(\d+)$"))
async def stg_del_sa_cb(client, cq):
    if cq.from_user.id not in Var.ADMINS:
        return await cq.answer("Only main admins can remove sub admins.", show_alert=True)

    uid_to_remove = int(cq.matches[0].group(1))
    removed = await db.delSubAdmin(uid_to_remove)

    await cq.answer(
        f"Removed {uid_to_remove}." if removed else "Not found.",
        show_alert=True
    )

    text, markup = await _subadmin_text_markup()
    await cq.edit_message_text(text, reply_markup=markup)


# ─── Callback: Delete Time panel ─────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_deltime$"))
async def stg_deltime_cb(client, cq):
    if not await _is_authorized(cq.from_user.id):
        return await cq.answer("You are not authorized.", show_alert=True)

    text, markup = await _deltime_text_markup()
    await cq.edit_message_text(text, reply_markup=markup)
    await cq.answer()


# ─── Callback: Set Timer trigger ─────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_set_timer$"))
async def stg_set_timer_cb(client, cq):
    if not await _is_authorized(cq.from_user.id):
        return await cq.answer("You are not authorized.", show_alert=True)

    pending_set_timer[cq.from_user.id] = True

    await cq.edit_message_text(
        "⏱ <b>Set Delete Timer</b>\n\n"
        "Send the new timer value in <b>seconds</b>.\n\n"
        "<b>Examples:</b>\n"
        "• <code>300</code>  →  5 minutes\n"
        "• <code>600</code>  →  10 minutes\n"
        "• <code>1800</code> →  30 minutes\n\n"
        "<i>Minimum: 30 seconds.</i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="stg_set_timer_cancel")]
        ])
    )
    await cq.answer()


# ─── Callback: Cancel Set Timer ──────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^stg_set_timer_cancel$"))
async def stg_set_timer_cancel_cb(client, cq):
    pending_set_timer.pop(cq.from_user.id, None)
    text, markup = await _deltime_text_markup()
    await cq.edit_message_text(text, reply_markup=markup)
    await cq.answer("Cancelled.")


# ─── Message handler: pending text inputs (group=1 to avoid conflicts) ────────

@bot.on_message(filters.text & private, group=1)
async def handle_settings_input(client, message):
    uid = message.from_user.id

    # ── Add Sub Admin ────────────────────────────────────────────────────────
    if uid in pending_add_subadmin:
        if uid not in Var.ADMINS:
            pending_add_subadmin.pop(uid, None)
            return

        pending_add_subadmin.pop(uid)
        raw = message.text.strip()

        try:
            new_sa_id = int(raw)
        except ValueError:
            await sendMessage(
                message,
                "❌ <b>Invalid ID.</b>\n\nUser ID must be a number.\nSend /settings and try again."
            )
            return

        if new_sa_id in Var.ADMINS:
            await sendMessage(
                message,
                f"⚠️ <code>{new_sa_id}</code> is already a main admin."
            )
            return

        added = await db.addSubAdmin(new_sa_id)
        if added:
            await sendMessage(
                message,
                f"✅ <b>Sub Admin Added!</b>\n\n"
                f"• <b>User ID:</b> <code>{new_sa_id}</code>\n\n"
                "<i>They can now manage Delete Time settings.\n"
                "Send /settings to continue.</i>"
            )
        else:
            await sendMessage(
                message,
                f"⚠️ <code>{new_sa_id}</code> is already a sub admin."
            )
        return

    # ── Set Timer ────────────────────────────────────────────────────────────
    if uid in pending_set_timer:
        if not await _is_authorized(uid):
            pending_set_timer.pop(uid, None)
            return

        pending_set_timer.pop(uid)
        raw = message.text.strip()

        try:
            seconds = int(raw)
        except ValueError:
            await sendMessage(
                message,
                "❌ <b>Invalid value.</b>\n\nMust be a whole number in seconds.\nSend /settings and try again."
            )
            return

        if seconds < 30:
            await sendMessage(
                message,
                "❌ <b>Too short.</b>\n\nMinimum is <b>30 seconds</b>.\nSend /settings and try again."
            )
            return

        await db.setDelTimer(seconds)
        mins, secs = divmod(seconds, 60)
        await sendMessage(
            message,
            f"✅ <b>Delete Timer Updated!</b>\n\n"
            f"• <b>New Timer:</b> <code>{seconds}s</code>  ({mins}m {secs}s)\n\n"
            "<i>Send /settings to continue.</i>"
        )
        return
