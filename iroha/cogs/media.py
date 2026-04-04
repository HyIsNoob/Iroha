import asyncio
import random
import re
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from iroha import config

_IROHA_COLOR = discord.Color(0xC9A0DC)
_QUOTES_PAGE_SIZE = 8
_MESSAGE_LINK_RE = re.compile(r"https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")
_JIKAN_BASE = "https://api.jikan.moe/v4"
_WEEKDAY_CHOICES = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_GENRE_HINTS = {
    "trinh tham": ["Mystery", "Detective", "Suspense"],
    "trinhtham": ["Mystery", "Detective", "Suspense"],
    "du hanh thoi gian": ["Time Travel", "Sci-Fi"],
    "duhanhthoigian": ["Time Travel", "Sci-Fi"],
    "kinh di": ["Horror", "Supernatural"],
    "kinhdi": ["Horror", "Supernatural"],
    "hai": ["Comedy"],
    "hanh dong": ["Action"],
    "hanhdong": ["Action"],
    "tam ly": ["Psychological"],
    "tamly": ["Psychological"],
    "romance": ["Romance"],
    "school": ["School"],
    "fantasy": ["Fantasy"],
    "isekai": ["Isekai", "Fantasy"],
}


class MediaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._genre_name_to_id: dict[str, int] = {}
        self._genre_cache_expire_at: float = 0.0
        self.quote_context_menu = app_commands.ContextMenu(
            name="Luu quote",
            callback=self.quote_save_context,
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.quote_context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.quote_context_menu.name, type=self.quote_context_menu.type)

    async def _store_quote(self, guild_id: int, message: discord.Message, saved_by_id: int) -> tuple[bool, str]:
        content = (message.content or "").strip()
        if not content:
            return False, "Tin nhắn này không có text để lưu quote."

        guild_key = str(guild_id)

        def updater(data: dict) -> dict:
            guild_quotes = data.setdefault("guilds", {}).setdefault(guild_key, {})
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
                    "saved_by_id": saved_by_id,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            return data

        before_data = await self.bot.quote_store.read()
        existing = before_data.get("guilds", {}).get(guild_key, {}).get("quotes", {})
        if str(message.id) in existing:
            return False, "Quote này đã được lưu rồi."

        await self.bot.quote_store.update(updater)
        return True, "Lưu quote xong."

    async def _get_message_from_input(
        self,
        interaction: discord.Interaction,
        raw_value: str,
        channel: discord.TextChannel | None = None,
    ) -> discord.Message | None:
        if interaction.guild is None:
            return None

        raw_value = raw_value.strip()
        target_channel = channel
        message_id: int | None = None

        link_match = _MESSAGE_LINK_RE.fullmatch(raw_value)
        if link_match:
            _, channel_id, raw_message_id = link_match.groups()
            found_channel = interaction.guild.get_channel(int(channel_id))
            if isinstance(found_channel, discord.TextChannel):
                target_channel = found_channel
                message_id = int(raw_message_id)
        else:
            try:
                message_id = int(raw_value)
            except ValueError:
                return None

        if not isinstance(target_channel, discord.TextChannel) or message_id is None:
            return None

        try:
            return await target_channel.fetch_message(message_id)
        except discord.NotFound:
            return None

    async def _save_quote(self, interaction: discord.Interaction, message: discord.Message):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        ok, reply = await self._store_quote(interaction.guild.id, message, interaction.user.id)
        await interaction.response.send_message(reply, ephemeral=True)

    async def _ensure_anime_allowed(self, interaction: discord.Interaction) -> bool:
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("Lệnh anime chỉ dùng trong server được cho phép.", ephemeral=True)
            return False
        if guild_id not in config.BACKUP_ALLOWED_GUILD_IDS:
            await interaction.response.send_message(
                "Lệnh anime đang giới hạn để tránh rate limit. Server này chưa được bật.",
                ephemeral=True,
            )
            return False
        return True

    async def _jikan_get(self, path: str, params: dict | None = None) -> tuple[int, dict | None]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{_JIKAN_BASE}{path}", params=params) as response:
                    if response.status != 200:
                        return response.status, None
                    return response.status, await response.json()
        except aiohttp.ClientError:
            return 0, None

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    async def _search_anime_first(self, query: str) -> tuple[int, dict | None]:
        status, payload = await self._jikan_get(
            "/anime",
            {"q": query, "limit": 1, "sfw": "true"},
        )
        if status != 200 or not payload:
            return status, None
        items = payload.get("data") or []
        return status, (items[0] if items else None)

    @staticmethod
    def _normalize_lookup(value: str) -> str:
        compact = re.sub(r"[^a-z0-9\s]+", " ", (value or "").lower())
        return " ".join(compact.split())

    async def _load_genre_map(self) -> dict[str, int]:
        now = asyncio.get_running_loop().time()
        if self._genre_name_to_id and now < self._genre_cache_expire_at:
            return self._genre_name_to_id

        status, payload = await self._jikan_get("/genres/anime")
        if status != 200 or not payload:
            return self._genre_name_to_id

        mapping: dict[str, int] = {}
        for row in payload.get("data") or []:
            mal_id = row.get("mal_id")
            name = row.get("name")
            if not mal_id or not name:
                continue
            mapping[self._normalize_lookup(name)] = int(mal_id)

        if mapping:
            self._genre_name_to_id = mapping
            self._genre_cache_expire_at = now + 3600
        return self._genre_name_to_id

    async def _resolve_genre_ids(self, genre_text: str | None, reference_anime: dict | None) -> list[int]:
        genre_map = await self._load_genre_map()
        genre_ids: list[int] = []

        if reference_anime is not None:
            for row in reference_anime.get("genres") or []:
                mal_id = row.get("mal_id")
                if mal_id is None:
                    continue
                value = int(mal_id)
                if value not in genre_ids:
                    genre_ids.append(value)

        if not genre_text:
            return genre_ids

        requested_terms: list[str] = []
        for chunk in re.split(r",|;|/", genre_text):
            token = self._normalize_lookup(chunk)
            if not token:
                continue
            requested_terms.extend(_GENRE_HINTS.get(token, [token]))

        for term in requested_terms:
            normalized = self._normalize_lookup(term)
            matched_id = genre_map.get(normalized)
            if matched_id is None:
                for name_key, name_id in genre_map.items():
                    if normalized and (normalized in name_key or name_key in normalized):
                        matched_id = name_id
                        break
            if matched_id is None:
                continue
            if matched_id not in genre_ids:
                genre_ids.append(matched_id)

        return genre_ids

    @app_commands.command(name="anime_random", description="Random anime có thể lọc theo thể loại hoặc anime tham chiếu")
    async def anime_random(
        self,
        interaction: discord.Interaction,
        the_loai: app_commands.Range[str, 2, 80] | None = None,
        tham_chieu: app_commands.Range[str, 2, 100] | None = None,
    ):
        if not await self._ensure_anime_allowed(interaction):
            return
        await interaction.response.defer()

        reference_anime: dict | None = None
        if tham_chieu:
            status, reference_anime = await self._search_anime_first(tham_chieu)
            if status != 200:
                await interaction.followup.send("Không kết nối được Jikan. Thử lại sau.", ephemeral=True)
                return
            if reference_anime is None:
                await interaction.followup.send(f"Không tìm thấy anime tham chiếu `{tham_chieu}`.", ephemeral=True)
                return

        genre_ids = await self._resolve_genre_ids(the_loai, reference_anime)
        params = {"sfw": "true", "limit": 25}
        if genre_ids:
            params["genres"] = ",".join(str(value) for value in genre_ids[:4])

        status, payload = await self._jikan_get("/anime", params)
        items = (payload or {}).get("data") or [] if status == 200 else []
        chosen = random.choice(items) if items else None

        if chosen is None:
            status, payload = await self._jikan_get("/random/anime", {"sfw": "true"})
            if status != 200 or not payload:
                await interaction.followup.send("Không lấy được anime random lúc này.", ephemeral=True)
                return
            chosen = payload.get("data")

        if chosen is None:
            await interaction.followup.send("Không có dữ liệu anime phù hợp để random.", ephemeral=True)
            return

        title = chosen.get("title") or "Anime random"
        synopsis = self._truncate(chosen.get("synopsis") or "Chưa có synopsis.", 900)
        embed = discord.Embed(title=title, url=chosen.get("url"), description=synopsis, color=_IROHA_COLOR)
        embed.add_field(name="Điểm", value=str(chosen.get("score") or "N/A"), inline=True)
        embed.add_field(name="Tập", value=str(chosen.get("episodes") or "?"), inline=True)
        embed.add_field(name="Trạng thái", value=chosen.get("status") or "N/A", inline=True)

        genres = chosen.get("genres") or []
        if genres:
            links = []
            for row in genres[:6]:
                mal_id = row.get("mal_id")
                name = row.get("name") or "Unknown"
                if mal_id:
                    links.append(f"[{name}](https://myanimelist.net/anime/genre/{mal_id})")
                else:
                    links.append(name)
            embed.add_field(name="Thể loại", value=", ".join(links), inline=False)

        if the_loai:
            embed.add_field(name="Filter thể loại", value=the_loai, inline=True)
        if reference_anime is not None:
            ref_title = reference_anime.get("title") or tham_chieu or "Reference"
            ref_url = reference_anime.get("url")
            ref_text = f"[{ref_title}]({ref_url})" if ref_url else ref_title
            embed.add_field(name="Reference", value=ref_text, inline=True)

        image_url = ((chosen.get("images") or {}).get("jpg") or {}).get("large_image_url")
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.set_footer(text="Jikan Random / Filtered")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="anime", description="Xem thông tin anime từ Jikan")
    async def anime(self, interaction: discord.Interaction, ten: app_commands.Range[str, 2, 100]):
        if not await self._ensure_anime_allowed(interaction):
            return
        await interaction.response.defer()
        status, anime = await self._search_anime_first(ten)
        if status != 200:
            await interaction.followup.send("Không kết nối được Jikan. Thử lại sau.", ephemeral=True)
            return
        if anime is None:
            await interaction.followup.send(f"Không tìm thấy anime nào khớp với `{ten}`.", ephemeral=True)
            return
        title = anime.get("title") or ten
        title_jp = anime.get("title_japanese") or ""
        synopsis = self._truncate(anime.get("synopsis") or "Chưa có synopsis.", 900)

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

    @app_commands.command(name="anime_recommend", description="Gợi ý anime tương tự từ tên anime")
    async def anime_recommend(
        self,
        interaction: discord.Interaction,
        ten: app_commands.Range[str, 2, 100],
        top: app_commands.Range[int, 3, 10] = 5,
    ):
        if not await self._ensure_anime_allowed(interaction):
            return
        await interaction.response.defer()
        status, anime = await self._search_anime_first(ten)
        if status != 200:
            await interaction.followup.send("Không kết nối được Jikan. Thử lại sau.", ephemeral=True)
            return
        if anime is None:
            await interaction.followup.send(f"Không tìm thấy anime nào khớp với `{ten}`.", ephemeral=True)
            return

        mal_id = anime.get("mal_id")
        if not mal_id:
            await interaction.followup.send("Không lấy được mã anime để tìm recommendation.", ephemeral=True)
            return

        status, payload = await self._jikan_get(f"/anime/{mal_id}/recommendations")
        if status != 200 or not payload:
            await interaction.followup.send("Không lấy được dữ liệu recommendation lúc này.", ephemeral=True)
            return

        recs = payload.get("data") or []
        if not recs:
            await interaction.followup.send("Anime này chưa có recommendation đủ rõ trong Jikan.", ephemeral=True)
            return

        lines = []
        for idx, rec in enumerate(recs[:top], start=1):
            entry = rec.get("entry") or {}
            rec_title = entry.get("title") or "Không rõ"
            rec_url = entry.get("url")
            votes = rec.get("votes")
            name = f"[{rec_title}]({rec_url})" if rec_url else rec_title
            vote_text = f" · votes: {votes}" if votes is not None else ""
            lines.append(f"**{idx}.** {name}{vote_text}")

        embed = discord.Embed(
            title=f"Gợi ý từ {anime.get('title') or ten}",
            description="\n".join(lines),
            color=_IROHA_COLOR,
        )
        image_url = ((anime.get("images") or {}).get("jpg") or {}).get("image_url")
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.set_footer(text="Jikan Recommendations")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="anime_season", description="Top anime mùa hiện tại hoặc sắp tới")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="now", value="now"),
            app_commands.Choice(name="upcoming", value="upcoming"),
        ]
    )
    async def anime_season(
        self,
        interaction: discord.Interaction,
        mode: str = "now",
        top: app_commands.Range[int, 3, 10] = 5,
    ):
        if not await self._ensure_anime_allowed(interaction):
            return
        await interaction.response.defer()
        endpoint = "/seasons/upcoming" if mode == "upcoming" else "/seasons/now"
        status, payload = await self._jikan_get(endpoint, {"limit": 25, "sfw": "true"})
        if status != 200 or not payload:
            await interaction.followup.send("Không lấy được dữ liệu anime theo mùa lúc này.", ephemeral=True)
            return

        items = payload.get("data") or []
        if not items:
            await interaction.followup.send("Mùa này chưa có dữ liệu anime phù hợp.", ephemeral=True)
            return

        ranked = sorted(items, key=lambda x: x.get("score") or 0, reverse=True)[:top]
        lines = []
        for idx, anime in enumerate(ranked, start=1):
            title = anime.get("title") or "Không rõ"
            url = anime.get("url")
            anime_type = anime.get("type") or "?"
            score = anime.get("score") or "N/A"
            episodes = anime.get("episodes") or "?"
            name = f"[{title}]({url})" if url else title
            lines.append(f"**{idx}.** {name} · ⭐ {score} · {anime_type} · {episodes} eps")

        season_label = "Sắp chiếu" if mode == "upcoming" else "Đang chiếu"
        embed = discord.Embed(
            title=f"Anime mùa — {season_label}",
            description="\n".join(lines),
            color=_IROHA_COLOR,
        )
        embed.set_footer(text="Jikan Seasons")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="anime_schedule", description="Lịch anime theo thứ")
    @app_commands.choices(
        thu=[
            app_commands.Choice(name="today", value="today"),
            app_commands.Choice(name="monday", value="monday"),
            app_commands.Choice(name="tuesday", value="tuesday"),
            app_commands.Choice(name="wednesday", value="wednesday"),
            app_commands.Choice(name="thursday", value="thursday"),
            app_commands.Choice(name="friday", value="friday"),
            app_commands.Choice(name="saturday", value="saturday"),
            app_commands.Choice(name="sunday", value="sunday"),
        ]
    )
    async def anime_schedule(
        self,
        interaction: discord.Interaction,
        thu: str = "today",
        top: app_commands.Range[int, 3, 10] = 5,
    ):
        if not await self._ensure_anime_allowed(interaction):
            return
        await interaction.response.defer()
        day = datetime.now(timezone.utc).strftime("%A").lower() if thu == "today" else thu.lower().strip()
        if day not in _WEEKDAY_CHOICES:
            await interaction.followup.send("Giá trị thứ không hợp lệ.", ephemeral=True)
            return

        status, payload = await self._jikan_get("/schedules", {"filter": day, "limit": 25, "sfw": "true"})
        if status != 200 or not payload:
            await interaction.followup.send("Không lấy được lịch anime lúc này.", ephemeral=True)
            return

        items = payload.get("data") or []
        if not items:
            await interaction.followup.send("Không có anime nào trong lịch của ngày này.", ephemeral=True)
            return

        ranked = sorted(items, key=lambda x: x.get("score") or 0, reverse=True)[:top]
        lines = []
        for idx, anime in enumerate(ranked, start=1):
            title = anime.get("title") or "Không rõ"
            url = anime.get("url")
            score = anime.get("score") or "N/A"
            broadcast = ((anime.get("broadcast") or {}).get("string") or "Giờ chiếu chưa rõ")
            name = f"[{title}]({url})" if url else title
            lines.append(f"**{idx}.** {name} · ⭐ {score}\n{broadcast}")

        embed = discord.Embed(
            title=f"Lịch anime — {day.capitalize()}",
            description="\n\n".join(lines),
            color=_IROHA_COLOR,
        )
        embed.set_footer(text="Jikan Schedules")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="character", description="Tra cứu nhân vật và seiyuu")
    async def character(self, interaction: discord.Interaction, ten: app_commands.Range[str, 2, 100]):
        if not await self._ensure_anime_allowed(interaction):
            return
        await interaction.response.defer()
        status, payload = await self._jikan_get(
            "/characters",
            {"q": ten, "limit": 1},
        )
        if status != 200 or not payload:
            await interaction.followup.send("Không kết nối được dữ liệu character lúc này.", ephemeral=True)
            return

        found = payload.get("data") or []
        if not found:
            await interaction.followup.send(f"Không tìm thấy nhân vật khớp với `{ten}`.", ephemeral=True)
            return

        character = found[0]
        char_id = character.get("mal_id")
        if not char_id:
            await interaction.followup.send("Không lấy được ID nhân vật.", ephemeral=True)
            return

        _, full_payload = await self._jikan_get(f"/characters/{char_id}/full")
        _, voices_payload = await self._jikan_get(f"/characters/{char_id}/voices")

        full_data = (full_payload or {}).get("data") or character
        voices = (voices_payload or {}).get("data") or []

        title = full_data.get("name") or character.get("name") or ten
        about = self._truncate(full_data.get("about") or "Chưa có mô tả nhân vật.", 900)
        image_url = ((full_data.get("images") or {}).get("jpg") or {}).get("image_url")
        favorites = full_data.get("favorites")

        embed = discord.Embed(
            title=title,
            url=full_data.get("url") or character.get("url"),
            description=about,
            color=_IROHA_COLOR,
        )
        if image_url:
            embed.set_thumbnail(url=image_url)
        if favorites is not None:
            embed.add_field(name="Favorites", value=str(favorites), inline=True)

        seiyuu_line = "Chưa có dữ liệu seiyuu."
        jp_voice = next((v for v in voices if (v.get("language") or "").lower() == "japanese"), None)
        pick_voice = jp_voice or (voices[0] if voices else None)
        if pick_voice:
            person = pick_voice.get("person") or {}
            person_name = person.get("name") or "Không rõ"
            person_url = person.get("url")
            lang = pick_voice.get("language") or "Unknown"
            seiyuu_name = f"[{person_name}]({person_url})" if person_url else person_name
            seiyuu_line = f"{seiyuu_name} ({lang})"
        embed.add_field(name="Seiyuu", value=seiyuu_line, inline=False)

        anime_entries = (full_data.get("anime") or [])[:3]
        if anime_entries:
            appear_lines = []
            for row in anime_entries:
                entry = row.get("anime") or {}
                role = row.get("role") or "?"
                anime_title = entry.get("title") or "Không rõ"
                anime_url = entry.get("url")
                show = f"[{anime_title}]({anime_url})" if anime_url else anime_title
                appear_lines.append(f"- {show} ({role})")
            embed.add_field(name="Xuất hiện trong", value="\n".join(appear_lines), inline=False)

        embed.set_footer(text="Jikan Characters / People")
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
        target_message = await self._get_message_from_input(interaction, message_id, target_channel)
        if target_message is None:
            await interaction.response.send_message("Không tìm thấy message đó.", ephemeral=True)
            return
        await self._save_quote(interaction, target_message)

    @app_commands.command(name="quote", description="Lưu quote từ message link hoặc message ID")
    async def quote(
        self,
        interaction: discord.Interaction,
        tin_nhan: str,
        channel: discord.TextChannel | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Quote chỉ dùng trong server.", ephemeral=True)
            return
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Chỉ lưu quote từ text channel được.", ephemeral=True)
            return

        target_message = await self._get_message_from_input(interaction, tin_nhan, target_channel)
        if target_message is None:
            await interaction.response.send_message(
                "Không đọc được tin nhắn đó. Dùng message ID hoặc link tin nhắn đầy đủ.",
                ephemeral=True,
            )
            return
        await self._save_quote(interaction, target_message)

    async def quote_save_context(self, interaction: discord.Interaction, message: discord.Message):
        await self._save_quote(interaction, message)

    @commands.command(name="quote")
    async def quote_prefix(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.reply("Quote chỉ dùng trong server.")
            return

        reference = ctx.message.reference
        if reference is None:
            await ctx.reply("Reply vào tin nhắn cần lưu rồi dùng `!quote`.")
            return

        target_message = reference.resolved if isinstance(reference.resolved, discord.Message) else None
        if target_message is None and reference.message_id is not None:
            channel = ctx.channel
            if isinstance(channel, discord.TextChannel):
                try:
                    target_message = await channel.fetch_message(reference.message_id)
                except discord.NotFound:
                    target_message = None

        if target_message is None:
            await ctx.reply("Mình không đọc được tin nhắn được reply.")
            return

        ok, reply = await self._store_quote(ctx.guild.id, target_message, ctx.author.id)
        await ctx.reply(reply)

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