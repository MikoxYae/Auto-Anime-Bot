# 🌸 Auto Anime Bot

A powerful Telegram bot that automatically fetches anime torrents from RSS feeds, encodes them to multiple quality levels, and uploads directly to Telegram channels.

---

## ✨ Features

- 📡 **Auto RSS Fetching** — Polls RSS feeds (nyaa.si, subsplease.org, etc.) on a schedule
- 🎞️ **Multi-Quality Encoding** — FFmpeg encodes to 360p / 480p / 720p / 1080p
- 📤 **Auto Upload** — Uploads encoded files to Telegram channels automatically
- 🔗 **Channel Connections** — Route specific anime to specific channels
- 🗃️ **MongoDB Backed** — All config, connections, and RSS feeds stored in DB
- 🤖 **AI Title Shortening** — Smart filenames using AI for long anime titles
- 🖼️ **Custom Posters** — Set custom thumbnail per anime
- ⏸️ **Encoding Queue Control** — Pause, resume, and reorder the FFmpeg queue
- ⚙️ **Dynamic RSS Management** — Add/remove RSS feeds live via bot commands

---

## 🛠️ Tech Stack

| Library | Purpose |
|---|---|
| `pyrofork` | Telegram client (Pyrogram fork) |
| `motor` + `pymongo` | Async MongoDB |
| `apscheduler` | Scheduled RSS polling |
| `aiohttp` | Async HTTP (RSS fetch + AniList + AI) |
| `feedparser` | RSS/Atom parsing |
| `anitopy` | Anime filename parsing |
| `torrentp` | Torrent downloading |
| `ffmpeg` | Video encoding |

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

# RSS (default fallback)
RSS_ITEMS=

# Branding
BRAND_UNAME=@YourChannel

# AI Title Shortening (Replit AI Integrations)
AI_INTEGRATIONS_OPENAI_BASE_URL=
AI_INTEGRATIONS_OPENAI_API_KEY=

# Optional
AUTO_DEL=false
DEL_TIMER=300
```

---

## 📋 Commands

### Anime
| Command | Description |
|---|---|
| `/fetch` | Toggle auto fetch on/off |
| `/addmagnet <link>` | Add magnet link manually |
| `/addtorrent` | Add .torrent file manually |
| `/schedule` | Send today's anime schedule to channel |

### RSS Feeds
| Command | Description |
|---|---|
| `/addrss <url>` | Add a custom RSS feed URL |
| `/delrss <url>` | Remove a saved RSS feed URL |
| `/listrss` | List all active RSS feeds |

### Channel Connections
| Command | Description |
|---|---|
| `/connect <anime name>` | Connect anime to a channel |
| `/disconnect <anilist id>` | Remove a connection |
| `/connections` | List all connections |

### Encoding Control
| Command | Description |
|---|---|
| `/pause` | Pause current encoding + show queue |
| `/resume` | Resume paused encoding |
| `/queue` | View and reorder the encoding queue |
| `/setffmpeg <quality>` | Set custom FFmpeg command |
| `/listffmpeg` | List saved FFmpeg configs |
| `/delffmpeg <quality>` | Delete an FFmpeg config |

### Custom Posters
| Command | Description |
|---|---|
| `/addpic <anime name>` | Set custom thumbnail for an anime |
| `/delpic <anilist id>` | Remove custom thumbnail |
| `/listpics` | List all custom thumbnails |

### Database
| Command | Description |
|---|---|
| `/delanime <anilist id>` | Delete anime data from DB |
| `/status` | Show bot status |
| `/users` | Total bot users |

---

## 📡 Recommended RSS Feeds (nyaa.si)

```
# varyg1001 — 1080p CR WEB-DL, Sub/Multi-Sub only (~1.4 GB)
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
cp .env.example .env
# Fill in your .env values
python -m bot
```

---

## 📁 Project Structure

```
bot/
├── core/
│   ├── auto_animes.py     # RSS polling + anime pipeline
│   ├── database.py        # MongoDB operations
│   ├── ffencoder.py       # FFmpeg encoding
│   ├── func_utils.py      # Utility helpers
│   ├── reporter.py        # Logging / error reporting
│   ├── text_utils.py      # AniList + AI title shortening
│   ├── tordownload.py     # Torrent downloading
│   └── tguploader.py      # Telegram upload
├── modules/
│   ├── cmds.py            # All bot commands
│   └── up_posts.py        # Schedule post sender
└── __init__.py            # Bot init + config
```

---

## 🌸 Made by Yae Miko
