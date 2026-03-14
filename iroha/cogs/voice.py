import asyncio
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from gtts import gTTS


class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_author_voice_channel(self, interaction: discord.Interaction):
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            return None
        return interaction.user.voice.channel

    @app_commands.command(name="connect", description="Cho Iroha vào voice channel của bạn")
    async def connect(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        voice_channel = await self._get_author_voice_channel(interaction)
        if voice_channel is None:
            await interaction.response.send_message("Bạn phải vào voice trước.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.move_to(voice_channel)
        else:
            await voice_channel.connect()
        await interaction.response.send_message(f"Iroha đã vào {voice_channel.mention}.")

    @app_commands.command(name="disconnect", description="Cho Iroha rời voice channel")
    async def disconnect(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("Iroha chưa vào voice.", ephemeral=True)
            return
        await voice_client.disconnect(force=True)
        await interaction.response.send_message("Iroha đã rời voice channel.")

    @app_commands.command(name="autojoin", description="Bật hoặc tắt tự động join voice")
    @app_commands.default_permissions(manage_guild=True)
    async def autojoin(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"autojoin_enabled": enabled}),
        )
        await interaction.response.send_message(f"Autojoin đã {'bật' if enabled else 'tắt'}.")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {'bật' if enabled else 'tắt'} autojoin")

    @app_commands.command(name="voiceinout", description="Bật hoặc tắt thông báo join/leave voice")
    @app_commands.default_permissions(manage_guild=True)
    async def voiceinout(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        await self.bot.patch_guild_settings(
            interaction.guild.id,
            lambda guild: guild.update({"voiceinout_enabled": enabled}),
        )
        await interaction.response.send_message(f"Voice in/out đã {'bật' if enabled else 'tắt'}.")
        await self.bot.guild_log(interaction.guild.id, f"{interaction.user.mention} {'bật' if enabled else 'tắt'} voiceinout")

    @app_commands.command(name="speak", description="Iroha nói trong voice channel")
    async def speak(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 200]):
        if interaction.guild is None:
            await interaction.response.send_message("Chỉ dùng trong server.", ephemeral=True)
            return
        voice_channel = await self._get_author_voice_channel(interaction)
        if voice_channel is None:
            await interaction.response.send_message("Bạn phải vào voice trước.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.move_to(voice_channel)
        else:
            voice_client = await voice_channel.connect()

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
            await interaction.followup.send("Iroha đang nói.", ephemeral=True)
            await done.wait()
        except Exception as exc:
            await interaction.followup.send(f"Không thể phát giọng nói: {exc}", ephemeral=True)
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
                try:
                    await after.channel.connect()
                    await self.bot.guild_log(member.guild.id, f"Iroha tự động join {after.channel.mention}")
                except Exception:
                    return


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
