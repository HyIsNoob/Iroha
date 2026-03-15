import asyncio
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from discord.errors import ConnectionClosed
from gtts import gTTS


class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._autojoin_locks: dict[int, asyncio.Lock] = {}
        self._autojoin_fail_count: dict[int, int] = {}
        self._autojoin_next_retry: dict[int, float] = {}

    @staticmethod
    def _is_voice_4006(exc: Exception) -> bool:
        return isinstance(exc, ConnectionClosed) and getattr(exc, "code", None) == 4006

    async def _get_author_voice_channel(self, interaction: discord.Interaction):
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            return None
        return interaction.user.voice.channel

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
                await voice_channel.connect(timeout=12, reconnect=True, self_deaf=True)
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

        if voice_client.is_playing():
            voice_client.stop()

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
            tts = gTTS(text=text, lang="vi")
            tts.save(str(temp_path))
            source = discord.FFmpegPCMAudio(str(temp_path))
            done = asyncio.Event()

            def after_playback(_error):
                done.set()

            voice_client.play(source, after=after_playback)
            await interaction.followup.send("Đang nói đây...", ephemeral=True)
            await done.wait()
        except Exception as exc:
            await interaction.followup.send(f"Ủa mình nói không được: {exc}", ephemeral=True)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or member.guild is None:
            return

        settings = await self.bot.get_guild_settings(member.guild.id)
        if settings.get("voiceinout_enabled"):
            if before.channel is None and after.channel is not None:
                await self.bot.guild_log(member.guild.id, f"{member.mention} vừa join {after.channel.mention}")
            elif before.channel is not None and after.channel is None:
                await self.bot.guild_log(member.guild.id, f"{member.mention} vừa rời {before.channel.mention}")

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


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
