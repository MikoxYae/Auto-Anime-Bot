import os
from motor.motor_asyncio import AsyncIOMotorClient


class MongoDB:
    def __init__(self, uri, database_name):
        _token  = os.environ.get("BOT_TOKEN", "")
        _quals  = os.environ.get("QUALS", "360 480 720 1080").split()

        self.__client      = AsyncIOMotorClient(uri)
        self.__db          = self.__client[database_name]
        self.__animes      = self.__db.animes[_token.split(':')[0]]
        self.__connections = self.__db.channel_connections[_token.split(':')[0]]
        self.__quals       = _quals

    # ─── Anime Methods ────────────────────────────────────────────────────────

    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {q: False for q in self.__quals})
        quals[qual] = True
        await self.__animes.update_one({'_id': ani_id}, {'$set': {ep: quals}}, upsert=True)
        if post_id:
            await self.__animes.update_one({'_id': ani_id}, {'$set': {"msg_id": post_id}}, upsert=True)

    async def delAnime(self, ani_id):
        await self.__animes.delete_one({'_id': ani_id})

    async def reboot(self):
        await self.__animes.drop()

    # ─── Custom Pic Methods ───────────────────────────────────────────────────

    async def saveAnimePic(self, ani_id, file_id):
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$set': {'custom_pic': file_id}},
            upsert=True
        )

    async def getAnimePic(self, ani_id):
        doc = await self.__animes.find_one({'_id': ani_id})
        return doc.get('custom_pic') if doc else None

    async def delAnimePic(self, ani_id):
        await self.__animes.update_one(
            {'_id': ani_id},
            {'$unset': {'custom_pic': ""}}
        )

    # ─── Channel Connection Methods ───────────────────────────────────────────

    async def connectChannel(self, ani_id, ani_name, channel_id, channel_name, invite_link):
        await self.__connections.update_one(
            {'_id': ani_id},
            {'$set': {
                'ani_name':     ani_name,
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


_mongo_uri = os.environ.get("MONGO_URI", "")
db = MongoDB(_mongo_uri, "FZAutoAnimes")
