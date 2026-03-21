# 🌸 Auto Anime Bot

A powerful Telegram bot that automatically fetches anime torrents from RSS feeds, encodes them to multiple quality levels, and uploads directly to Telegram channels.

---

## ✨ Features

- 📡 **Auto RSS Fetching** — Polls RSS feeds (nyaa.si, subsplease.org, etc.) on a schedule
- 🎞️ **Multi-Quality Encoding** — FFmpeg encodes to 360p / 480p / 720p / 1080p
- 📤 **Auto Upload** — Uploads encoded files to Telegram channels automatically
- 🔗 **Channel Connections** — Route specific anime to specific private/public channels
- 🎭 **Auto Stickers** — Sends a sticker after every post (separate sticker for main & connected channels, fully manageable via settings)
- 🗃️ **MongoDB Backed** — All config, connections, RSS feeds, and settings stored in DB
- 🤖 **AI Title Shortening** — Smart filenames using AI for long anime titles
- 🖼️ **Custom Posters** — Set custom thumbnail per anime
- ⏸️ **Encoding Queue Control** — Pause, resume, and reorder the FFmpeg queue
- ⚙️ **Dynamic RSS Management** — Add/remove RSS feeds live via bot commands
- 🔒 **Force Subscribe** — Require users to join channel(s) before using the bot (join mode & request mode per channel)
- 📢 **Broadcast System** — Send, forward, pin, and delete messages to all users
- 👥 **Sub Admins** — Grant limited admin access to other users
- 🗂️ **File Store** — Auto-generate deep links for uploaded files with optional auto-delete
- 📆 **Daily Schedule** — Posts today's anime release schedule to the main channel daily

---

## 🛠️ Tech Stack

| Library | Purpose |
|---|---|
| `pyrofork` | Telegram client (Pyrogram fork) |
| `motor` + `pymongo` | Async MongoDB |
| `apscheduler` | Scheduled tasks (daily restart + schedule post) |
| `aiohttp` | Async HTTP (RSS fetch + AniList + AI) |
| `feedparser` | RSS/Atom parsing |
| `anitopy` | Anime filename parsing |
| `torrentp` | Torrent downloading |
| `ffmpeg` | Video encoding |
| `uvloop` | High-performance async event loop |

---

## ⚙️ Environment Variables

```env
# Telegram
API_ID=
API_HASH=
BOT_TOKEN=
ADMINS=

# MongoDB
MONGO_URI=

# Channels
MAIN_CHANNEL=
FILE_STORE=
LOG_CHANNEL=
BACKUP_CHANNEL=

# RSS (default fallback)
RSS_ITEMS=

# Branding
BRAND_UNAME=@YourChannel

# AI Title Shortening (Replit AI Integrations)
AI_INTEGRATIONS_OPENAI_BASE_URL=
AI_INTEGRATIONS_OPENAI_API_KEY=

# Optional
AUTO_DEL=False
DEL_TIMER=600
AS_DOC=True
THUMB=
SEND_SCHEDULE=False
QUALS=360 480 720 1080

# FFmpeg (override defaults per quality)
FFCODE_1080=
FFCODE_720=
FFCODE_480=
FFCODE_360=
```

---

## 📋 Commands

### General
| Command | Description |
|---|---|
| `/start` | Start the bot |
| `/help` | Show all available commands |
| `/status` | Show bot status (fetch, queue, connections, users) |
| `/settings` | Open the bot settings panel |

### Anime
| Command | Description |
|---|---|
| `/fetch` | Toggle auto fetch on/off |
| `/addmagnet <link>` | Add magnet link manually |
| `/addtorrent` | Add .torrent file manually |
| `/schedule` | Send today's anime schedule to main channel |

### RSS Feeds
| Command | Description |
|---|---|
| `/addrss <url>` | Add a custom RSS feed URL |
| `/delrss <url>` | Remove a saved RSS feed URL |
| `/listrss` | List all active RSS feeds |

### Channel Connections
| Command | Description |
|---|---|
| `/connect <anime name> \| <channel_id>` | Connect anime to a specific channel |
| `/disconnect <anilist id>` | Remove a connection |
| `/connections` | List all connections |

### Encoding Control
| Command | Description |
|---|---|
| `/pause` | Pause current encoding + show queue reorder UI |
| `/resume` | Resume paused encoding |
| `/queue` | View and reorder the encoding queue |
| `/setffmpeg <quality>` | Set custom FFmpeg command for a quality |
| `/listffmpeg` | List saved FFmpeg configs |
| `/delffmpeg <quality>` | Delete an FFmpeg config |

