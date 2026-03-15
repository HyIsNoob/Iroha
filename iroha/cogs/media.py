import random
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


class MediaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quote_context_menu = app_commands.ContextMenu(
            name="Luu quote",
            callback=self.quote_save_context,
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.quote_context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.quote_context_menu.name, type=self.quote_context_menu.type)

    async def _save_quote(self, interaction: discord.Interaction, message: discord.Message):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server thôi nha.", ephemeral=True)
            return
        content = (message.content or "").strip()
        if not content:
            await interaction.response.send_message("Tin nhắn này không có chữ để lưu quote đâu nha.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)

        def updater(data: dict) -> dict:
            guild_quotes = data.setdefault("guilds", {}).setdefault(guild_id, {})
            quotes = guild_quotes.setdefault("quotes", {})
            quotes.setdefault(
                str(message.id),
                {
                    "message_id": message.id,
                    "channel_id": message.channel.id,
                    "author_id": message.author.id,
                    "author_name": getattr(message.author, "display_name", message.author.name),
                    "content": content,
                    "jump_url": message.jump_url,
                    "created_at": message.created_at.isoformat() if message.created_at else datetime.now(timezone.utc).isoformat(),
                    "saved_by_id": interaction.user.id,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            return data

        before_data = await self.bot.quote_store.read()
        existing = before_data.get("guilds", {}).get(guild_id, {}).get("quotes", {})
        if str(message.id) in existing:
            await interaction.response.send_message("Quote này đã được lưu trước đó rồi nha.", ephemeral=True)
            return

        await self.bot.quote_store.update(updater)
        await interaction.response.send_message("Lưu quote xong rồi nha!", ephemeral=True)

    @app_commands.command(name="anime", description="Xem nhanh thông tin anime từ Jikan")
    async def anime(self, interaction: discord.Interaction, ten: app_commands.Range[str, 2, 100]):
        await interaction.response.defer()
        params = {"q": ten, "limit": 1, "sfw": "true"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.jikan.moe/v4/anime", params=params) as response:
                    if response.status != 200:
                        await interaction.followup.send("Jikan đang bận chút rồi, bạn thử lại sau nha.")
                        return
                    payload = await response.json()
        except aiohttp.ClientError:
            await interaction.followup.send("Mình chưa chạm tới Jikan được, thử lại sau giúp mình nha.")
            return

        items = payload.get("data") or []
        if not items:
            await interaction.followup.send(f"Mình chưa tìm thấy anime nào khớp với `{ten}` hết.")
            return

        anime = items[0]
        title = anime.get("title") or ten
        synopsis = (anime.get("synopsis") or "Chưa có synopsis.").strip()
        if len(synopsis) > 900:
            synopsis = synopsis[:897].rstrip() + "..."

        embed = discord.Embed(title=title, url=anime.get("url"), description=synopsis, color=discord.Color.teal())
        embed.add_field(name="Điểm", value=str(anime.get("score") or "Chưa có"), inline=True)
        embed.add_field(name="Episodes", value=str(anime.get("episodes") or "Chưa rõ"), inline=True)
        embed.add_field(name="Trạng thái", value=anime.get("status") or "Chưa rõ", inline=True)
        embed.add_field(name="Loại", value=anime.get("type") or "Chưa rõ", inline=True)
        embed.add_field(name="Nguồn", value=anime.get("source") or "Chưa rõ", inline=True)
        embed.add_field(name="Rating", value=anime.get("rating") or "Chưa rõ", inline=True)
        image_url = ((anime.get("images") or {}).get("jpg") or {}).get("large_image_url")
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.set_footer(text="Nguồn: Jikan / MyAnimeList")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="quote_save", description="Lưu một câu quote từ message ID")
    async def quote_save(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server thôi nha.", ephemeral=True)
            return
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Mình chỉ lưu quote từ text channel được thôi nha.", ephemeral=True)
            return
        try:
            target_message = await target_channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Mình không tìm thấy message đó đâu.", ephemeral=True)
            return
        await self._save_quote(interaction, target_message)

    async def quote_save_context(self, interaction: discord.Interaction, message: discord.Message):
        await self._save_quote(interaction, message)

    @app_commands.command(name="quote_random", description="Bốc ngẫu nhiên một quote trong server")
    async def quote_random(self, interaction: discord.Interaction, user: discord.Member | None = None):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server thôi nha.", ephemeral=True)
            return
        data = await self.bot.quote_store.read()
        quotes = list(data.get("guilds", {}).get(str(interaction.guild.id), {}).get("quotes", {}).values())
        if user is not None:
            quotes = [quote for quote in quotes if quote.get("author_id") == user.id]
        if not quotes:
            await interaction.response.send_message("Chưa có quote nào phù hợp để mình bốc hết.", ephemeral=True)
            return

        quote = random.choice(quotes)
        content = quote.get("content", "")
        if len(content) > 1000:
            content = content[:997].rstrip() + "..."

        embed = discord.Embed(title="Quote ngẫu nhiên", description=content, color=discord.Color.magenta())
        embed.add_field(name="Tác giả", value=f"<@{quote['author_id']}>", inline=True)
        embed.add_field(name="Channel", value=f"<#{quote['channel_id']}>", inline=True)
        embed.add_field(name="Lưu lúc", value=quote.get("saved_at", "Không rõ"), inline=False)
        jump_url = quote.get("jump_url")
        if jump_url:
            embed.add_field(name="Link", value=f"[Mở tin nhắn gốc]({jump_url})", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(MediaCog(bot))