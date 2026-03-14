import random

import discord
from discord import app_commands
from discord.ext import commands


class CoreCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"Chờ {error.retry_after:.1f}s rồi dùng lại.", ephemeral=True
            )
        else:
            raise error

    @app_commands.command(name="yesno", description="Trả lời ngẫu nhiên Yes hoặc No")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def yesno(self, interaction: discord.Interaction, question: str):
        answer = random.choice(["Yes", "No"])
        embed = discord.Embed(title="Iroha Yes/No", color=discord.Color.blurple())
        embed.add_field(name="Câu hỏi", value=question, inline=False)
        embed.add_field(name="Kết quả", value=answer, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="random", description="Random 1 lựa chọn từ danh sách")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def random_choice(self, interaction: discord.Interaction, options: str):
        values = [item.strip() for item in options.split(",") if item.strip()]
        if len(values) < 2:
            await interaction.response.send_message("Cần ít nhất 2 lựa chọn, ngăn cách bằng dấu phẩy.", ephemeral=True)
            return
        picked = random.choice(values)
        await interaction.response.send_message(f"Iroha chọn: **{picked}**")

    @app_commands.command(name="team", description="Chia người vào số team")
    async def team(self, interaction: discord.Interaction, members: str, teams: app_commands.Range[int, 2, 20]):
        people = [item.strip() for item in members.split(",") if item.strip()]
        if len(people) < teams:
            await interaction.response.send_message("Số người phải >= số team.", ephemeral=True)
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
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return

        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"log_channel_id": interaction.channel.id}),
        )
        await interaction.response.send_message("Đã đặt channel này làm kênh log của Iroha.")

    @app_commands.command(name="help", description="Hiển thị hướng dẫn lệnh")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Iroha Help", color=discord.Color.gold())
        embed.add_field(name="Core", value="`/yesno`, `/random`, `/team`, `/playgame`, `/hangout`, `/iroha`, `/help`", inline=False)
        embed.add_field(name="Voice", value="`/autojoin`, `/connect`, `/disconnect`, `/speak`, `/voiceinout`", inline=False)
        embed.add_field(name="Backup", value="`/backupwatch_add`, `/backupwatch_remove`, `/backupwatch_list`, `/backup_manual`, `/backup_status`", inline=False)
        embed.add_field(name="Moderation", value="`/muted`, `/clearbot`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CoreCog(bot))
