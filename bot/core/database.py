import os
from motor.motor_asyncio import AsyncIOMotorClient


class MongoDB:
    def __init__(self, uri, database_name):
        _token  = os.environ.get("BOT_TOKEN", "")
        _quals  = os.environ.get("QUALS", "360 480 720 1080").split()

        self.__client        = AsyncIOMotorClient(uri)
        self.__db            = self.__client[database_name]
        self.__animes        = self.__db.animes[_token.split(':')[0]]
        self.__connections   = self.__db.channel_connections[_token.split(':')[0]]
        self.__ffconfigs     = self.__db.ffconfigs[_token.split(':')[0]]
        self.__rssfeeds      = self.__db.rssfeeds[_token.split(':')[0]]
        self.__users         = self.__db.users[_token.split(':')[0]]
        self.__broadcasts    = self.__db.broadcasts[_token.split(':')[0]]
        self.__fsubchannels  = self.__db.fsubchannels[_token.split(':')[0]]
        self.__joinrequests  = self.__db.joinrequests[_token.split(':')[0]]
        self.__subadmins     = self.__db.subadmins[_token.split(':')[0]]
        self.__botsettings   = self.__db.botsettings[_token.split(':')[0]]
        self.__quals         = _quals

    # ─── Anime Methods ────────────────────────────────────────────────────────

    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {q: False for q in self.__quals})
        quals[qual] = True
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {ep: quals}},
            upsert=True
        )
        if post_id:
            await self.__animes.update_one(
                {'_id': ani_id},
                {'$set': {"msg_id": post_id}},
                upsert=True
            )

    async def delAnime(self, ani_id):
        await self.__animes.delete_one({'_id': ani_id})

    async def reboot(self):
        await self.__animes.drop()

    # ─── Custom Pic Methods ───────────────────────────────────────────────────

    async def saveAnimePic(self, ani_id, file_id, ani_name=None):
        update = {'custom_pic': file_id}
        if ani_name:
            update['ani_name_pic'] = ani_name
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': update},
            upsert=True
        )

    async def getAnimePic(self, ani_id):
        doc = await self.__animes.find_one({'_id': ani_id}, {'custom_pic': 1})
        return doc.get('custom_pic') if doc else None

    async def delAnimePic(self, ani_id):
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$unset': {'custom_pic': '', 'ani_name_pic': ''}}
        )

    async def getAllAnimePics(self):
        cursor = self.__animes.find(
            {'custom_pic': {'$exists': True}},
            {'_id': 1, 'custom_pic': 1, 'ani_name_pic': 1}
        )
        return await cursor.to_list(length=None)

    # ─── Channel Connection Methods ───────────────────────────────────────────

    async def connectChannel(self, ani_id, ani_name, channel_id, channel_name, invite_link, ani_name_alt=''):
        await self.__connections.update_one(
            {'_id': ani_id},
            {'$set': {
                'ani_name':     ani_name,
                'ani_name_alt': ani_name_alt,
                'channel_id':   channel_id,
                'channel_name': channel_name,
                'invite_link':  invite_link
            }},
            upsert=True
        )

    async def disconnectChannel(self, ani_id):
        result = await self.__connections.delete_one({'_id': ani_id})
        return result.deleted_count > 0

    async def getChannelConnection(self, ani_id):
        return await self.__connections.find_one({'_id': ani_id})

    async def getAllConnections(self):
        return await self.__connections.find({}).to_list(length=None)

    # ─── FFmpeg Config Methods ────────────────────────────────────────────────

    async def saveFFConfig(self, qual: str, command: str):
        await self.__ffconfigs.update_one(
            {'_id': qual},
            {'$set': {'command': command}},
            upsert=True
        )

    async def getFFConfig(self, qual: str):
        doc = await self.__ffconfigs.find_one({'_id': qual})
        return doc['command'] if doc else None

    async def getAllFFConfigs(self):
        return await self.__ffconfigs.find({}).to_list(length=None)

    async def delFFConfig(self, qual: str):
        await self.__ffconfigs.delete_one({'_id': qual})

    # ─── RSS Feed Methods ─────────────────────────────────────────────────────

    async def addRSS(self, url: str) -> bool:
        existing = await self.__rssfeeds.find_one({'_id': url})
        if existing:
            return False
        await self.__rssfeeds.insert_one({'_id': url})
        return True

    async def delRSS(self, url: str) -> bool:
        result = await self.__rssfeeds.delete_one({'_id': url})
        return result.deleted_count > 0

    async def getAllRSS(self) -> list:
        docs = await self.__rssfeeds.find({}).to_list(length=None)
        return [doc['_id'] for doc in docs]

    # ─── User Methods ─────────────────────────────────────────────────────────

    async def addUser(self, user_id: int) -> None:
        await self.__users.update_one(
            {'_id': user_id},
            {'$set': {'_id': user_id}},
            upsert=True
        )

    async def delUser(self, user_id: int) -> None:
        await self.__users.delete_one({'_id': user_id})

    async def getAllUsers(self) -> list:
        docs = await self.__users.find({}, {'_id': 1}).to_list(length=None)
        return [doc['_id'] for doc in docs]

    async def getUserCount(self) -> int:
        return await self.__users.count_documents({})

    # ─── Broadcast Methods ────────────────────────────────────────────────────

    async def saveBroadcast(self, broadcast_id: int, msg_map: dict) -> None:
        await self.__broadcasts.update_one(
            {'_id': broadcast_id},
            {'$set': {'messages': msg_map}},
            upsert=True
        )

    async def getBroadcast(self, broadcast_id: int) -> dict:
        doc = await self.__broadcasts.find_one({'_id': broadcast_id})
        return doc.get('messages', {}) if doc else {}

    async def delBroadcast(self, broadcast_id: int) -> None:
        await self.__broadcasts.delete_one({'_id': broadcast_id})

    # ─── Force Sub Channel Methods ────────────────────────────────────────────

    async def addFSubChannel(self, channel_id: int) -> bool:
        existing = await self.__fsubchannels.find_one({'_id': channel_id})
        if existing:
            return False
        await self.__fsubchannels.insert_one({'_id': channel_id, 'request_mode': False})
        return True

    async def delFSubChannel(self, channel_id: int) -> bool:
        result = await self.__fsubchannels.delete_one({'_id': channel_id})
        if result.deleted_count > 0:
            await self.__joinrequests.delete_many({'channel_id': channel_id})
            return True
        return False

    async def getAllFSubChannels(self) -> list:
        docs = await self.__fsubchannels.find({}).to_list(length=None)
        return [doc['_id'] for doc in docs]

    async def getAllFSubChannelsWithMode(self) -> list:
        docs = await self.__fsubchannels.find({}).to_list(length=None)
        return [
            {'id': doc['_id'], 'request_mode': doc.get('request_mode', False)}
            for doc in docs
        ]

    async def getFSubChannelMode(self, channel_id: int) -> bool:
        doc = await self.__fsubchannels.find_one({'_id': channel_id}, {'request_mode': 1})
        return doc.get('request_mode', False) if doc else False

    async def setFSubChannelMode(self, channel_id: int, request_mode: bool) -> None:
        await self.__fsubchannels.update_one(
            {'_id': channel_id},
            {'$set': {'request_mode': request_mode}},
            upsert=True
        )

    # ─── Join Request Methods ─────────────────────────────────────────────────

    async def saveJoinRequest(self, channel_id: int, user_id: int) -> None:
        doc_id = f"{channel_id}:{user_id}"
        await self.__joinrequests.update_one(
            {'_id': doc_id},
            {'$set': {'channel_id': channel_id, 'user_id': user_id}},
            upsert=True
        )

    async def hasJoinRequest(self, channel_id: int, user_id: int) -> bool:
        doc_id = f"{channel_id}:{user_id}"
        return bool(await self.__joinrequests.find_one({'_id': doc_id}))

    async def delJoinRequest(self, channel_id: int, user_id: int) -> None:
        doc_id = f"{channel_id}:{user_id}"
        await self.__joinrequests.delete_one({'_id': doc_id})

    async def getJoinRequestCount(self, channel_id: int) -> int:
        return await self.__joinrequests.count_documents({'channel_id': channel_id})

    async def getTotalJoinRequests(self) -> int:
        return await self.__joinrequests.count_documents({})

    # ─── Sub Admin Methods ────────────────────────────────────────────────────

    async def addSubAdmin(self, user_id: int) -> bool:
        existing = await self.__subadmins.find_one({'_id': user_id})
        if existing:
            return False
        await self.__subadmins.insert_one({'_id': user_id})
        return True

    async def delSubAdmin(self, user_id: int) -> bool:
        result = await self.__subadmins.delete_one({'_id': user_id})
        return result.deleted_count > 0

    async def getAllSubAdmins(self) -> list:
        docs = await self.__subadmins.find({}, {'_id': 1}).to_list(length=None)
        return [doc['_id'] for doc in docs]

    async def isSubAdmin(self, user_id: int) -> bool:
        return bool(await self.__subadmins.find_one({'_id': user_id}))

    # ─── Bot Settings Methods ─────────────────────────────────────────────────

    async def setDelTimer(self, seconds: int) -> None:
        await self.__botsettings.update_one(
            {'_id': 'del_timer'},
            {'$set': {'value': seconds}},
            upsert=True
        )

    async def getDelTimer(self) -> int | None:
        doc = await self.__botsettings.find_one({'_id': 'del_timer'})
        return doc['value'] if doc else None

    async def setAutoDelete(self, enabled: bool) -> None:
        await self.__botsettings.update_one(
            {'_id': 'auto_delete'},
            {'$set': {'value': enabled}},
            upsert=True
        )

    async def getAutoDelete(self) -> bool | None:
        doc = await self.__botsettings.find_one({'_id': 'auto_delete'})
        return doc['value'] if doc else None

    async def setBatchMode(self, enabled: bool) -> None:
        await self.__botsettings.update_one(
            {'_id': 'batch_mode'},
            {'$set': {'value': enabled}},
            upsert=True
        )

    async def getBatchMode(self) -> bool | None:
        doc = await self.__botsettings.find_one({'_id': 'batch_mode'})
        return doc['value'] if doc else None

    # ─── Sticker Methods ──────────────────────────────────────────────────────

    async def getStickerMain(self) -> str | None:
        doc = await self.__botsettings.find_one({'_id': 'sticker_main'})
        return doc['value'] if doc else None

    async def setStickerMain(self, file_id: str) -> None:
        await self.__botsettings.update_one(
            {'_id': 'sticker_main'},
            {'$set': {'value': file_id}},
            upsert=True
        )

    async def delStickerMain(self) -> None:
        # Store 'REMOVED' so auto_animes knows not to send any sticker
        # (deleting the document would cause fallback to the default sticker)
        await self.__botsettings.update_one(
            {'_id': 'sticker_main'},
            {'$set': {'value': 'REMOVED'}},
            upsert=True
        )

    async def getStickerConnect(self) -> str | None:
        doc = await self.__botsettings.find_one({'_id': 'sticker_connect'})
        return doc['value'] if doc else None

    async def setStickerConnect(self, file_id: str) -> None:
        await self.__botsettings.update_one(
            {'_id': 'sticker_connect'},
            {'$set': {'value': file_id}},
            upsert=True
        )

    async def delStickerConnect(self) -> None:
        # Store 'REMOVED' so auto_animes knows not to send any sticker
        # (deleting the document would cause fallback to the default sticker)
        await self.__botsettings.update_one(
            {'_id': 'sticker_connect'},
            {'$set': {'value': 'REMOVED'}},
            upsert=True
        )


_mongo_uri = os.environ.get("MONGO_URI", "")
db = MongoDB(_mongo_uri, "FZAutoAnimes")
