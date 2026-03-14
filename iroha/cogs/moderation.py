import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands


class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="muted", description="Chặn 1 user nhắn trong channel được chọn")
    @app_commands.default_permissions(manage_messages=True)
    async def muted(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        channel: discord.TextChannel,
        enabled: bool,
        reply_text: str = "Bạn đã bị cấm vận",
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return

        def patcher(guild: dict):
            muted_rules = guild.setdefault("muted_rules", {})
            channel_rules = muted_rules.setdefault(str(channel.id), {})
            if enabled:
                channel_rules[str(user.id)] = reply_text
            else:
                channel_rules.pop(str(user.id), None)
                if not channel_rules:
                    muted_rules.pop(str(channel.id), None)

        await self.bot.patch_guild_settings(interaction.guild.id, patcher)
        action = "bật" if enabled else "tắt"
        await interaction.response.send_message(f"Mình đã {action} muted cho {user.mention} ở {channel.mention} rồi nhé.")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {action} muted cho {user.mention} ở {channel.mention}")

    @app_commands.command(name="clearbot", description="Xóa 50 tin nhắn gần nhất của Iroha trong channel hiện tại")
    @app_commands.default_permissions(manage_messages=True)
    async def clearbot(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Lệnh này chỉ dùng được trong text channel của server thôi nha.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        removed = []
        async for message in interaction.channel.history(limit=200):
            if message.author.id == self.bot.user.id:
                removed.append(message)
            if len(removed) == 50:
                break

        if not removed:
            await interaction.followup.send("Mình tìm không thấy tin nhắn nào của mình ở đây cả.", ephemeral=True)
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        recent = [m for m in removed if m.created_at > cutoff]
        old = [m for m in removed if m.created_at <= cutoff]

        deleted = 0
        if recent:
            try:
                await interaction.channel.delete_messages(recent)
                deleted += len(recent)
            except discord.HTTPException:
                for m in recent:
                    try:
                        await m.delete()
                        deleted += 1
                    except discord.Forbidden:
                        pass

        for m in old:
            try:
                await m.delete()
                deleted += 1
                await asyncio.sleep(0.5)
            except discord.Forbidden:
                pass

        await interaction.followup.send(f"Mình dọn xong rồi, đã xóa {deleted} tin nhắn nha!", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        settings = await self.bot.get_guild_settings(message.guild.id)
        channel_rules = settings.get("muted_rules", {}).get(str(message.channel.id), {})
        reply_text = channel_rules.get(str(message.author.id))
        if not reply_text:
            return
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention} {reply_text}", delete_after=5)
        except discord.Forbidden:
            return


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
