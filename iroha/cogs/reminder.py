import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

_IROHA_COLOR = discord.Color(0xC9A0DC)
_MAX_DURATION_SECONDS = 60 * 60 * 24 * 7
_MIN_DURATION_SECONDS = 60
_MAX_REMINDERS_PER_USER = 10


def _parse_duration(s: str) -> int | None:
    total = 0
    found = False
    for m in re.finditer(r"(\d+)\s*(d|h|m|s)", s.lower()):
        found = True
        val, unit = int(m.group(1)), m.group(2)
        total += {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total if found else None


class ReminderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks: dict[str, asyncio.Task] = {}

    async def cog_load(self):
        data = await self.bot.reminder_store.read()
        for reminder in data.get("reminders", []):
            due = datetime.fromisoformat(reminder["due_at"])
            remaining = (due - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                self._schedule(reminder, remaining)

    async def cog_unload(self):
        for task in self._tasks.values():
            task.cancel()

    def _schedule(self, reminder: dict, delay: float):
        rid = reminder["id"]
        task = asyncio.create_task(self._fire(reminder, delay))
        self._tasks[rid] = task

    async def _fire(self, reminder: dict, delay: float):
        await asyncio.sleep(delay)
        channel = self.bot.get_channel(reminder["channel_id"])
        if channel is not None:
            try:
                await channel.send(f"<@{reminder['user_id']}> Nhắc nhở: **{reminder['content']}**")
            except Exception:
                pass
        await self._remove_reminder(reminder["id"])
        self._tasks.pop(reminder["id"], None)

    async def _remove_reminder(self, rid: str):
        def updater(data: dict) -> dict:
            data["reminders"] = [r for r in data.get("reminders", []) if r["id"] != rid]
            return data

        await self.bot.reminder_store.update(updater)

    @app_commands.command(name="remind", description="Đặt nhắc nhở. Ví dụ: /remind 30m Ăn cơm")
    async def remind(self, interaction: discord.Interaction, thoigian: str, noidung: str):
        seconds = _parse_duration(thoigian)
        if seconds is None or seconds < _MIN_DURATION_SECONDS:
            await interaction.response.send_message(
                "Thời gian không hợp lệ. Dùng định dạng như `30m`, `2h`, `1d`. Tối thiểu 1 phút.",
                ephemeral=True,
            )
            return
        if seconds > _MAX_DURATION_SECONDS:
            await interaction.response.send_message("Tối đa 7 ngày.", ephemeral=True)
            return

        data = await self.bot.reminder_store.read()
        user_reminders = [r for r in data.get("reminders", []) if r["user_id"] == interaction.user.id]
        if len(user_reminders) >= _MAX_REMINDERS_PER_USER:
            await interaction.response.send_message(
                f"Đang có {_MAX_REMINDERS_PER_USER} nhắc nhở rồi. Xóa bớt đi.",
                ephemeral=True,
            )
            return

        rid = str(uuid.uuid4())
        due = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        reminder = {
            "id": rid,
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "content": noidung,
            "due_at": due.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        def updater(data: dict) -> dict:
            data.setdefault("reminders", []).append(reminder)
            return data

        await self.bot.reminder_store.update(updater)
        self._schedule(reminder, seconds)

        due_ts = int(due.timestamp())
        embed = discord.Embed(
            description=f"Nhắc nhở lúc <t:{due_ts}:t> — <t:{due_ts}:R>",
            color=_IROHA_COLOR,
        )
        embed.add_field(name="Nội dung", value=noidung, inline=False)
        embed.set_footer(text="Iroha Reminder")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remind_list", description="Xem danh sách nhắc nhở đang chờ")
    async def remind_list(self, interaction: discord.Interaction):
        data = await self.bot.reminder_store.read()
        reminders = [r for r in data.get("reminders", []) if r["user_id"] == interaction.user.id]
        if not reminders:
            await interaction.response.send_message("Không có nhắc nhở nào đang chờ.", ephemeral=True)
            return

        embed = discord.Embed(title="Nhắc nhở đang chờ", color=_IROHA_COLOR)
        for i, r in enumerate(reminders[:10], 1):
            due = datetime.fromisoformat(r["due_at"])
            ts = int(due.timestamp())
            embed.add_field(
                name=f"{i}. {r['content'][:50]}",
                value=f"<t:{ts}:R>",
                inline=False,
            )
        embed.set_footer(text="Iroha Reminder")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ReminderCog(bot))
