import logging

import discord
from discord.ext import commands

from iroha import config
from iroha.services.dropbox_backup import DropboxBackupService
from iroha.storage import JsonStore


class IrohaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        intents.presences = True
        super().__init__(command_prefix="!", intents=intents)

        self.logger = logging.getLogger("iroha")
        self.settings_store = JsonStore(config.SETTINGS_FILE, {"guilds": {}})
        self.playgame_store = JsonStore(config.PLAYGAME_FILE, {"rooms": {}})
        self.hangout_store = JsonStore(config.HANGOUT_FILE, {"events": {}})
        self.quote_store = JsonStore(config.QUOTES_FILE, {"guilds": {}})
        self.reminder_store = JsonStore(config.REMINDERS_FILE, {"reminders": []})
        self.backup_manifest_store = JsonStore(config.BACKUP_MANIFEST_FILE, {})
        self.backup_stats_store = JsonStore(
            config.BACKUP_STATS_FILE,
            {
                "uploaded_files": 0,
                "uploaded_bytes": 0,
                "skipped_too_large": 0,
                "skipped_duplicate": 0,
                "last_error": "",
            },
        )
        self.backup_service = DropboxBackupService(self.backup_manifest_store, self.backup_stats_store)

    async def sync_allowed_guild_commands(self, remove_global: bool = True) -> int:
        if remove_global:
            global_commands = list(self.tree.get_commands(guild=None))
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            for command in global_commands:
                self.tree.add_command(command)

        synced_guilds = 0
        for guild_id in config.BACKUP_ALLOWED_GUILD_IDS:
            guild_obj = discord.Object(id=guild_id)
            self.tree.clear_commands(guild=guild_obj)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            synced_guilds += 1
            self.logger.info("Guild sync %s: %s commands", guild_id, len(synced))

        return synced_guilds

    async def setup_hook(self):
        await self.settings_store.read()
        await self.playgame_store.read()
        await self.hangout_store.read()
        await self.quote_store.read()
        await self.reminder_store.read()
        await self.backup_manifest_store.read()
        await self.backup_stats_store.read()

        extensions = [
            "iroha.cogs.core",
            "iroha.cogs.social",
            "iroha.cogs.voice",
            "iroha.cogs.backup",
            "iroha.cogs.moderation",
            "iroha.cogs.media",
            "iroha.cogs.fun",
            "iroha.cogs.reminder",
        ]
        for extension in extensions:
            await self.load_extension(extension)

    async def on_ready(self):
        self.logger.info("Iroha online as %s", self.user)

    async def get_guild_settings(self, guild_id: int) -> dict:
        data = await self.settings_store.read()
        gid = str(guild_id)
        guild = data.setdefault("guilds", {}).setdefault(
            gid,
            {
                "log_channel_id": None,
                "autojoin_enabled": False,
                "voiceinout_enabled": False,
                "voiceactivity_enabled": False,
                "voicestream_enabled": False,
                "backup_watch_channels": [],
                "muted_rules": {},
            },
        )
        await self.settings_store.write(data)
        return guild

    async def patch_guild_settings(self, guild_id: int, patcher):
        gid = str(guild_id)

        def updater(data: dict) -> dict:
            guild = data.setdefault("guilds", {}).setdefault(
                gid,
                {
                    "log_channel_id": None,
                    "autojoin_enabled": False,
                    "voiceinout_enabled": False,
                    "voiceactivity_enabled": False,
                    "voicestream_enabled": False,
                    "backup_watch_channels": [],
                    "muted_rules": {},
                },
            )
            patcher(guild)
            return data

        updated = await self.settings_store.update(updater)
        return updated["guilds"][gid]

    async def guild_log(self, guild_id: int, message: str):
        guild = self.get_guild(guild_id)
        if guild is None:
            return
        settings = await self.get_guild_settings(guild_id)
        channel_id = settings.get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            return
        try:
            await channel.send(message)
        except Exception:
            return
