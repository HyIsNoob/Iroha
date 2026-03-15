import random

import discord
from discord import app_commands
from discord.ext import commands

_MENTION_RESPONSES = [
    "Iroha nghe rồi. Cần gì không?",
    "Hmm? Có chuyện gì vậy?",
    "Mình đang ở đây. Cần gì thì nói.",
    "Bạn gọi mình? Nói đi mình nghe.",
    "Gọi mình mà không nói gì... thôi mình ở đây chờ.",
    "Bạn vừa tag mình... chắc nhớ mình quá.",
    "Mình thấy tên mình rồi. Bạn cần gì không?",
    "Ừ, mình đây. Nói đi.",
    "Hôm nay có việc gì à?",
    "Hmm.",
    "Dùng /help nếu cần xem danh sách lệnh.",
]


class CoreCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.bot.user is None:
            return
        if self.bot.user.mentioned_in(message) and not message.mention_everyone:
            content = message.content.strip()
            mention_str = f"<@{self.bot.user.id}>"
            mention_str_nick = f"<@!{self.bot.user.id}>"
            body = content.replace(mention_str, "").replace(mention_str_nick, "").strip()
            if not body:
                await message.reply(random.choice(_MENTION_RESPONSES))

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"Từ từ nha, chờ {error.retry_after:.1f}s nữa rồi thử lại!", ephemeral=True
            )
        else:
            raise error

    @app_commands.command(name="yesno", description="Trả lời ngẫu nhiên Yes hoặc No")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def yesno(self, interaction: discord.Interaction, question: str):
        answer = random.choice(["Yes", "No"])
        color = discord.Color(0x27AE60) if answer == "Yes" else discord.Color(0xE74C3C)
        embed = discord.Embed(color=color)
        embed.set_author(name="Yes / No")
        embed.add_field(name="Câu hỏi", value=question, inline=False)
        embed.add_field(name="Kết quả", value=f"**{answer}**", inline=False)
        embed.set_footer(text="Iroha")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="random", description="Random 1 lựa chọn từ danh sách")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def random_choice(self, interaction: discord.Interaction, options: str):
        values = [item.strip() for item in options.split(",") if item.strip()]
        if len(values) < 2:
            await interaction.response.send_message("Cần ít nhất 2 lựa chọn, ngăn cách bằng dấu phẩy.", ephemeral=True)
            return
        picked = random.choice(values)
        embed = discord.Embed(color=discord.Color(0xC9A0DC))
        embed.set_author(name="Random")
        embed.add_field(name="Kết quả", value=f"**{picked}**", inline=False)
        embed.set_footer(text="Iroha")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="team", description="Chia người vào số team")
    async def team(self, interaction: discord.Interaction, members: str, teams: app_commands.Range[int, 2, 20]):
        people = [item.strip() for item in members.split(",") if item.strip()]
        if len(people) < teams:
            await interaction.response.send_message("Số người phải nhiều hơn hoặc bằng số team nha!", ephemeral=True)
            return

        random.shuffle(people)
        buckets = [[] for _ in range(teams)]
        for index, person in enumerate(people):
            buckets[index % teams].append(person)

        embed = discord.Embed(title="Kết quả chia team", color=discord.Color.green())
        for i, bucket in enumerate(buckets, start=1):
            embed.add_field(name=f"Team {i}", value="\n".join(bucket) if bucket else "Trống", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="iroha", description="Đặt channel hiện tại làm channel log của Iroha")
    @app_commands.default_permissions(manage_guild=True)
    async def iroha(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server.", ephemeral=True)
            return

        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"log_channel_id": interaction.channel.id}),
        )
        await interaction.response.send_message("Xong. Từ giờ mình sẽ log ở đây.")

    @app_commands.command(name="help", description="Hiển thị hướng dẫn lệnh")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Iroha — Danh sách lệnh", color=discord.Color(0xC9A0DC))
        embed.add_field(name="Core", value="`/yesno`, `/random`, `/team`, `/playgame`, `/hangout`, `/iroha`, `/help`", inline=False)
        embed.add_field(name="Voice", value="`/autojoin`, `/connect`, `/disconnect`, `/speak`, `/voiceinout`, `/voiceactivity`, `/voicestream`", inline=False)
        embed.add_field(name="Anime & Quotes", value="`/anime`, `/quote_save`, `/quote_list`, `/quote_delete`, `/quote_top`, `/quote_random`, `Lưu quote`", inline=False)
        embed.add_field(name="Fun", value="`/ship`, `/8ball`, `/rate`", inline=False)
        embed.add_field(name="Reminder", value="`/remind`, `/remind_list`", inline=False)
        embed.add_field(name="Backup", value="`/backupwatch_add`, `/backupwatch_remove`, `/backupwatch_list`, `/backup_manual`, `/backup_all`, `/backup_status`", inline=False)
        embed.add_field(name="Moderation", value="`/muted`, `/clearbot`", inline=False)
        embed.set_footer(text="Iroha")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CoreCog(bot))
