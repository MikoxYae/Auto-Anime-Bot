from asyncio import sleep as asleep
from urllib.parse import unquote, parse_qs, urlparse
from pyrogram.filters import command, private, user, document
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, MessageNotModified

from bot import bot, bot_loop, Var, ani_cache
from bot.core.database import db
from bot.core.func_utils import decode, is_fsubbed, get_fsubs, editMessage, sendMessage, new_task, convertTime, getfeed
from bot.core.auto_animes import get_animes
from bot.core.tordownload import TorDownloader
from bot.core.reporter import rep

pending_torrent = {}

@bot.on_message(command('start') & private)
@new_task
async def start_msg(client, message):
    uid = message.from_user.id
    from_user = message.from_user
    txtargs = message.text.split()
    temp = await sendMessage(message, "<i>Connecting..</i>")
    if not await is_fsubbed(uid):
        txt, btns = await get_fsubs(uid, txtargs)
        return await editMessage(temp, txt, InlineKeyboardMarkup(btns))
    if len(txtargs) <= 1:
        await temp.delete()
        btns = []
        for elem in Var.START_BUTTONS.split():
            try:
                bt, link = elem.split('|', maxsplit=1)
            except:
                continue
            if len(btns) != 0 and len(btns[-1]) == 1:
                btns[-1].insert(1, InlineKeyboardButton(bt, url=link))
            else:
                btns.append([InlineKeyboardButton(bt, url=link)])
        smsg = Var.START_MSG.format(
            first_name=from_user.first_name,
            last_name=from_user.first_name,
            mention=from_user.mention,
            user_id=from_user.id
        )
        if Var.START_PHOTO:
            await message.reply_photo(
                photo=Var.START_PHOTO,
                caption=smsg,
                reply_markup=InlineKeyboardMarkup(btns) if len(btns) != 0 else None
            )
        else:
            await sendMessage(message, smsg, InlineKeyboardMarkup(btns) if len(btns) != 0 else None)
        return
    try:
        arg = (await decode(txtargs[1])).split('-')
    except Exception as e:
        await rep.report(f"User : {uid} | Error : {str(e)}", "error")
        await editMessage(temp, "<b>Input Link Code Decode Failed !</b>")
        return
    if len(arg) == 2 and arg[0] == 'get':
        try:
            fid = int(int(arg[1]) / abs(int(Var.FILE_STORE)))
        except Exception as e:
            await rep.report(f"User : {uid} | Error : {str(e)}", "error")
            await editMessage(temp, "<b>Input Link Code is Invalid !</b>")
            return
        try:
            msg = await client.get_messages(Var.FILE_STORE, message_ids=fid)
            if msg.empty:
                return await editMessage(temp, "<b>File Not Found !</b>")
            nmsg = await msg.copy(message.chat.id, reply_markup=None)
            await temp.delete()
            if Var.AUTO_DEL:
                async def auto_del(msg, timer):
                    await asleep(timer)
                    await msg.delete()
                await sendMessage(message, f'<i>File will be Auto Deleted in {convertTime(Var.DEL_TIMER)}, Forward to Saved Messages Now..</i>')
                bot_loop.create_task(auto_del(nmsg, Var.DEL_TIMER))
        except Exception as e:
            await rep.report(f"User : {uid} | Error : {str(e)}", "error")
            await editMessage(temp, "<b>File Not Found !</b>")
    else:
        await editMessage(temp, "<b>Input Link is Invalid for Usage !</b>")


@bot.on_message(command('pause') & private & user(Var.ADMINS))
async def pause_fetch(client, message):
    ani_cache['fetch_animes'] = False
    await sendMessage(message, "`Successfully Paused Fetching Animes...`")


@bot.on_message(command('resume') & private & user(Var.ADMINS))
async def resume_fetch(client, message):
    ani_cache['fetch_animes'] = True
    await sendMessage(message, "`Successfully Resumed Fetching Animes...`")


@bot.on_message(command('log') & private & user(Var.ADMINS))
@new_task
async def _log(client, message):
    await message.reply_document("log.txt", quote=True)


@bot.on_message(command('addlink') & private & user(Var.ADMINS))
@new_task
async def add_link(client, message):
    args = message.text.split()
    if len(args) <= 1:
        return await sendMessage(message, "<b>No Link Found to Add</b>")
    Var.RSS_ITEMS.append(args[1])
    await sendMessage(message, f"`Global Link Added Successfully!`\n\n    • **All Link(s) :** {', '.join(Var.RSS_ITEMS)}")


@bot.on_message(command('addtask') & private & user(Var.ADMINS))
@new_task
async def add_task(client, message):
    args = message.text.split()
    if len(args) <= 1:
        return await sendMessage(message, "<b>No Task Found to Add</b>")
    index = int(args[2]) if len(args) > 2 and args[2].isdigit() else 0
    if not (taskInfo := await getfeed(args[1], index)):
        return await sendMessage(message, "<b>No Task Found to Add for the Provided Link</b>")
    bot_loop.create_task(get_animes(taskInfo.title, taskInfo.link, True))
    await sendMessage(message, f"<i><b>Task Added Successfully!</b></i>\n\n    • <b>Task Name :</b> {taskInfo.title}\n    • <b>Task Link :</b> {args[1]}")


@bot.on_message(command('addmagnet') & private & user(Var.ADMINS))
@new_task
async def add_magnet(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) <= 1 or not args[1].startswith("magnet:"):
        return await sendMessage(message, "<b>Please provide a valid magnet link!</b>\n\n<i>Usage: /addmagnet magnet:?xt=...</i>")

    magnet = args[1].strip()

    try:
        parsed = urlparse(magnet)
        dn = parse_qs(parsed.query).get('dn', [''])[0]
        name = unquote(dn).strip()
    except Exception:
        name = ""

    if not name:
        return await sendMessage(message, "<b>Could not extract anime name from magnet link!</b>")

    await sendMessage(
        message,
        f"<i><b>Magnet Task Added!</b></i>\n\n"
        f"    • <b>Anime Name :</b> <code>{name}</code>\n"
        f"    • <b>Processing...</b>"
    )
    bot_loop.create_task(get_animes(name, magnet, True))


@bot.on_message(command('addtorrent') & private & user(Var.ADMINS))
async def add_torrent_cmd(client, message):
    uid = message.from_user.id
    pending_torrent[uid] = True
    await sendMessage(message, "<b>Send your .torrent file now:</b>")


@bot.on_message(document & private & user(Var.ADMINS))
@new_task
async def handle_torrent_file(client, message):
    uid = message.from_user.id
    if not pending_torrent.get(uid):
        return
    pending_torrent.pop(uid, None)

    doc = message.document
    if not doc.file_name.endswith(".torrent"):
        return await sendMessage(message, "<b>Invalid file! Please send a .torrent file.</b>")

    temp = await sendMessage(message, "<i>Downloading torrent file...</i>")
    torrent_path = f"torrents/{doc.file_name}"

    try:
        await client.download_media(message, file_name=torrent_path)
    except Exception as e:
        await rep.report(str(e), "error")
        return await editMessage(temp, "<b>Failed to download torrent file!</b>")

    name = await TorDownloader.get_name_from_torfile(torrent_path)
    if not name:
        return await editMessage(temp, "<b>Could not extract anime name from torrent file!</b>")

    await editMessage(
        temp,
        f"<i><b>Torrent Task Added!</b></i>\n\n"
        f"    • <b>Anime Name :</b> <code>{name}</code>\n"
        f"    • <b>Processing...</b>"
    )
    bot_loop.create_task(get_animes(name, torrent_path, True))