### Custom Posters
| Command | Description |
|---|---|
| `/addpic <anime name>` | Set custom thumbnail for an anime |
| `/delpic <anilist id>` | Remove custom thumbnail |
| `/listpics` | List all custom thumbnails (paginated) |

### Force Subscribe
| Command | Description |
|---|---|
| `/addchnl <id>` | Add a force-sub channel |
| `/delchnl <id>` | Remove a force-sub channel |
| `/listchnl` | List all force-sub channels |
| `/fsub_mode` | Toggle request mode per channel (join vs request) |
| `/fsubstats` | View force-sub channel statistics |

### Broadcast
| Command | Description |
|---|---|
| `/broadcast` | Reply to a message to copy it to all users |
| `/fbroadcast` | Reply to a message to forward it to all users |
| `/pbroadcast` | Reply to a message to send and pin it in all users' DMs |
| `/dbroadcast <id>` | Delete a previous broadcast from all users |

### Database
| Command | Description |
|---|---|
| `/delanime <anilist id>` | Delete anime data from DB |
| `/users` | Total bot users |

---

## ⚙️ Settings Panel (`/settings`)

The settings panel provides an interactive inline UI for managing:

| Setting | Description |
|---|---|
| 👥 Sub Admins | Add or remove sub admins (main admins only) |
| ⏱ Delete Timer | Set the auto-delete timer in seconds (min 30s) |
| 🟢 Auto Delete | Toggle auto-delete for file store links ON/OFF |
| 🟢 Batch Mode | Toggle batch mode ON/OFF |
| 🎭 Stickers | Change or remove the sticker sent after each post |

### 🎭 Sticker Settings

The bot automatically sends a sticker after every anime post:

- **Main Channel Sticker** — sent after every post to the main channel
- **Connected Channel Sticker** — sent after posts to connected (private/routed) channels

Both stickers can be independently:
- **Changed** — tap Change, then send any sticker
- **Removed** — tap Remove to disable that sticker entirely

If no custom sticker is set, the default stickers are used. If removed, no sticker is sent at all.

---

## 🔒 Force Subscribe Modes

Each force-sub channel supports two modes:

| Mode | Behaviour |
|---|---|
| 📢 Join Mode (default) | User must actually join the channel |
| 📨 Request Mode | A pending join request is sufficient (no full join required) |

Toggle per channel via `/fsub_mode`.

---

## 📡 Recommended RSS Feeds (nyaa.si)

```
# varyg1001 — 1080p CR WEB-DL, Sub/Multi-Sub only
https://nyaa.si/?page=rss&u=varyg1001&q=1080p+CR+-dual

# SubsPlease — 1080p
https://nyaa.si/?page=rss&u=SubsPlease&q=1080p

# All English-translated anime
https://nyaa.si/?page=rss&c=1_2&q=1080p
```

---

## 🚀 Setup

```bash
git clone <repo>
cd auto-anime-bot
pip install -r requirements.txt
cp config.env.example config.env
# Fill in your config.env values
bash run.sh
```

---

## 📁 Project Structure

```
bot/
├── core/
│   ├── auto_animes.py     # RSS polling + anime pipeline + sticker sending
│   ├── database.py        # MongoDB operations (all collections)
│   ├── ffencoder.py       # FFmpeg encoding with progress
│   ├── func_utils.py      # Utility helpers (send/edit/encode/decode)
│   ├── reporter.py        # Logging / error reporting to LOG_CHANNEL
│   ├── text_utils.py      # AniList queries + AI title shortening + captions
│   ├── tordownload.py     # Torrent + magnet downloading
│   └── tguploader.py      # Telegram upload with progress
├── modules/
│   ├── broadcast.py       # /broadcast /fbroadcast /pbroadcast /dbroadcast
│   ├── cmds.py            # All bot commands
│   ├── fsub.py            # Force subscribe enforcement + /fsub_mode
│   ├── settings.py        # /settings panel (sub admins, timer, stickers, etc.)
│   └── up_posts.py        # Daily schedule post + auto restart
├── __init__.py            # Bot init + Var config + queue/cache setup
└── __main__.py            # Entry point + queue loop
```

---

## 🌸 Made by Team Warlords
