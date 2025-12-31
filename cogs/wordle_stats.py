import re
import asyncio
from collections import defaultdict, Counter
from io import BytesIO
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image, ImageDraw
import discord
from discord.ext import commands
from discord import app_commands


WORDLE_PATTERN = re.compile(r"Your group is on \d+ day streak|Here are yesterday's results|[1-6X]/6:|👑", re.IGNORECASE)
# Fixed channel id as requested
CHANNEL_ID = 708795613575249941


class WordleStats(commands.Cog):
    """Collect and display Wordle results posted in the specific offerings channel.

    The `/wordle_stats` command takes no arguments; it scans the fixed channel
    and stops when it reaches the beginning of the tracked streak (group streak == 1).
    """

    def __init__(self, bot):
        self.bot = bot
        self._member_cache = {}

    def parse_wordle_post(self, content: str):
        """Parse a Wordle post's text and return (results, group_streak).

        results: list of (score, players) where players are either ints (ids) or '@name' strings.
        group_streak: int or None
        """
        results = []
        group_streak = None

        for line in (content or "").splitlines():
            line = line.strip()
            if not line:
                continue

            m_streak = re.search(r"Your group is on a (\d+) day streak", line)
            if m_streak:
                try:
                    group_streak = int(m_streak.group(1))
                except Exception:
                    pass
                continue

            m = re.search(r"(?P<score>[1-6X])/6:\s*(?P<players>.+)", line)
            if not m:
                continue

            score = m.group("score")
            players_str = m.group("players").strip()

            # Try to extract mention ids first
            mention_ids = re.findall(r"<@!?(\d+)>", players_str)
            players = []
            if mention_ids:
                players = [int(pid) for pid in mention_ids]
            else:
                if players_str.startswith("@"):
                    parts = [p.strip() for p in players_str[1:].split(" @") if p.strip()]
                    players = ["@" + p for p in parts]
                else:
                    players = [p.strip() for p in players_str.split() if p.strip()]

            results.append((score, players))

        return results, group_streak

    async def resolve_player(self, guild: discord.Guild, player_token):
        """Resolve token to (display_name, member or None)."""
        if isinstance(player_token, int):
            member = guild.get_member(player_token)
            if member is None:
                try:
                    member = await guild.fetch_member(player_token)
                except Exception:
                    member = None

            if member:
                # cache member
                self._member_cache[player_token] = member
                return member.display_name, member
            return f"<@{player_token}>", None

        if isinstance(player_token, str) and player_token.startswith("@"):
            return player_token[1:], None

        return str(player_token), None

    async def resolve_player_name(self, guild: discord.Guild, player_token):
        """Resolve token to display name; cache members to reduce REST calls."""
        if isinstance(player_token, int):
            if player_token in self._member_cache:
                return self._member_cache[player_token].display_name

            member = guild.get_member(player_token)
            if member is None:
                try:
                    member = await guild.fetch_member(player_token)
                except Exception:
                    member = None

            if member:
                self._member_cache[player_token] = member
                return member.display_name
            return f"<@{player_token}>"

        if isinstance(player_token, str) and player_token.startswith("@"):
            return player_token[1:]

        return str(player_token)

    @app_commands.command(name="wordle_stats", description="Show Wordle stats from the offerings-to-dan channel")
    async def wordle_stats(self, interaction: discord.Interaction):
        await interaction.response.defer()

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("This command must be used in a server.")
            return

        channel = guild.get_channel(CHANNEL_ID) or self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            await interaction.followup.send(f"Could not find the channel with ID {CHANNEL_ID} in this server.")
            return

        # Collect matching Wordle posts newest -> oldest until we hit streak==1
        matches = []  # list of (message, combined_text)
        pattern = WORDLE_PATTERN
        try:
            counter = 0
            async for m in channel.history(limit=None, oldest_first=False):
                counter += 1

                # Build combined text from content + embed descriptions/fields
                combined = m.content or ""
                if getattr(m, 'embeds', None):
                    for emb in m.embeds:
                        if getattr(emb, 'description', None):
                            combined += "\n" + emb.description
                        for f in getattr(emb, 'fields', []):
                            if getattr(f, 'value', None):
                                combined += "\n" + f.value

                if combined and pattern.search(combined):
                    matches.append((m, combined))
                    # Check for group streak and stop when we find streak==1
                    _, grp = self.parse_wordle_post(combined)
                    if grp == 1:
                        break

                # throttle to reduce rate-limit risk
                if counter % 25 == 0:
                    await asyncio.sleep(0.12)
        except discord.Forbidden:
            await interaction.followup.send("I don't have access to that channel.")
            return
        except Exception as e:
            await interaction.followup.send(f"Error scanning channel history: {e}")
            return

        if not matches:
            await interaction.followup.send("No Wordle posts found in the scanned range.")
            return

        # Aggregate stats; process matches in chronological order
        per_player = defaultdict(lambda: {"appearances": 0, "completions": 0, "fails": 0, "attempts": Counter(), "longest_streak": 0, "current_streak": 0})
        group_streaks = []

        # Map display_name -> member (when resolvable) for avatar fetching
        player_member_map = {}

        for message, combined in reversed(matches):
            parsed, grp = self.parse_wordle_post(combined)
            if grp:
                group_streaks.append((message.created_at, grp))

            for score, players in parsed:
                is_fail = score == "X"
                resolved = []
                for token in players:
                    name, member = await self.resolve_player(guild, token)
                    resolved.append(name)
                    if member:
                        # prefer existing mapping if already set
                        player_member_map.setdefault(name, member)

                for name in resolved:
                    data = per_player[name]
                    data["appearances"] += 1
                    if is_fail:
                        data["fails"] += 1
                        data["current_streak"] = 0
                    else:
                        data["completions"] += 1
                        try:
                            attempts = int(score)
                        except Exception:
                            attempts = None
                        if attempts:
                            data["attempts"][attempts] += 1

                        data["current_streak"] += 1
                        if data["current_streak"] > data["longest_streak"]:
                            data["longest_streak"] = data["current_streak"]

        # Build graphs for top completions and longest streaks and send images only
        top_completions = sorted(per_player.items(), key=lambda x: x[1]["completions"], reverse=True)[:10]
        top_streaks = sorted(per_player.items(), key=lambda x: x[1]["longest_streak"], reverse=True)[:10]

        files_to_send = []

        if top_completions:
            try:
                completions_path = await self.generate_completions_graph(guild, top_completions, player_member_map)
                files_to_send.append(discord.File(completions_path, filename=os.path.basename(completions_path)))
            except Exception as e:
                print(f"Failed to generate completions graph: {e}")

        if top_streaks:
            try:
                streaks_path = await self.generate_streaks_graph(guild, top_streaks, player_member_map)
                files_to_send.append(discord.File(streaks_path, filename=os.path.basename(streaks_path)))
            except Exception as e:
                print(f"Failed to generate streaks graph: {e}")

        if not files_to_send:
            await interaction.followup.send("No Wordle data found to plot.")
            return

        try:
            await interaction.followup.send(files=files_to_send)
        finally:
            # cleanup
            for f in files_to_send:
                try:
                    os.remove(f.filename)
                except Exception:
                    pass

    async def generate_completions_graph(self, guild: discord.Guild, top_completions, player_member_map: dict):
        """Generate a horizontal bar chart for top completions and return the file path."""
        # top_completions: list of (name, stats)
        names = [n for n, _ in top_completions]
        counts = [s["completions"] for _, s in top_completions]

        num = len(names)
        fig_height = max(3, num * 0.6)
        fig, ax = plt.subplots(figsize=(10, fig_height))
        fig.patch.set_facecolor("#2C2F33")
        ax.set_facecolor("#2C2F33")

        # Fetch avatars and compute average colors for bars
        avatars = []
        bar_colors = []
        for name in names:
            member = player_member_map.get(name)
            avatar_img = None
            avg_hex = "#00BFA5"  # default completion color
            if member:
                try:
                    avatar_url = member.avatar.url if getattr(member, 'avatar', None) else member.display_avatar.url
                except Exception:
                    avatar_url = None
                if avatar_url:
                    try:
                        async with self.bot.http._HTTPClient__session.get(str(avatar_url)) as resp:
                            avatar_data = await resp.read()
                        avatar = Image.open(BytesIO(avatar_data)).convert("RGBA").resize((36, 36))
                        # compute average color from RGB channels
                        avatar_array = np.array(avatar)[..., :3]
                        avg_color = tuple(avatar_array.mean(axis=(0, 1)).astype(int))
                        avg_hex = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
                        # circular mask
                        mask = Image.new("L", avatar.size, 0)
                        draw = ImageDraw.Draw(mask)
                        draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                        avatar.putalpha(mask)
                        avatar_img = avatar
                    except Exception:
                        avatar_img = None

            avatars.append(avatar_img)
            bar_colors.append(avg_hex)

        y = np.arange(num)
        bars = ax.barh(y, counts, color=bar_colors, height=0.6, edgecolor="none")

        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12)
        ax.invert_yaxis()
        ax.set_xlabel("Completions", color="#FFFFFF")
        ax.set_title("Top Wordle Completions", color="#FFFFFF", fontsize=16)
        ax.tick_params(axis="x", colors="#FFFFFF")

        # Add counts at end of bars and place avatars
        max_count = max(counts) if counts else 1
        for i, b in enumerate(bars):
            x = b.get_width()
            y_pos = b.get_y() + b.get_height() / 2
            if avatars[i] is not None:
                avatar_img = avatars[i]
                avatar_box = OffsetImage(avatar_img, zoom=1)
                ab = AnnotationBbox(avatar_box, (x + max_count * 0.03, y_pos), frameon=False, xycoords="data", box_alignment=(0.5, 0.5))
                ax.add_artist(ab)
                text_x = x + max_count * 0.08
            else:
                text_x = x + max_count * 0.02

            ax.text(text_x, y_pos, str(counts[i]), va="center", color="#FFFFFF", fontsize=12)

        plt.tight_layout()
        out_path = "wordle_top_completions.png"
        plt.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()
        return out_path

    async def generate_streaks_graph(self, guild: discord.Guild, top_streaks, player_member_map: dict):
        """Generate a horizontal bar chart for longest completion streaks and return the file path."""
        names = [n for n, _ in top_streaks]
        counts = [s["longest_streak"] for _, s in top_streaks]

        num = len(names)
        fig_height = max(3, num * 0.6)
        fig, ax = plt.subplots(figsize=(10, fig_height))
        fig.patch.set_facecolor("#2C2F33")
        ax.set_facecolor("#2C2F33")

        y = np.arange(num)
        bars = ax.barh(y, counts, color="#FFB74D", height=0.6, edgecolor="none")

        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12)
        ax.invert_yaxis()
        ax.set_xlabel("Days", color="#FFFFFF")
        ax.set_title("Longest Recorded Completion Streaks", color="#FFFFFF", fontsize=16)
        ax.tick_params(axis="x", colors="#FFFFFF")

        max_count = max(counts) if counts else 1

        # Fetch avatars similar to completions chart
        avatars = []
        for name in names:
            member = player_member_map.get(name)
            if member:
                try:
                    avatar_url = member.avatar.url if getattr(member, 'avatar', None) else member.display_avatar.url
                except Exception:
                    avatar_url = None
            else:
                avatar_url = None

            if avatar_url:
                try:
                    async with self.bot.http._HTTPClient__session.get(str(avatar_url)) as resp:
                        avatar_data = await resp.read()
                    avatar = Image.open(BytesIO(avatar_data)).convert("RGBA").resize((36, 36))
                    mask = Image.new("L", avatar.size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                    avatar.putalpha(mask)
                    avatars.append(avatar)
                except Exception:
                    avatars.append(None)
            else:
                avatars.append(None)

        for i, b in enumerate(bars):
            x = b.get_width()
            y_pos = b.get_y() + b.get_height() / 2
            if avatars[i] is not None:
                avatar_img = avatars[i]
                avatar_box = OffsetImage(avatar_img, zoom=1)
                ab = AnnotationBbox(avatar_box, (x + max_count * 0.03, y_pos), frameon=False, xycoords="data", box_alignment=(0.5, 0.5))
                ax.add_artist(ab)
                text_x = x + max_count * 0.08
            else:
                text_x = x + max_count * 0.02

            ax.text(text_x, y_pos, str(counts[i]), va="center", color="#FFFFFF", fontsize=12)

        plt.tight_layout()
        out_path = "wordle_top_streaks.png"
        plt.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()
        return out_path


async def setup(bot):
    await bot.add_cog(WordleStats(bot))
