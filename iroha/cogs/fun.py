import random

import discord
from discord import app_commands
from discord.ext import commands

_IROHA_COLOR = discord.Color(0xC9A0DC)

_8BALL_RESPONSES = [
    ("Đúng vậy đó.", True),
    ("Chắc chắn rồi.", True),
    ("Không thể nghi ngờ gì hết.", True),
    ("Mình nghĩ là được.", True),
    ("Dấu hiệu chỉ ra là có.", True),
    ("Nhìn theo hướng tích cực hơn đi.", None),
    ("Hỏi lại sau xem.", None),
    ("Mình không chắc lắm đâu.", None),
    ("Đừng đặt cược vào điều đó.", False),
    ("Câu trả lời là không.", False),
    ("Rất đáng ngờ.", False),
    ("Không có khả năng đó.", False),
]

_RATE_COMMENTS = [
    (0, 2, "Thảm."),
    (2, 4, "Không ấn tượng gì hết."),
    (4, 6, "Tạm. Không hơn không kém."),
    (6, 8, "Được đấy... theo nghĩa nào đó."),
    (8, 10, "Ổn thật sự. Mình không thừa nhận thêm đâu."),
    (10, 11, "Hoàn hảo. Mình hiếm khi nói vậy."),
]


def _ship_comment(score: int) -> str:
    if score < 20:
        return "Không hợp nhau lắm."
    if score < 40:
        return "Có chút tia sáng... nhưng chưa chắc."
    if score < 60:
        return "Tạm được. Có thể thành công nếu cố."
    if score < 80:
        return "Khá ổn. Mình không nhận xét gì thêm."
    if score < 100:
        return "Cặp này hợp thật rồi."
    return "Hoàn toàn tương hợp. Hiếm gặp lắm."


class FunCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ship", description="Kiểm tra độ tương hợp giữa hai người")
    async def ship(
        self,
        interaction: discord.Interaction,
        nguoi1: discord.Member,
        nguoi2: discord.Member,
    ):
        seed = min(nguoi1.id, nguoi2.id) * 31 + max(nguoi1.id, nguoi2.id)
        rng = random.Random(seed)
        score = rng.randint(0, 100)
        comment = _ship_comment(score)
        filled = round(score / 10)
        bar = "█" * filled + "░" * (10 - filled)

        embed = discord.Embed(color=_IROHA_COLOR)
        embed.set_author(name="Ship Meter")
        embed.description = f"**{nguoi1.display_name}** + **{nguoi2.display_name}**"
        embed.add_field(name="Độ tương hợp", value=f"`{bar}` **{score}%**", inline=False)
        embed.add_field(name="Nhận xét", value=comment, inline=False)
        embed.set_footer(text="Iroha")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="8ball", description="Hỏi Iroha một câu hỏi Yes/No")
    async def ball8(self, interaction: discord.Interaction, cauhoi: str):
        text, positive = random.choice(_8BALL_RESPONSES)
        if positive is True:
            color = discord.Color(0x27AE60)
            indicator = "+"
        elif positive is False:
            color = discord.Color(0xE74C3C)
            indicator = "-"
        else:
            color = discord.Color(0x95A5A6)
            indicator = "?"

        embed = discord.Embed(color=color)
        embed.set_author(name="8ball")
        embed.add_field(name="Câu hỏi", value=cauhoi, inline=False)
        embed.add_field(name="Câu trả lời", value=f"[{indicator}] {text}", inline=False)
        embed.set_footer(text="Iroha")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rate", description="Iroha đánh giá một thứ gì đó")
    async def rate(self, interaction: discord.Interaction, thu: str):
        rng = random.Random(thu.strip().lower())
        score = rng.randint(0, 10)
        comment = next(c for lo, hi, c in _RATE_COMMENTS if lo <= score < hi)
        filled = score
        bar = "█" * filled + "░" * (10 - filled)

        embed = discord.Embed(color=_IROHA_COLOR)
        embed.set_author(name="Rate")
        embed.add_field(name="Đối tượng", value=thu, inline=False)
        embed.add_field(name="Điểm", value=f"`{bar}` **{score}/10**", inline=False)
        embed.add_field(name="Nhận xét", value=comment, inline=False)
        embed.set_footer(text="Iroha")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(FunCog(bot))
