import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

_EVENT_VOICE_JOIN = "voice_join"
_EVENT_STREAM_START = "stream_start"
_EVENT_GAME_START = "game_start"
_ALL_EVENTS = [_EVENT_VOICE_JOIN, _EVENT_STREAM_START, _EVENT_GAME_START]
_EVENT_LABELS = {
    _EVENT_VOICE_JOIN: "Join voice",
    _EVENT_STREAM_START: "Start livestream",
    _EVENT_GAME_START: "Start game/app",
}
_SCOPE_USER = "user"
_SCOPE_SERVER = "server"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class NotifyPanelView(discord.ui.View):
    def __init__(self, cog: "NotifyCog", guild_id: int, user_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Panel này không phải của bạn.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction):
        settings = await self.cog.bot.get_notify_user_settings(self.guild_id, self.user_id)
        embed = self.cog.build_panel_embed(interaction.user, settings)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="ON", style=discord.ButtonStyle.success, row=0)
    async def enable_notify(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.cog.bot.patch_notify_user_settings(
            self.guild_id,
            self.user_id,
            lambda user: user.update({"enabled": True}),
        )
        await self._refresh(interaction)

    @discord.ui.button(label="OFF", style=discord.ButtonStyle.danger, row=0)
    async def disable_notify(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.cog.bot.patch_notify_user_settings(
            self.guild_id,
            self.user_id,
            lambda user: user.update({"enabled": False}),
        )
        await self._refresh(interaction)

    @discord.ui.button(label="Pause 1h", style=discord.ButtonStyle.secondary, row=0)
    async def pause_one_hour(self, interaction: discord.Interaction, _button: discord.ui.Button):
        paused_until = (_now_utc() + timedelta(hours=1)).isoformat()
        await self.cog.bot.patch_notify_user_settings(
            self.guild_id,
            self.user_id,
            lambda user: user.update({"paused_until": paused_until}),
        )
        await self._refresh(interaction)

    @discord.ui.button(label="Pause 8h", style=discord.ButtonStyle.secondary, row=0)
    async def pause_eight_hours(self, interaction: discord.Interaction, _button: discord.ui.Button):
        paused_until = (_now_utc() + timedelta(hours=8)).isoformat()
        await self.cog.bot.patch_notify_user_settings(
            self.guild_id,
            self.user_id,
            lambda user: user.update({"paused_until": paused_until}),
        )
        await self._refresh(interaction)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.primary, row=0)
    async def resume_notify(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.cog.bot.patch_notify_user_settings(
            self.guild_id,
            self.user_id,
            lambda user: user.update({"paused_until": None}),
        )
        await self._refresh(interaction)

    @discord.ui.button(label="Not-in-voice", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_not_in_voice(self, interaction: discord.Interaction, _button: discord.ui.Button):
        def patcher(user: dict):
            current = bool(user.get("only_when_not_in_voice", True))
            user["only_when_not_in_voice"] = not current

        await self.cog.bot.patch_notify_user_settings(self.guild_id, self.user_id, patcher)
        await self._refresh(interaction)

    @discord.ui.button(label="Test DM", style=discord.ButtonStyle.primary, row=1)
    async def test_dm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        ok = await self.cog.send_test_dm(interaction.user)
        await interaction.response.send_message(
            "Đã gửi DM test." if ok else "Không gửi được DM test. Có thể bạn đang chặn DM từ server.",
            ephemeral=True,
        )


class NotifyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cooldowns: dict[tuple[int, int, int, str], float] = {}

    @staticmethod
    def _default_settings() -> dict:
        return {
            "enabled": False,
            "paused_until": None,
            "only_when_not_in_voice": True,
            "cooldown_seconds": 300,
            "subscriptions": [],
        }

    def _normalize_settings(self, raw: dict | None) -> dict:
        merged = self._default_settings()
        if raw:
            merged.update(raw)
        if not isinstance(merged.get("subscriptions"), list):
            merged["subscriptions"] = []
        return merged

    @staticmethod
    def _is_paused(settings: dict) -> bool:
        paused_until = _parse_dt(settings.get("paused_until"))
        if paused_until is None:
            return False
        return paused_until > _now_utc()

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

    def _is_matching_subscription(self, subscription: dict, event_type: str, actor_id: int) -> bool:
        if subscription.get("event") != event_type:
            return False
        scope = subscription.get("scope")
        if scope == _SCOPE_SERVER:
            return True
        if scope == _SCOPE_USER:
            return int(subscription.get("target_user_id") or 0) == actor_id
        return False

    @staticmethod
    def _subscription_label(subscription: dict) -> str:
        event_key = str(subscription.get("event") or "unknown")
        event_label = _EVENT_LABELS.get(event_key, event_key)
        if subscription.get("scope") == _SCOPE_SERVER:
            return f"Server · {event_label}"
        target_user_id = int(subscription.get("target_user_id") or 0)
        return f"User <@{target_user_id}> · {event_label}"

    def build_panel_embed(self, user: discord.abc.User, settings: dict) -> discord.Embed:
        merged = self._normalize_settings(settings)
        enabled_text = "ON" if merged.get("enabled") else "OFF"
        paused_until = _parse_dt(merged.get("paused_until"))
        paused_text = "Không"
        if paused_until and paused_until > _now_utc():
            paused_text = f"Đến <t:{int(paused_until.timestamp())}:R>"
        only_not_in_voice = "Có" if merged.get("only_when_not_in_voice", True) else "Không"
        subscriptions = merged.get("subscriptions", [])

        embed = discord.Embed(title="Notify DM Panel", color=discord.Color(0x4A90E2))
        embed.add_field(name="Trạng thái", value=enabled_text, inline=True)
        embed.add_field(name="Đang pause", value=paused_text, inline=True)
        embed.add_field(name="Chỉ khi không ở voice", value=only_not_in_voice, inline=True)
        embed.add_field(name="Cooldown", value=f"{int(merged.get('cooldown_seconds', 300))}s", inline=True)
        embed.add_field(name="Số đăng ký", value=str(len(subscriptions)), inline=True)
        embed.set_footer(text=f"Subscriber: {getattr(user, 'display_name', user.name)}")
        return embed

    async def send_test_dm(self, user: discord.User | discord.Member) -> bool:
        try:
            await user.send("DM test: hệ thống notify đang hoạt động.")
            return True
        except discord.Forbidden:
            return False
        except Exception:
            return False

    async def _dispatch_notify_event(
        self,
        guild: discord.Guild,
        actor: discord.Member,
        event_type: str,
        channel: discord.abc.GuildChannel | None = None,
        activity_name: str | None = None,
    ):
        subscribers = await self.bot.get_notify_subscribers(guild.id)
        if not subscribers:
            return
        now = asyncio.get_running_loop().time()

        for subscriber_id_raw, raw_settings in subscribers.items():
            subscriber_id = int(subscriber_id_raw)
            if subscriber_id == actor.id:
                continue
            settings = self._normalize_settings(raw_settings)
            if not settings.get("enabled"):
                continue
            if self._is_paused(settings):
                continue

            has_match = False
            for subscription in settings.get("subscriptions", []):
                if self._is_matching_subscription(subscription, event_type, actor.id):
                    has_match = True
                    break
            if not has_match:
                continue

            member = guild.get_member(subscriber_id)
            if member is None:
                continue
            if settings.get("only_when_not_in_voice", True):
                if member.voice is not None and member.voice.channel is not None:
                    continue

            cooldown_seconds = max(15, int(settings.get("cooldown_seconds", 300)))
            cooldown_key = (guild.id, subscriber_id, actor.id, event_type)
            if now < self._cooldowns.get(cooldown_key, 0.0):
                continue

            if event_type == _EVENT_VOICE_JOIN:
                channel_text = getattr(channel, "mention", "voice")
                message = f"{actor.display_name} vừa vào {channel_text} ở **{guild.name}**."
            elif event_type == _EVENT_STREAM_START:
                channel_text = getattr(channel, "mention", "voice")
                message = f"{actor.display_name} vừa bắt đầu livestream trong {channel_text} ở **{guild.name}**."
            else:
                activity_text = activity_name or "một ứng dụng"
                message = f"{actor.display_name} vừa mở **{activity_text}** ở **{guild.name}**."

            try:
                await member.send(message)
                self._cooldowns[cooldown_key] = now + cooldown_seconds
            except discord.Forbidden:
                self._cooldowns[cooldown_key] = now + cooldown_seconds
            except Exception:
                self._cooldowns[cooldown_key] = now + cooldown_seconds

    @app_commands.command(name="notify_subscribe", description="Đăng ký nhận DM khi có event")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="user", value=_SCOPE_USER),
            app_commands.Choice(name="server", value=_SCOPE_SERVER),
        ],
        event=[
            app_commands.Choice(name="all", value="all"),
            app_commands.Choice(name="voice_join", value=_EVENT_VOICE_JOIN),
            app_commands.Choice(name="stream_start", value=_EVENT_STREAM_START),
            app_commands.Choice(name="game_start", value=_EVENT_GAME_START),
        ],
    )
    async def notify_subscribe(
        self,
        interaction: discord.Interaction,
        scope: str,
        event: str = "all",
        user: discord.Member | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng trong server.", ephemeral=True)
            return
        if scope == _SCOPE_USER and user is None:
            await interaction.response.send_message("Bạn cần chọn user khi scope là user.", ephemeral=True)
            return
        if scope == _SCOPE_USER and user is not None and user.bot:
            await interaction.response.send_message("Không hỗ trợ theo dõi bot.", ephemeral=True)
            return

        events = _ALL_EVENTS if event == "all" else [event]
        user_id = interaction.user.id
        target_user_id = user.id if user is not None else None

        def patcher(settings: dict):
            subscriptions = settings.setdefault("subscriptions", [])
            for event_name in events:
                candidate: dict[str, object] = {"scope": scope, "event": event_name}
                candidate_target_user_id = 0
                if scope == _SCOPE_USER:
                    candidate_target_user_id = int(target_user_id or 0)
                    candidate["target_user_id"] = candidate_target_user_id
                exists = False
                for item in subscriptions:
                    if item.get("scope") != candidate.get("scope"):
                        continue
                    if item.get("event") != candidate.get("event"):
                        continue
                    if int(item.get("target_user_id") or 0) != candidate_target_user_id:
                        continue
                    exists = True
                    break
                if not exists:
                    subscriptions.append(candidate)
            settings["enabled"] = True

        await self.bot.patch_notify_user_settings(interaction.guild.id, user_id, patcher)
        await interaction.response.send_message("Đăng ký notify thành công. Dùng /notify_panel để bật tắt nhanh.", ephemeral=True)

    @app_commands.command(name="notify_unsubscribe", description="Hủy đăng ký nhận DM")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="user", value=_SCOPE_USER),
            app_commands.Choice(name="server", value=_SCOPE_SERVER),
        ],
        event=[
            app_commands.Choice(name="all", value="all"),
            app_commands.Choice(name="voice_join", value=_EVENT_VOICE_JOIN),
            app_commands.Choice(name="stream_start", value=_EVENT_STREAM_START),
            app_commands.Choice(name="game_start", value=_EVENT_GAME_START),
        ],
    )
    async def notify_unsubscribe(
        self,
        interaction: discord.Interaction,
        scope: str,
        event: str = "all",
        user: discord.Member | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng trong server.", ephemeral=True)
            return
        if scope == _SCOPE_USER and user is None:
            await interaction.response.send_message("Bạn cần chọn user khi scope là user.", ephemeral=True)
            return

        events = set(_ALL_EVENTS if event == "all" else [event])
        target_user_id = user.id if user is not None else None

        def patcher(settings: dict):
            subscriptions = settings.setdefault("subscriptions", [])
            filtered = []
            for item in subscriptions:
                if item.get("scope") != scope:
                    filtered.append(item)
                    continue
                if item.get("event") not in events:
                    filtered.append(item)
                    continue
                if scope == _SCOPE_USER:
                    if int(item.get("target_user_id") or 0) != int(target_user_id or 0):
                        filtered.append(item)
            settings["subscriptions"] = filtered

        await self.bot.patch_notify_user_settings(interaction.guild.id, interaction.user.id, patcher)
        await interaction.response.send_message("Đã hủy đăng ký theo điều kiện bạn chọn.", ephemeral=True)

    @app_commands.command(name="notify_list", description="Xem danh sách đăng ký notify của bạn")
    async def notify_list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng trong server.", ephemeral=True)
            return

        settings = await self.bot.get_notify_user_settings(interaction.guild.id, interaction.user.id)
        settings = self._normalize_settings(settings)

        lines = []
        for idx, subscription in enumerate(settings.get("subscriptions", []), start=1):
            lines.append(f"{idx}. {self._subscription_label(subscription)}")
        if not lines:
            lines = ["Chưa có đăng ký nào."]

        paused_until = _parse_dt(settings.get("paused_until"))
        paused_text = "Không"
        if paused_until and paused_until > _now_utc():
            paused_text = f"Đến <t:{int(paused_until.timestamp())}:R>"

        embed = discord.Embed(title="Notify subscriptions", color=discord.Color(0x4A90E2))
        embed.add_field(name="Enabled", value="ON" if settings.get("enabled") else "OFF", inline=True)
        embed.add_field(name="Pause", value=paused_text, inline=True)
        embed.add_field(name="Only when not in voice", value="Có" if settings.get("only_when_not_in_voice", True) else "Không", inline=True)
        embed.add_field(name="Danh sách", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="notify_panel", description="Mở panel bật tắt notify nhanh")
    async def notify_panel(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng trong server.", ephemeral=True)
            return
        settings = await self.bot.get_notify_user_settings(interaction.guild.id, interaction.user.id)
        embed = self.build_panel_embed(interaction.user, settings)
        view = NotifyPanelView(self, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or member.guild is None:
            return

        if before.channel is None and after.channel is not None:
            await self._dispatch_notify_event(
                member.guild,
                member,
                _EVENT_VOICE_JOIN,
                channel=after.channel,
            )

        started_stream = bool(after.self_stream) and not bool(before.self_stream)
        if started_stream and after.channel is not None:
            await self._dispatch_notify_event(
                member.guild,
                member,
                _EVENT_STREAM_START,
                channel=after.channel,
            )

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or after.guild is None:
            return

        started = self._activity_names(after) - self._activity_names(before)
        if not started:
            return
        activity_name = sorted(started)[0]
        await self._dispatch_notify_event(
            after.guild,
            after,
            _EVENT_GAME_START,
            activity_name=activity_name,
        )


async def setup(bot):
    await bot.add_cog(NotifyCog(bot))
