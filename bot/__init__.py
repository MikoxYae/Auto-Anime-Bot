from os import path as ospath, mkdir, getenv
from logging import INFO, ERROR, FileHandler, StreamHandler, basicConfig, getLogger
from traceback import format_exc
from asyncio import Queue, Lock, new_event_loop, set_event_loop

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client
from pyrogram.enums import ParseMode
from dotenv import load_dotenv
from uvloop import install

install()
basicConfig(format="[%(asctime)s] [%(name)s | %(levelname)s] - %(message)s [%(filename)s:%(lineno)d]",
            datefmt="%m/%d/%Y, %H:%M:%S %p",
            handlers=[FileHandler('log.txt'), StreamHandler()],
            level=INFO)

getLogger("pyrogram").setLevel(ERROR)
LOGS = getLogger(__name__)

load_dotenv('config.env')

ani_cache = {
    'fetch_animes': True,
    'ongoing': set(),
    'completed': set()
}
ffpids_cache = list()

ffLock = Lock()
ffQueue = Queue()
ff_queued = dict()

class Var:
    API_ID, API_HASH, BOT_TOKEN = getenv("API_ID"), getenv("API_HASH"), getenv("BOT_TOKEN")
    MONGO_URI = getenv("MONGO_URI")

    if not BOT_TOKEN or not API_HASH or not API_ID or not MONGO_URI:
        LOGS.critical('Important Variables Missing. Fill Up and Retry..!! Exiting Now...')
        exit(1)

    RSS_ITEMS = getenv("RSS_ITEMS", "https://subsplease.org/rss/?r=1080").split()
    FSUB_CHATS = list(map(int, getenv('FSUB_CHATS', '').split()))
    BACKUP_CHANNEL = getenv("BACKUP_CHANNEL") or ""
    MAIN_CHANNEL = int(getenv("MAIN_CHANNEL"))
    LOG_CHANNEL = int(getenv("LOG_CHANNEL") or 0)
    FILE_STORE = int(getenv("FILE_STORE"))
    ADMINS = list(map(int, getenv("ADMINS", "1242011540").split()))

    SEND_SCHEDULE = getenv("SEND_SCHEDULE", "False").lower() == "true"
    BRAND_UNAME = getenv("BRAND_UNAME", "@username")
    FFCODE_1080 = getenv("FFCODE_1080") or """ffmpeg -i '{}' -progress '{}' -c:v libx264 -crf 26 -c:s copy -pix_fmt yuv420p -s 1920x1080 -b:v 150k -c:a libopus -b:a 35k -preset veryfast -map 0:v -map 0:a -map 0:s? '{}' -y"""
    FFCODE_720  = getenv("FFCODE_720")  or """ffmpeg -i '{}' -progress '{}' -c:v libx264 -crf 26 -c:s copy -pix_fmt yuv420p -s 1280x720  -b:v 150k -c:a libopus -b:a 35k -preset veryfast -map 0:v -map 0:a -map 0:s? '{}' -y"""
    FFCODE_480  = getenv("FFCODE_480")  or """ffmpeg -i '{}' -progress '{}' -c:v libx264 -crf 26 -c:s copy -pix_fmt yuv420p -s 854x480   -b:v 150k -c:a libopus -b:a 35k -preset veryfast -map 0:v -map 0:a -map 0:s? '{}' -y"""
    FFCODE_360  = getenv("FFCODE_360")  or """ffmpeg -i '{}' -progress '{}' -c:v libx264 -crf 26 -c:s copy -pix_fmt yuv420p -s 640x360   -b:v 150k -c:a libopus -b:a 35k -preset veryfast -map 0:v -map 0:a -map 0:s? '{}' -y"""
    QUALS = getenv("QUALS", "360 480 720 1080").split()

    AS_DOC = getenv("AS_DOC", "True").lower() == "true"
    THUMB = getenv("THUMB", "")
    AUTO_DEL = getenv("AUTO_DEL", "True").lower() == "true"
    DEL_TIMER = int(getenv("DEL_TIMER", "600"))
    START_PHOTO = getenv("START_PHOTO", "")
    START_MSG = getenv("START_MSG", "<b>Hey {first_name}</b>,\n\n    <i>I am Auto Animes Store & Automater Encoder Build with ❤️ !!</i>")
    START_BUTTONS = getenv("START_BUTTONS", "")

if Var.THUMB and not ospath.exists("thumb.jpg"):
    from os import system
    system(f"wget -q {Var.THUMB} -O thumb.jpg")
    LOGS.info("Thumbnail Downloaded and Saved!")
elif ospath.exists("thumb.jpg"):
    LOGS.info("Local thumb.jpg found and ready!")
else:
    LOGS.warning("No thumbnail configured. Uploads will proceed without thumbnail.")

if not ospath.isdir("encode/"):
    mkdir("encode/")
if not ospath.isdir("thumbs/"):
    mkdir("thumbs/")
if not ospath.isdir("downloads/"):
    mkdir("downloads/")

try:
    bot_loop = new_event_loop()
    set_event_loop(bot_loop)
    bot = Client(
        name="AutoAniAdvance",
        api_id=Var.API_ID,
        api_hash=Var.API_HASH,
        bot_token=Var.BOT_TOKEN,
        plugins=dict(root="bot/modules"),
        parse_mode=ParseMode.HTML
    )
    sch = AsyncIOScheduler(timezone="Asia/Kolkata", event_loop=bot_loop)
except Exception as ee:
    LOGS.error(str(ee))
    exit(1)
