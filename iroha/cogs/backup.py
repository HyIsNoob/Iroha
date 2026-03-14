from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands


class BackupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="backupwatch_add", description="Thêm channel vào danh sách auto backup")
    @app_commands.default_permissions(manage_guild=True)
    async def backupwatch_add(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return

        def patcher(guild: dict):
            watch_channels = guild.setdefault("backup_watch_channels", [])
            if channel.id not in watch_channels:
                watch_channels.append(channel.id)

        await self.bot.patch_guild_settings(interaction.guild.id, patcher)
        await interaction.response.send_message(f"Thêm {channel.mention} vào danh sách backup rồi!")

    @app_commands.command(name="backupwatch_remove", description="Gỡ channel khỏi danh sách auto backup")
    @app_commands.default_permissions(manage_guild=True)
    async def backupwatch_remove(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return

        def patcher(guild: dict):
            watch_channels = guild.setdefault("backup_watch_channels", [])
            guild["backup_watch_channels"] = [item for item in watch_channels if item != channel.id]

        await self.bot.patch_guild_settings(interaction.guild.id, patcher)
        await interaction.response.send_message(f"Gỡ {channel.mention} khỏi danh sách backup rồi nhé.")

    @app_commands.command(name="backupwatch_list", description="Xem các channel đang được theo dõi backup")
    @app_commands.default_permissions(manage_guild=True)
    async def backupwatch_list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        settings = await self.bot.get_guild_settings(interaction.guild.id)
        channel_ids = settings.get("backup_watch_channels", [])
        if not channel_ids:
            await interaction.response.send_message("Chưa có channel nào được theo dõi backup nha.", ephemeral=True)
            return
        lines = []
        for channel_id in channel_ids:
            channel = interaction.guild.get_channel(channel_id)
            lines.append(channel.mention if channel else f"Channel {channel_id}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="backup_manual", description="Backup thủ công media theo ngày cho 1 channel")
    @app_commands.default_permissions(manage_guild=True)
    async def backup_manual(self, interaction: discord.Interaction, channel: discord.TextChannel, date: str):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            await interaction.response.send_message("Định dạng ngày phải là YYYY-MM-DD.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        result = await self.bot.backup_service.manual_backup_by_date(channel, parsed)
        summary = (
            f"Backup ngày {date} xong rồi!\n"
            f"Đã upload: {result['uploaded']} file\n"
            f"Bỏ qua trùng lặp: {result['skip_duplicate']}\n"
            f"Bỏ qua quá lớn: {result['skip_too_large']}\n"
            f"Không phải media: {result['skip_not_media']}\n"
            f"Lỗi: {result['failed']}"
        )
        await interaction.followup.send(summary, ephemeral=True)

    @app_commands.command(name="backup_status", description="Xem trạng thái backup Dropbox")
    @app_commands.default_permissions(manage_guild=True)
    async def backup_status(self, interaction: discord.Interaction):
        stats = await self.bot.backup_stats_store.read()
        embed = discord.Embed(title="Iroha Backup Status", color=discord.Color.blue())
        embed.add_field(name="Dropbox", value="Đã cấu hình" if self.bot.backup_service.enabled else "Chưa cấu hình", inline=False)
        embed.add_field(name="Uploaded files", value=str(stats.get("uploaded_files", 0)), inline=True)
        embed.add_field(name="Uploaded MB", value=f"{stats.get('uploaded_bytes', 0) / 1024 / 1024:.2f}", inline=True)
        embed.add_field(name="Skipped > limit", value=str(stats.get("skipped_too_large", 0)), inline=True)
        embed.add_field(name="Skipped duplicate", value=str(stats.get("skipped_duplicate", 0)), inline=True)
        embed.add_field(name="Last error", value=stats.get("last_error", "Không có") or "Không có", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="backup_all", description="Backup tất cả ảnh/video hiện có trong channel")
    @app_commands.default_permissions(manage_guild=True)
    async def backup_all(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        from iroha.config import BACKUP_ALLOWED_GUILD_IDS
        if interaction.guild.id not in BACKUP_ALLOWED_GUILD_IDS:
            await interaction.response.send_message("Tính năng backup chỉ hoạt động ở các server được cho phép thôi nha.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            f"Bắt đầu backup toàn bộ media trong {channel.mention} rồi, mình sẽ báo khi xong nha!",
            ephemeral=True,
        )
        result = await self.bot.backup_service.backup_all_channel(channel)
        summary = (
            f"Backup {channel.mention} xong rồi!\n"
            f"Đã upload: {result['uploaded_images']} ảnh, {result['uploaded_videos']} video\n"
            f"Bỏ qua trùng lặp: {result['skip_duplicate']}\n"
            f"Bỏ qua quá lớn: {result['skip_too_large']}\n"
            f"Không phải media: {result['skip_not_media']}\n"
            f"Lỗi: {result['failed']}"
        )
        await self.bot.guild_log(interaction.guild.id, summary)
        await interaction.followup.send(summary, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.attachments:
            return
        settings = await self.bot.get_guild_settings(message.guild.id)
        if message.channel.id not in settings.get("backup_watch_channels", []):
            return

        for attachment in message.attachments:
            ok, status = await self.bot.backup_service.backup_attachment(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                channel_name=message.channel.name,
                message_id=message.id,
                attachment=attachment,
            )
            if not ok:
                await self.bot.backup_service.note_skip(status)
            else:
                await self.bot.guild_log(message.guild.id, f"Mình vừa backup 1 file từ {message.channel.mention}!")


async def setup(bot):
    await bot.add_cog(BackupCog(bot))
