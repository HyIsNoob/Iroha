import random
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

_IROHA_COLOR = discord.Color(0xC9A0DC)
_QUOTES_PAGE_SIZE = 8


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
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        content = (message.content or "").strip()
        if not content:
            await interaction.response.send_message("Tin nhắn này không có text để lưu quote.", ephemeral=True)
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
            await interaction.response.send_message("Quote này đã được lưu rồi.", ephemeral=True)
            return

        await self.bot.quote_store.update(updater)
        await interaction.response.send_message("Lưu quote xong.", ephemeral=True)

    @app_commands.command(name="anime", description="Xem thông tin anime từ Jikan")
    async def anime(self, interaction: discord.Interaction, ten: app_commands.Range[str, 2, 100]):
        await interaction.response.defer()
        params = {"q": ten, "limit": 1, "sfw": "true"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.jikan.moe/v4/anime", params=params) as response:
                    if response.status != 200:
                        await interaction.followup.send("Jikan không phản hồi. Thử lại sau.", ephemeral=True)
                        return
                    payload = await response.json()
        except aiohttp.ClientError:
            await interaction.followup.send("Không kết nối được Jikan. Thử lại sau.", ephemeral=True)
            return

        items = payload.get("data") or []
        if not items:
            await interaction.followup.send(f"Không tìm thấy anime nào khớp với `{ten}`.", ephemeral=True)
            return

        anime = items[0]
        title = anime.get("title") or ten
        title_jp = anime.get("title_japanese") or ""
        synopsis = (anime.get("synopsis") or "Chưa có synopsis.").strip()
        if len(synopsis) > 900:
            synopsis = synopsis[:897].rstrip() + "..."

        desc = f"*{title_jp}*\n\n{synopsis}" if title_jp else synopsis
        embed = discord.Embed(title=title, url=anime.get("url"), description=desc, color=discord.Color(0x2E86AB))
        embed.add_field(name="Điểm", value=str(anime.get("score") or "N/A"), inline=True)
        embed.add_field(name="Tập", value=str(anime.get("episodes") or "?"), inline=True)
        embed.add_field(name="Trạng thái", value=anime.get("status") or "N/A", inline=True)
        embed.add_field(name="Loại", value=anime.get("type") or "N/A", inline=True)
        embed.add_field(name="Nguồn", value=anime.get("source") or "N/A", inline=True)
        embed.add_field(name="Rating", value=anime.get("rating") or "N/A", inline=True)
        image_url = ((anime.get("images") or {}).get("jpg") or {}).get("large_image_url")
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.set_footer(text="Jikan / MyAnimeList")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="quote_save", description="Lưu một câu quote từ message ID")
    async def quote_save(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Chỉ lưu quote từ text channel được.", ephemeral=True)
            return
        try:
            target_message = await target_channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Không tìm thấy message đó.", ephemeral=True)
            return
        await self._save_quote(interaction, target_message)

    async def quote_save_context(self, interaction: discord.Interaction, message: discord.Message):
        await self._save_quote(interaction, message)

    @app_commands.command(name="quote_random", description="Bốc ngẫu nhiên một quote trong server")
    async def quote_random(self, interaction: discord.Interaction, user: discord.Member | None = None):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        data = await self.bot.quote_store.read()
        quotes = list(data.get("guilds", {}).get(str(interaction.guild.id), {}).get("quotes", {}).values())
        if user is not None:
            quotes = [q for q in quotes if q.get("author_id") == user.id]
        if not quotes:
            await interaction.response.send_message("Chưa có quote nào phù hợp.", ephemeral=True)
            return

        quote = random.choice(quotes)
        content = quote.get("content", "")
        if len(content) > 1000:
            content = content[:997].rstrip() + "..."

        saved_dt = None
        try:
            saved_dt = datetime.fromisoformat(quote.get("saved_at", ""))
        except (ValueError, TypeError):
            pass

        embed = discord.Embed(description=f'"{content}"', color=_IROHA_COLOR)
        embed.set_author(name=quote.get("author_name", "Ẩn danh"))
        embed.add_field(name="Channel", value=f"<#{quote['channel_id']}>", inline=True)
        if saved_dt:
            embed.add_field(name="Lưu lúc", value=f"<t:{int(saved_dt.timestamp())}:d>", inline=True)
        jump_url = quote.get("jump_url")
        if jump_url:
            embed.add_field(name="Link", value=f"[Xem tin nhắn gốc]({jump_url})", inline=False)
        embed.set_footer(text="Iroha Quotes")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_list", description="Xem danh sách quote đã lưu trong server")
    async def quote_list(self, interaction: discord.Interaction, trang: app_commands.Range[int, 1, 100] = 1):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        data = await self.bot.quote_store.read()
        quotes = list(data.get("guilds", {}).get(str(interaction.guild.id), {}).get("quotes", {}).values())
        if not quotes:
            await interaction.response.send_message("Server chưa có quote nào.", ephemeral=True)
            return

        total = len(quotes)
        pages = (total + _QUOTES_PAGE_SIZE - 1) // _QUOTES_PAGE_SIZE
        page = min(trang, pages)
        start = (page - 1) * _QUOTES_PAGE_SIZE
        slice_ = quotes[start : start + _QUOTES_PAGE_SIZE]

        embed = discord.Embed(title=f"Quotes — Trang {page}/{pages}", color=_IROHA_COLOR)
        for i, q in enumerate(slice_, start=start + 1):
            preview = q.get("content", "")[:60].replace("\n", " ")
            if len(q.get("content", "")) > 60:
                preview += "..."
            embed.add_field(
                name=f"{i}. {q.get('author_name', '?')}",
                value=preview,
                inline=False,
            )
        embed.set_footer(text=f"Iroha Quotes · {total} quote tổng")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="quote_delete", description="Xóa một quote (cần là người lưu hoặc Manage Messages)")
    async def quote_delete(self, interaction: discord.Interaction, message_id: str):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        guild_id = str(interaction.guild.id)
        data = await self.bot.quote_store.read()
        quotes = data.get("guilds", {}).get(guild_id, {}).get("quotes", {})
        if message_id not in quotes:
            await interaction.response.send_message("Không tìm thấy quote đó.", ephemeral=True)
            return

        quote = quotes[message_id]
        can_delete = (
            quote.get("saved_by_id") == interaction.user.id
            or interaction.user.guild_permissions.manage_messages
        )
        if not can_delete:
            await interaction.response.send_message("Không có quyền xóa quote này.", ephemeral=True)
            return

        def updater(data: dict) -> dict:
            data.get("guilds", {}).get(guild_id, {}).get("quotes", {}).pop(message_id, None)
            return data

        await self.bot.quote_store.update(updater)
        await interaction.response.send_message("Đã xóa quote.", ephemeral=True)

    @app_commands.command(name="quote_top", description="Top người được quote nhiều nhất")
    async def quote_top(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        data = await self.bot.quote_store.read()
        all_quotes = data.get("guilds", {}).get(str(interaction.guild.id), {}).get("quotes", {}).values()
        if not all_quotes:
            await interaction.response.send_message("Server chưa có quote nào.", ephemeral=True)
            return

        counts: dict[int, tuple[str, int]] = {}
        for q in all_quotes:
            uid = q.get("author_id")
            name = q.get("author_name", "?")
            if uid:
                prev_name, prev_count = counts.get(uid, (name, 0))
                counts[uid] = (prev_name, prev_count + 1)

        ranked = sorted(counts.items(), key=lambda x: x[1][1], reverse=True)[:10]
        embed = discord.Embed(title="Top người được quote nhiều nhất", color=_IROHA_COLOR)
        medals = ["1.", "2.", "3."]
        for i, (uid, (name, count)) in enumerate(ranked):
            prefix = medals[i] if i < len(medals) else f"{i + 1}."
            embed.add_field(name=f"{prefix} {name}", value=f"{count} quote", inline=False)
        embed.set_footer(text="Iroha Quotes")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(MediaCog(bot))