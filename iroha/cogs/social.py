from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands


class PlayGameView(discord.ui.View):
    def __init__(self, owner_id: int, game_name: str, max_players: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.game_name = game_name
        self.max_players = max_players
        self.players = [owner_id]

    def render_embed(self, guild: discord.Guild) -> discord.Embed:
        player_names = []
        for user_id in self.players:
            member = guild.get_member(user_id)
            player_names.append(member.mention if member else f"<@{user_id}>")
        embed = discord.Embed(title=f"Room {self.game_name}", color=discord.Color.blurple())
        embed.description = f"Số lượng: **{len(self.players)}/{self.max_players}**"
        embed.add_field(name="Thành viên", value="\n".join(player_names), inline=False)
        return embed

    @discord.ui.button(label="Tham gia", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id in self.players:
            await interaction.response.send_message("Bạn đã có trong room rồi nha!", ephemeral=True)
            return
        if len(self.players) >= self.max_players:
            await interaction.response.send_message("Room đầy rồi, tiếc quá!", ephemeral=True)
            return
        self.players.append(interaction.user.id)
        await interaction.response.edit_message(embed=self.render_embed(interaction.guild), view=self)


class HangoutView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.joined = {owner_id}
        self.declined = set()

    def render_embed(self, base_embed: discord.Embed, guild: discord.Guild) -> discord.Embed:
        joined_mentions = [guild.get_member(uid).mention if guild.get_member(uid) else f"<@{uid}>" for uid in self.joined]
        declined_mentions = [guild.get_member(uid).mention if guild.get_member(uid) else f"<@{uid}>" for uid in self.declined]
        embed = discord.Embed.from_dict(base_embed.to_dict())
        embed.set_field_at(3, name="Tham gia", value="\n".join(joined_mentions) if joined_mentions else "Chưa có", inline=False)
        embed.set_field_at(4, name="Không thể tham gia", value="\n".join(declined_mentions) if declined_mentions else "Chưa có", inline=False)
        return embed

    @discord.ui.button(label="Tham gia", style=discord.ButtonStyle.green)
    async def attend(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.declined.discard(interaction.user.id)
        self.joined.add(interaction.user.id)
        new_embed = self.render_embed(interaction.message.embeds[0], interaction.guild)
        await interaction.response.edit_message(embed=new_embed, view=self)

    @discord.ui.button(label="Không thể tham gia", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.joined.discard(interaction.user.id)
        self.declined.add(interaction.user.id)
        new_embed = self.render_embed(interaction.message.embeds[0], interaction.guild)
        await interaction.response.edit_message(embed=new_embed, view=self)


class SocialCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="playgame", description="Tạo room rủ mọi người chơi game")
    async def playgame(
        self,
        interaction: discord.Interaction,
        game: str,
        max_players: app_commands.Range[int, 2, 20] = 3,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        view = PlayGameView(owner_id=interaction.user.id, game_name=game, max_players=max_players)
        embed = view.render_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        rooms = await self.bot.playgame_store.read()
        rooms.setdefault("rooms", {})[str(message.id)] = {
            "guild_id": interaction.guild.id,
            "channel_id": interaction.channel_id,
            "owner_id": interaction.user.id,
            "game": game,
            "max_players": max_players,
            "created_at": datetime.utcnow().isoformat(),
        }
        await self.bot.playgame_store.write(rooms)
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} tạo room playgame `{game}`")

    @app_commands.command(name="hangout", description="Tạo event offline")
    async def hangout(self, interaction: discord.Interaction, dip: str, dia_diem: str, thoi_gian: str):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        embed = discord.Embed(title="Sự kiện hangout", color=discord.Color.orange())
        embed.add_field(name="Dịp", value=dip, inline=False)
        embed.add_field(name="Địa điểm", value=dia_diem, inline=False)
        embed.add_field(name="Thời gian", value=thoi_gian, inline=False)
        embed.add_field(name="Tham gia", value=interaction.user.mention, inline=False)
        embed.add_field(name="Không thể tham gia", value="Chưa có", inline=False)
        view = HangoutView(owner_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        events = await self.bot.hangout_store.read()
        events.setdefault("events", {})[str(message.id)] = {
            "guild_id": interaction.guild.id,
            "channel_id": interaction.channel_id,
            "owner_id": interaction.user.id,
            "dip": dip,
            "dia_diem": dia_diem,
            "thoi_gian": thoi_gian,
            "created_at": datetime.utcnow().isoformat(),
        }
        await self.bot.hangout_store.write(events)
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} tạo event hangout `{dip}`")


async def setup(bot):
    await bot.add_cog(SocialCog(bot))
