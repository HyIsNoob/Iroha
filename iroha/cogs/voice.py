import asyncio
import random
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from discord.errors import ConnectionClosed
from gtts import gTTS

VOICE_JOIN_LINES = [
    "thằng {name} đã vào",
    "Chào mừng thằng {name}",
    "là thằng {name}",
]

VOICE_LEAVE_LINES = [
    "thằng {name} cút",
    "{name} đi rồi",
    "{name} đã out",
]

VOICE_STREAM_LINES = [
    "{name} vừa mở stream",
    "thằng {name} lại stream rồi",
    "sờ chim {name}",
]

VOICE_ACTIVITY_LINES = [
    "{name} mở {activity} kìa",
    "Phát hiện {name} dùng {activity}.",
]


class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._autojoin_locks: dict[int, asyncio.Lock] = {}
        self._autojoin_fail_count: dict[int, int] = {}
        self._autojoin_next_retry: dict[int, float] = {}
        self._tts_locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def _is_voice_4006(exc: Exception) -> bool:
        return isinstance(exc, ConnectionClosed) and getattr(exc, "code", None) == 4006

    async def _get_author_voice_channel(self, interaction: discord.Interaction):
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            return None
        return interaction.user.voice.channel

    def _get_tts_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._tts_locks:
            self._tts_locks[guild_id] = asyncio.Lock()
        return self._tts_locks[guild_id]

    def _get_shared_voice_client(self, member: discord.Member):
        voice_state = member.voice
        voice_client = member.guild.voice_client
        if voice_state is None or voice_state.channel is None:
            return None
        if voice_client is None or not voice_client.is_connected():
            return None
        if getattr(voice_client.channel, "id", None) != voice_state.channel.id:
            return None
        return voice_client

    def _get_voice_client_for_channel(self, guild: discord.Guild, channel_id: int | None):
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_connected() or channel_id is None:
            return None
        if getattr(voice_client.channel, "id", None) != channel_id:
            return None
        return voice_client

    @staticmethod
    def _activity_names(member: discord.Member) -> set[str]:
        names = set()
        for activity in member.activities:
            activity_name = getattr(activity, "name", None)
            activity_type = getattr(activity, "type", None)
            if not activity_name:
                continue
            if activity_type in (discord.ActivityType.custom, discord.ActivityType.streaming):
                continue
            names.add(activity_name)
        return names

    async def _play_tts(self, voice_client, text: str) -> bool:
        guild_id = voice_client.guild.id
        lock = self._get_tts_lock(guild_id)
        async with lock:
            if not voice_client.is_connected() or voice_client.is_playing():
                return False

            temp_path = None
            done = asyncio.Event()
            loop = asyncio.get_running_loop()
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
                    temp_path = Path(temp_file.name)
                tts = gTTS(text=text, lang="vi")
                await asyncio.to_thread(tts.save, str(temp_path))
                source = discord.FFmpegPCMAudio(str(temp_path))

                def after_playback(_error):
                    loop.call_soon_threadsafe(done.set)

                voice_client.play(source, after=after_playback)
                await asyncio.wait_for(done.wait(), timeout=30)
                return True
            finally:
                if temp_path and temp_path.exists():
                    temp_path.unlink(missing_ok=True)

    def _render_line(self, lines: list[str], **values: str) -> str:
        return random.choice(lines).format(**values)

    @app_commands.command(name="connect", description="Cho Iroha vào voice channel của bạn")
    async def connect(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        voice_channel = await self._get_author_voice_channel(interaction)
        if voice_channel is None:
            await interaction.response.send_message("Bạn vào voice trước thì mình mới vào được nha!", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        try:
            if voice_client and voice_client.is_connected():
                await voice_client.move_to(voice_channel)
            else:
                await voice_channel.connect(timeout=12, reconnect=False, self_deaf=True)
        except TimeoutError:
            await interaction.response.send_message(
                "Kết nối voice bị timeout, thử lại sau một chút nha!", ephemeral=True
            )
            return
        except Exception as exc:
            if self._is_voice_4006(exc):
                await interaction.response.send_message(
                    "Voice đang lỗi kết nối (4006). Bạn kiểm tra giúp mình: chỉ chạy 1 instance bot duy nhất và thử lại sau ít phút nha.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"Mình vào voice không được: {exc}", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Mình đã vào {voice_channel.mention} rồi!")

    @app_commands.command(name="disconnect", description="Cho Iroha rời voice channel")
    async def disconnect(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("Mình chưa ở trong voice channel nào cả.", ephemeral=True)
            return
        await voice_client.disconnect(force=True)
        await interaction.response.send_message("Mình rời voice rồi, gọi mình lại nha!")

    @app_commands.command(name="autojoin", description="Bật hoặc tắt tự động join voice")
    @app_commands.default_permissions(manage_guild=True)
    async def autojoin(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"autojoin_enabled": enabled}),
        )
        await interaction.response.send_message(f"Autojoin {'bật' if enabled else 'tắt'} rồi nha!")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {'bật' if enabled else 'tắt'} autojoin")

    @app_commands.command(name="voiceinout", description="Bật hoặc tắt thông báo join/leave voice")
    @app_commands.default_permissions(manage_guild=True)
    async def voiceinout(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"voiceinout_enabled": enabled}),
        )
        await interaction.response.send_message(f"Thông báo voice in/out {'bật' if enabled else 'tắt'} rồi nha!")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {'bật' if enabled else 'tắt'} voiceinout")

    @app_commands.command(name="voiceactivity", description="Bật hoặc tắt đọc khi ai đó mở activity trong voice")
    @app_commands.default_permissions(manage_guild=True)
    async def voiceactivity(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"voiceactivity_enabled": enabled}),
        )
        await interaction.response.send_message(f"Đọc activity trong voice {'bật' if enabled else 'tắt'} rồi nha!")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {'bật' if enabled else 'tắt'} voiceactivity")

    @app_commands.command(name="voicestream", description="Bật hoặc tắt đọc khi ai đó bật stream trong voice")
    @app_commands.default_permissions(manage_guild=True)
    async def voicestream(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"voicestream_enabled": enabled}),
        )
        await interaction.response.send_message(f"Đọc stream trong voice {'bật' if enabled else 'tắt'} rồi nha!")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {'bật' if enabled else 'tắt'} voicestream")

    @app_commands.command(name="speak", description="Iroha nói trong voice channel")
    async def speak(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 200]):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng được trong server thôi nha.", ephemeral=True)
            return
        voice_channel = await self._get_author_voice_channel(interaction)
        if voice_channel is None:
            await interaction.response.send_message("Bạn vào voice trước thì mình mới nói được nha!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client
        try:
            if voice_client and voice_client.is_connected():
                await voice_client.move_to(voice_channel)
            else:
                voice_client = await voice_channel.connect(timeout=12, reconnect=False, self_deaf=True)
        except TimeoutError:
            await interaction.followup.send("Kết nối voice bị timeout, bạn thử lại sau ít giây nha.", ephemeral=True)
            return
        except Exception as exc:
            if self._is_voice_4006(exc):
                await interaction.followup.send(
                    "Voice đang lỗi kết nối (4006), nên mình chưa nói được. Bạn đảm bảo chỉ có 1 bot instance đang chạy rồi thử lại nha.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(f"Mình vào voice chưa được: {exc}", ephemeral=True)
            return

        try:
            if voice_client.is_playing():
                await interaction.followup.send("Mình đang bận nói rồi, chờ mình một chút nha.", ephemeral=True)
                return
            await interaction.followup.send("Đang nói đây...", ephemeral=True)
            await self._play_tts(voice_client, text)
        except Exception as exc:
            await interaction.followup.send(f"Ủa mình nói không được: {exc}", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or member.guild is None:
            return

        settings = await self.bot.get_guild_settings(member.guild.id)
        if settings.get("voiceinout_enabled"):
            before_channel_id = getattr(before.channel, "id", None)
            after_channel_id = getattr(after.channel, "id", None)
            joined_voice_client = self._get_voice_client_for_channel(member.guild, after_channel_id)
            left_voice_client = self._get_voice_client_for_channel(member.guild, before_channel_id)
            if after_channel_id != before_channel_id:
                if joined_voice_client is not None and after_channel_id is not None:
                    await self._play_tts(
                        joined_voice_client,
                        self._render_line(VOICE_JOIN_LINES, name=member.display_name),
                    )
                elif left_voice_client is not None and before_channel_id is not None:
                    await self._play_tts(
                        left_voice_client,
                        self._render_line(VOICE_LEAVE_LINES, name=member.display_name),
                    )

        if settings.get("voicestream_enabled") and after.channel is not None:
            started_stream = bool(after.self_stream) and not bool(before.self_stream)
            if started_stream:
                voice_client = self._get_shared_voice_client(member)
                if voice_client is not None:
                    await self._play_tts(
                        voice_client,
                        self._render_line(VOICE_STREAM_LINES, name=member.display_name),
                    )

        if settings.get("autojoin_enabled") and before.channel is None and after.channel is not None:
            voice_client = member.guild.voice_client
            if voice_client is None or not voice_client.is_connected():
                guild_id = member.guild.id
                now = asyncio.get_running_loop().time()
                next_retry = self._autojoin_next_retry.get(guild_id, 0.0)
                if now < next_retry:
                    return
                lock = self._autojoin_locks.setdefault(guild_id, asyncio.Lock())
                if lock.locked():
                    return
                async with lock:
                    try:
                        await asyncio.sleep(1)
                        await after.channel.connect(timeout=12, reconnect=False, self_deaf=True)
                        self._autojoin_fail_count[guild_id] = 0
                        self._autojoin_next_retry[guild_id] = 0.0
                        await self.bot.guild_log(guild_id, f"Mình tự động join {after.channel.mention} rồi nha!")
                    except Exception as exc:
                        fail_count = self._autojoin_fail_count.get(guild_id, 0) + 1
                        self._autojoin_fail_count[guild_id] = fail_count
                        delay = min(300, 15 * (2 ** (fail_count - 1)))
                        self._autojoin_next_retry[guild_id] = asyncio.get_running_loop().time() + delay
                        if self._is_voice_4006(exc) and fail_count >= 3:
                            await self.bot.patch_guild_settings(
                                guild_id,
                                lambda guild: guild.update({"autojoin_enabled": False}),
                            )
                            await self.bot.guild_log(
                                guild_id,
                                "Autojoin đã tự tắt sau nhiều lần lỗi voice 4006. Bạn có thể bật lại bằng /autojoin khi ổn định.",
                            )
                            return
                        await self.bot.guild_log(
                            guild_id,
                            f"Autojoin thất bại ({type(exc).__name__}), sẽ thử lại sau {delay}s.",
                        )

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or after.guild is None:
            return
        settings = await self.bot.get_guild_settings(after.guild.id)
        if not settings.get("voiceactivity_enabled"):
            return
        voice_client = self._get_shared_voice_client(after)
        if voice_client is None:
            return
        started = self._activity_names(after) - self._activity_names(before)
        if not started:
            return
        activity_name = sorted(started)[0]
        await self._play_tts(
            voice_client,
            self._render_line(VOICE_ACTIVITY_LINES, name=after.display_name, activity=activity_name),
        )


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
