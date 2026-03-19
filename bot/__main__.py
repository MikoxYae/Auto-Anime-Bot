from asyncio import create_task, create_subprocess_exec, create_subprocess_shell, run as asyrun, all_tasks, gather, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from os import path as ospath, execl, kill
from sys import executable
from signal import SIGKILL, SIGSTOP, SIGCONT

from bot import bot, Var, bot_loop, sch, LOGS, ffQueue, ffLock, ffpids_cache, ff_queued, ff_queue_names, ff_queue_order
from bot.core.auto_animes import fetch_animes
from bot.core.func_utils import clean_up, new_task, editMessage
from bot.modules.up_posts import upcoming_animes

@bot.on_message(command('restart') & user(Var.ADMINS))
@new_task
async def restart(client, message):
    rmessage = await message.reply('<i>Restarting...</i>')
    if sch.running:
        sch.shutdown(wait=False)
    await clean_up()
    if len(ffpids_cache) != 0:
        for pid in ffpids_cache:
            try:
                LOGS.info(f"Process ID : {pid}")
                kill(pid, SIGKILL)
            except (OSError, ProcessLookupError):
                LOGS.error("Killing Process Failed !!")
                continue
    await (await create_subprocess_exec('python3', 'update.py')).wait()
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{rmessage.chat.id}\n{rmessage.id}\n")
    execl(executable, executable, "-m", "bot")

async def restart():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="<i>Restarted !</i>")
        except Exception as e:
            LOGS.error(e)

async def queue_loop():
    LOGS.info("Queue Loop Started !!")
    while True:
        if ff_queue_order:
            while ffLock.locked():
                await asleep(1)

            post_id = ff_queue_order.pop(0)
            ff_queue_names.pop(post_id, None)

            try:
                ffQueue.get_nowait()
                ffQueue.task_done()
            except Exception:
                pass

            if post_id in ff_queued:
                ff_queued[post_id].set()

            await asleep(3)
        else:
            await asleep(2)

async def main():
    sch.add_job(upcoming_animes, "cron", hour=0, minute=30)
    await bot.start()
    await restart()
    LOGS.info('Auto Anime Bot Started!')
    sch.start()
    bot_loop.create_task(queue_loop())
    await fetch_animes()
    await idle()
    LOGS.info('Auto Anime Bot Stopped!')
    await bot.stop()
    for task in all_tasks:
        task.cancel()
    await clean_up()
    LOGS.info('Finished AutoCleanUp !!')

if __name__ == '__main__':
    bot_loop.run_until_complete(main())
