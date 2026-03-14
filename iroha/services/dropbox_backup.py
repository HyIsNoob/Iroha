import asyncio
import hashlib
from datetime import datetime, timezone

import aiohttp
import dropbox

from iroha import config
from iroha.storage import JsonStore


class DropboxBackupService:
    def __init__(self, manifest_store: JsonStore, stats_store: JsonStore):
        self.manifest_store = manifest_store
        self.stats_store = stats_store
        self.enabled = all([
            config.DROPBOX_APP_KEY,
            config.DROPBOX_APP_SECRET,
            config.DROPBOX_REFRESH_TOKEN,
        ])
        self._client = None

    def _get_client(self):
        if not self.enabled:
            return None
        if self._client is None:
            self._client = dropbox.Dropbox(
                oauth2_refresh_token=config.DROPBOX_REFRESH_TOKEN,
                app_key=config.DROPBOX_APP_KEY,
                app_secret=config.DROPBOX_APP_SECRET,
            )
        return self._client

    @staticmethod
    def _media_type(attachment) -> str:
        content_type = attachment.content_type or ""
        lower_name = attachment.filename.lower()
        image_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        video_ext = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
        if content_type.startswith("image/") or lower_name.endswith(image_ext):
            return "image"
        if content_type.startswith("video/") or lower_name.endswith(video_ext):
            return "video"
        return ""

    async def _upload_bytes(self, data: bytes, dropbox_path: str):
        client = self._get_client()
        if client is None:
            return False, "Dropbox chưa cấu hình"
        loop = asyncio.get_running_loop()

        def do_upload():
            client.files_upload(data, dropbox_path, mode=dropbox.files.WriteMode("overwrite"))

        try:
            await loop.run_in_executor(None, do_upload)
            return True, None
        except Exception as exc:
            return False, str(exc)

    async def backup_attachment(self, guild_id: int, channel_id: int, channel_name: str, message_id: int, attachment) -> tuple[bool, str]:
        if guild_id not in config.BACKUP_ALLOWED_GUILD_IDS:
            return False, "skip_not_allowed_guild"
        media_type = self._media_type(attachment)
        if not media_type:
            return False, "skip_not_media"
        if attachment.size > config.BACKUP_MAX_FILE_MB * 1024 * 1024:
            return False, "skip_too_large"

        manifest = await self.manifest_store.read()
        key = f"{message_id}:{attachment.id}"
        if key in manifest:
            return False, "skip_duplicate"

        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as response:
                if response.status != 200:
                    return False, f"download_failed_{response.status}"
                payload = await response.read()

        sha = hashlib.sha256(payload).hexdigest()
        safe_channel = channel_name.replace("/", "_").replace(" ", "-")
        safe_name = attachment.filename.replace("/", "_")
        folder = "images" if media_type == "image" else "videos"
        dropbox_path = f"{config.DROPBOX_BACKUP_ROOT}/{safe_channel}/{folder}/{safe_name}"

        ok, err = await self._upload_bytes(payload, dropbox_path)
        if not ok:
            return False, f"upload_failed_{err}"

        manifest[key] = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "attachment_id": attachment.id,
            "filename": attachment.filename,
            "size": attachment.size,
            "sha256": sha,
            "dropbox_path": dropbox_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.manifest_store.write(manifest)

        stats = await self.stats_store.read()
        stats.setdefault("uploaded_files", 0)
        stats.setdefault("uploaded_bytes", 0)
        stats.setdefault("skipped_too_large", 0)
        stats.setdefault("skipped_duplicate", 0)
        stats.setdefault("last_error", "")
        stats["uploaded_files"] += 1
        stats["uploaded_bytes"] += attachment.size
        await self.stats_store.write(stats)
        return True, "uploaded"

    async def note_skip(self, reason: str):
        stats = await self.stats_store.read()
        stats.setdefault("uploaded_files", 0)
        stats.setdefault("uploaded_bytes", 0)
        stats.setdefault("skipped_too_large", 0)
        stats.setdefault("skipped_duplicate", 0)
        stats.setdefault("last_error", "")
        if reason == "skip_too_large":
            stats["skipped_too_large"] += 1
        if reason == "skip_duplicate":
            stats["skipped_duplicate"] += 1
        await self.stats_store.write(stats)

    async def manual_backup_by_date(self, channel, date_value: datetime) -> dict:
        result = {
            "uploaded": 0,
            "skip_duplicate": 0,
            "skip_too_large": 0,
            "skip_not_media": 0,
            "failed": 0,
        }
        start = datetime(date_value.year, date_value.month, date_value.day, tzinfo=timezone.utc)
        end = datetime(date_value.year, date_value.month, date_value.day, 23, 59, 59, tzinfo=timezone.utc)
        async for message in channel.history(limit=None, after=start, before=end):
            if not message.attachments:
                continue
            for attachment in message.attachments:
                ok, status = await self.backup_attachment(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    channel_name=message.channel.name,
                    message_id=message.id,
                    attachment=attachment,
                )
                if ok:
                    result["uploaded"] += 1
                else:
                    if status in result:
                        result[status] += 1
                        await self.note_skip(status)
                    else:
                        result["failed"] += 1
                        stats = await self.stats_store.read()
                        stats["last_error"] = status
                        await self.stats_store.write(stats)
        return result

    async def backup_all_channel(self, channel, rate_delay: float = 0.5) -> dict:
        result = {
            "uploaded_images": 0,
            "uploaded_videos": 0,
            "skip_duplicate": 0,
            "skip_too_large": 0,
            "skip_not_media": 0,
            "failed": 0,
        }
        async for message in channel.history(limit=None, oldest_first=True):
            if not message.attachments:
                continue
            for attachment in message.attachments:
                ok, status = await self.backup_attachment(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    channel_name=message.channel.name,
                    message_id=message.id,
                    attachment=attachment,
                )
                if ok:
                    mt = self._media_type(attachment)
                    if mt == "image":
                        result["uploaded_images"] += 1
                    else:
                        result["uploaded_videos"] += 1
                else:
                    if status in result:
                        result[status] += 1
                    else:
                        result["failed"] += 1
                    await self.note_skip(status)
                await asyncio.sleep(rate_delay)
        return result
