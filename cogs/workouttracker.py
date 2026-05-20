import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
import aiohttp
from collections import defaultdict
import json
import os
from io import BytesIO

# Plotting libs
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

from database import DatabaseManager

# Local Insult & Motivation Engine (Zero-dependency Dan persona)
DAN_INSULTS = [
    "Did you set a goal just to prove you are a serial quitter? Get moving.",
    "I've seen glaciers move faster than you. Go sweat off that laziness.",
    "Are your muscles made of cotton candy? Because you're melting under a simple goal.",
    "Excuses build monuments of nothingness. You are currently the chief architect.",
    "You said you'd do it. Was that before or after you decided to take a nap on the couch?",
    "If slacking off burned calories, you'd be a fitness model by now.",
    "The only workout you did this week was scrolling through your phone. Put it down and train.",
    "Lifting a donut to your mouth does not count as a bicep curl. Go lift some iron.",
    "Your workout tracker is looking as blank as your motivation. Get it together.",
    "Even my grandmother can press more than your weekly motivation. Lift the heavy circle.",
    "You missed your goal again. Are you proud of being this consistent at failing?",
    "Stop talking about it. Stop posting about it. Just go sweat.",
    "Weakness is a choice. And boy, are you making that choice loudly and clearly.",
    "The gym misses you. Or actually, it doesn't, because it prefers people who actually lift.",
    "Is that couch really that comfortable? Or are you just afraid of a little sweat?",
    "Congratulations on meeting 0% of your potential this week. A stellar achievement.",
    "My processor calculates a 100% chance that you are currently slacking off. Move.",
    "You had one job: do what you said you would do. Instead, you did nothing. Classic."
]

DAN_DM_RESPONSES = [
    "Why are you messaging me? Go lift some weights instead.",
    "Did you write this from the couch? Because it sounds like lazy talking.",
    "I'm a bot and even I have a higher active rate than you. Go train.",
    "Don't cry to me about how hard it is. Go put in the work.",
    "Your excuses are boring. The weights aren't going to lift themselves.",
    "You want sympathy? Look it up in the dictionary between 'slacker' and 'weakling'.",
    "Stop texting me. Go sweat.",
    "If you spent half as much energy lifting as you did talking, you'd be a champion."
]

def get_demeaning_message() -> str:
    """Select and return a random demeaning motivation message from the local engine."""
    return random.choice(DAN_INSULTS)

import random

def get_next_weekly_reset():
    now = datetime.now()
    days_until_sunday = (6 - now.weekday()) % 7
    next_reset = now.replace(hour=23, minute=50, second=59, microsecond=0) + timedelta(days=days_until_sunday)
    if next_reset < now:
        next_reset += timedelta(weeks=1)
    return next_reset


class AcknowledgeWorkoutButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Completely persistent across bot restarts

    @discord.ui.button(label="Acknowledge & Stay in Tracker", style=discord.ui.ButtonStyle.green, custom_id="ack_workout_btn")
    async def acknowledge(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Determine who this warning is actually for from the SQLite database
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute(
                "SELECT user_id FROM pending_workout_warnings WHERE message_id = ?;",
                (interaction.message.id,)
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("This warning is no longer active or already acknowledged.", ephemeral=True)
            return

        warned_user_id = row[0]

        if interaction.user.id != warned_user_id:
            await interaction.response.send_message("This warning isn't for you! Go back to lifting! 😠", ephemeral=True)
            return

        # Delete pending warning in SQLite
        async with await DatabaseManager.get_connection() as conn:
            await conn.execute("DELETE FROM pending_workout_warnings WHERE user_id = ?;", (warned_user_id,))
            await conn.commit()

        # Update warning message to confirm they stay
        await interaction.response.edit_message(
            content=f"🟢 **{interaction.user.mention} has acknowledged their warning and remains in the tracker!** Don't slack off this week! 💪",
            view=None
        )


class WorkoutTracker(commands.Cog):
    DEFAULT_CHANNEL_ID = int(os.getenv("WORKOUT_CHANNEL_ID", 1327019216510910546))

    def __init__(self, bot):
        self.bot = bot
        self.warning_threshold = 12 * 60 * 60  # 12 hours before reset
        
        channel_env = os.getenv("WORKOUT_CHANNEL_ID")
        try:
            channel_id = int(channel_env) if channel_env else self.DEFAULT_CHANNEL_ID
        except Exception:
            channel_id = self.DEFAULT_CHANNEL_ID
        self.SPECIFIC_THREAD_ID = channel_id
        self.leaderboard_channel = channel_id
        self.weekly_reset_time = get_next_weekly_reset()
        self.miss_threshold = 2  # Consecutive missed weeks before requiring reaction
        
        # Register the persistent Warning button view
        self.bot.add_view(AcknowledgeWorkoutButton())
        
        bot.loop.create_task(self.schedule_weekly_reset())
        print(f"[WorkoutTracker] Weekly reset scheduled for: {self.weekly_reset_time}")

    async def get_goal(self, user_id: int) -> int:
        """Return the workout goal for a user asynchronously from SQLite."""
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT goal FROM workout_goals WHERE user_id = ?;", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_workouts(self, user_id: int) -> list:
        """Return a user's workout list of datetimes asynchronously from SQLite."""
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT timestamp FROM workout_history WHERE user_id = ?;", (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [datetime.fromisoformat(r[0]) for r in rows]

    async def calculate_streak(self, user_id: int) -> int:
        workouts = sorted(await self.get_workouts(user_id))
        goal = await self.get_goal(user_id)
        if goal <= 0:
            return 0

        now = datetime.now()
        current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        current_week_end = current_week_start + timedelta(days=7)

        streak = 0
        current_week_count = sum(1 for w in workouts if current_week_start <= w < current_week_end)
        if current_week_count >= goal:
            streak += 1
            week_start = current_week_start - timedelta(days=7)
        else:
            week_start = current_week_start - timedelta(days=7)

        for _ in range(52):
            week_end = week_start + timedelta(days=7)
            week_count = sum(1 for w in workouts if week_start <= w < week_end)
            if week_count >= goal:
                streak += 1
                week_start -= timedelta(days=7)
            else:
                break

        return streak

    async def calculate_consecutive_misses(self, user_id: int) -> int:
        workouts = sorted(await self.get_workouts(user_id))
        goal = await self.get_goal(user_id)
        if goal <= 0:
            return 0

        now = datetime.now()
        current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        consecutive_misses = 0
        week_start = current_week_start - timedelta(days=7)

        for _ in range(52):
            week_end = week_start + timedelta(days=7)
            week_count = sum(1 for w in workouts if week_start <= w < week_end)
            if week_count < goal:
                consecutive_misses += 1
                week_start -= timedelta(days=7)
            else:
                break

        return consecutive_misses

    async def calculate_longest_streak(self, user_id: int) -> int:
        workouts = sorted(await self.get_workouts(user_id))
        goal = await self.get_goal(user_id)
        if goal <= 0 or not workouts:
            return 0

        first = workouts[0]
        last = workouts[-1]
        start_week = first.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=first.weekday())
        end_week = last.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=last.weekday())

        week = start_week
        met_weeks = []
        while week <= end_week:
            week_end = week + timedelta(days=7)
            week_count = sum(1 for w in workouts if week <= w < week_end)
            met_weeks.append(week_count >= goal)
            week += timedelta(days=7)

        longest = 0
        current = 0
        for v in met_weeks:
            if v:
                current += 1
                longest = max(longest, current)
            else:
                current = 0

        return longest

    @app_commands.command(name="set_goal", description="Set your weekly workout goal and opt in to tracking.")
    async def set_goal(self, interaction: discord.Interaction, goal_per_week: int):
        if goal_per_week <= 0:
            await interaction.response.send_message("Your goal must be at least 1 workout per week.", ephemeral=True)
            return

        async with await DatabaseManager.get_connection() as conn:
            await conn.execute("INSERT OR REPLACE INTO workout_goals (user_id, goal) VALUES (?, ?);", (interaction.user.id, goal_per_week))
            await conn.commit()

        await interaction.response.send_message(
            f"Your weekly workout goal is set to {goal_per_week} workouts! Let's get moving!", ephemeral=True
        )

        channel = interaction.channel
        if channel:
            await channel.send(
                f"📢 {interaction.user.mention} has joined the workout tracker with a goal of {goal_per_week} workouts per week!"
            )

    @app_commands.command(name="opt_out", description="Opt out of the workout tracker.")
    async def opt_out(self, interaction: discord.Interaction):
        uid = interaction.user.id
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT 1 FROM workout_goals WHERE user_id = ?;", (uid,)) as cursor:
                exists = await cursor.fetchone()

            if exists:
                await conn.execute("DELETE FROM workout_goals WHERE user_id = ?;", (uid,))
                await conn.execute("DELETE FROM workout_history WHERE user_id = ?;", (uid,))
                await conn.execute("DELETE FROM pending_workout_warnings WHERE user_id = ?;", (uid,))
                await conn.commit()

                await interaction.response.send_message(
                    "You have opted out of the workout tracker. But remember, quitting is for the weak! 😠", ephemeral=False
                )
                channel = interaction.channel
                if channel:
                    await channel.send(f"📢 {interaction.user.mention} has quit the workout tracker. I'm not really surprised.")
            else:
                await interaction.response.send_message("You're not currently participating in the tracker.", ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the workout leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT user_id, goal FROM workout_goals;") as cursor:
                users = await cursor.fetchall()

        if not users:
            await interaction.response.send_message("No one has logged any workouts yet! Be the first to start!", ephemeral=True)
            return

        await interaction.response.defer()

        # Gather metrics for all users
        total_workouts = {}
        longest_streaks = {}
        for uid, goal in users:
            w = await self.get_workouts(uid)
            total_workouts[uid] = len(w)
            longest_streaks[uid] = await self.calculate_longest_streak(uid)

        leaderboard_counts = sorted(total_workouts.items(), key=lambda x: x[1], reverse=True)
        leaderboard_streaks = sorted(longest_streaks.items(), key=lambda x: x[1], reverse=True)

        member_map = {}
        display_names = {}
        for uid, _ in leaderboard_counts:
            member = interaction.guild.get_member(uid) if interaction.guild else None
            if not member:
                try:
                    member = await self.bot.fetch_user(uid)
                except:
                    member = None
            member_map[uid] = member
            display_names[uid] = member.display_name if member else f"User {uid}"

        TOP_N = 10
        top_counts = [(display_names[uid], count, member_map.get(uid)) for uid, count in leaderboard_counts[:TOP_N]]
        top_streaks = [(display_names[uid], streak, member_map.get(uid)) for uid, streak in leaderboard_streaks[:TOP_N]]

        # Concurrent Avatar Fetching via aiohttp
        async def fetch_avatar(session, member):
            if not member:
                return None
            try:
                avatar_url = member.avatar.url if getattr(member, 'avatar', None) else member.display_avatar.url
                async with session.get(str(avatar_url), timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except:
                pass
            return None

        # Fetch for counts
        counts_avatars = []
        streaks_avatars = []
        async with aiohttp.ClientSession() as session:
            tasks_counts = [fetch_avatar(session, t[2]) for t in top_counts]
            tasks_streaks = [fetch_avatar(session, t[2]) for t in top_streaks]
            
            counts_avatars = await asyncio.gather(*tasks_counts)
            streaks_avatars = await asyncio.gather(*tasks_streaks)

        # Plot charts asynchronously in separate threads
        counts_path = os.path.join(os.getenv("DATA_DIR", "."), "workout_top_counts.png")
        streaks_path = os.path.join(os.getenv("DATA_DIR", "."), "workout_top_streaks.png")
        
        try:
            await asyncio.to_thread(self._render_leaderboard_counts, top_counts, counts_avatars, counts_path)
            await asyncio.to_thread(self._render_leaderboard_streaks, top_streaks, streaks_avatars, streaks_path)

            files = []
            if os.path.exists(counts_path):
                files.append(discord.File(counts_path))
            if os.path.exists(streaks_path):
                files.append(discord.File(streaks_path))

            if files:
                await interaction.followup.send(files=files)
            else:
                await interaction.followup.send("Could not generate leaderboard images.")
        finally:
            for path in [counts_path, streaks_path]:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except:
                    pass

    def _render_leaderboard_counts(self, top_counts, avatars_data, out_path):
        names = [t[0] for t in top_counts]
        counts = [t[1] for t in top_counts]
        num = len(names)

        fig_height = max(4, num * 0.6)
        fig, ax = plt.subplots(figsize=(10, fig_height))
        fig.patch.set_facecolor("#2C2F33")
        ax.set_facecolor("#2C2F33")

        bar_colors = []
        processed_avatars = []
        for idx, (name, count, member) in enumerate(top_counts):
            avatar_bytes = avatars_data[idx]
            avg_hex = "#10B981" # Sleek emerald
            avatar_img = None
            if avatar_bytes:
                try:
                    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((36, 36))
                    avatar_array = np.array(avatar)[..., :3]
                    avg_color = tuple(avatar_array.mean(axis=(0, 1)).astype(int))
                    avg_hex = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
                    mask = Image.new("L", avatar.size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                    avatar.putalpha(mask)
                    avatar_img = avatar
                except:
                    pass
            bar_colors.append(avg_hex)
            processed_avatars.append(avatar_img)

        y = np.arange(num)
        bars = ax.barh(y, counts, color=bar_colors, height=0.6, edgecolor="none")

        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12)
        ax.invert_yaxis()
        ax.set_xlabel("Workouts", color="#FFFFFF", fontsize=12)
        ax.set_title("Top Workout Totals", color="#FFFFFF", fontsize=16, pad=15)
        ax.tick_params(axis="x", colors="#FFFFFF")

        max_count = max(counts) if counts else 1
        for i, b in enumerate(bars):
            x = b.get_width()
            y_pos = b.get_y() + b.get_height() / 2
            avatar_img = processed_avatars[i]
            if avatar_img is not None:
                avatar_box = OffsetImage(avatar_img, zoom=1)
                ab = AnnotationBbox(avatar_box, (x + max_count * 0.03, y_pos), frameon=False, xycoords="data", box_alignment=(0.5, 0.5))
                ax.add_artist(ab)
                text_x = x + max_count * 0.08
            else:
                text_x = x + max_count * 0.02
            ax.text(text_x, y_pos, str(counts[i]), va="center", color="#FFFFFF", fontsize=12)

        plt.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

    def _render_leaderboard_streaks(self, top_streaks, avatars_data, out_path):
        names = [t[0] for t in top_streaks]
        streaks = [t[1] for t in top_streaks]
        num = len(names)

        fig_height = max(4, num * 0.6)
        fig, ax = plt.subplots(figsize=(10, fig_height))
        fig.patch.set_facecolor("#2C2F33")
        ax.set_facecolor("#2C2F33")

        bar_colors = []
        processed_avatars = []
        for idx, (name, streak, member) in enumerate(top_streaks):
            avatar_bytes = avatars_data[idx]
            avg_hex = "#F59E0B" # Sleek orange
            avatar_img = None
            if avatar_bytes:
                try:
                    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((36, 36))
                    avatar_array = np.array(avatar)[..., :3]
                    avg_color = tuple(avatar_array.mean(axis=(0, 1)).astype(int))
                    avg_hex = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
                    mask = Image.new("L", avatar.size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                    avatar.putalpha(mask)
                    avatar_img = avatar
                except:
                    pass
            bar_colors.append(avg_hex)
            processed_avatars.append(avatar_img)

        y = np.arange(num)
        bars = ax.barh(y, streaks, color=bar_colors, height=0.6, edgecolor="none")

        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12)
        ax.invert_yaxis()
        ax.set_xlabel("Longest Streak (weeks)", color="#FFFFFF", fontsize=12)
        ax.set_title("Top Longest Workout Streaks", color="#FFFFFF", fontsize=16, pad=15)
        ax.tick_params(axis="x", colors="#FFFFFF")

        max_count = max(streaks) if streaks else 1
        for i, b in enumerate(bars):
            x = b.get_width()
            y_pos = b.get_y() + b.get_height() / 2
            avatar_img = processed_avatars[i]
            if avatar_img is not None:
                avatar_box = OffsetImage(avatar_img, zoom=1)
                ab = AnnotationBbox(avatar_box, (x + max_count * 0.03, y_pos), frameon=False, xycoords="data", box_alignment=(0.5, 0.5))
                ax.add_artist(ab)
                text_x = x + max_count * 0.08
            else:
                text_x = x + max_count * 0.02
            ax.text(text_x, y_pos, str(streaks[i]), va="center", color="#FFFFFF", fontsize=12)

        plt.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

    @app_commands.command(name="my_workouts", description="Check how many workouts you've logged this week.")
    async def my_workouts(self, interaction: discord.Interaction):
        uid = interaction.user.id
        now = datetime.now()
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        
        all_w = await self.get_workouts(uid)
        this_week = [w for w in all_w if w >= week_start]
        total = len(all_w)
        weekly = len(this_week)
        goal = await self.get_goal(uid)
        
        streak = await self.calculate_streak(uid)
        streak_msg = f" You're on a **{streak} week streak!**" if streak > 0 else ""
        await interaction.response.send_message(
            f"You've logged **{weekly} workouts** this week and **{total} total**! (Goal: {goal}).{streak_msg}", 
            ephemeral=True
        )

    @app_commands.command(name="test_weekly_reset", description="Test the weekly reset messages (admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_weekly_reset(self, interaction: discord.Interaction):
        await interaction.response.send_message("Testing weekly reset...", ephemeral=True)
        await self.reset_weekly_goals()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Handle DMs offline using local demeaning wisdom selector
        if message.guild is None:
            response = random.choice(DAN_DM_RESPONSES)
            await message.channel.send(response)
            return

        # Thread attachments check
        if not message.attachments or not isinstance(message.channel, discord.Thread) or message.channel.id != self.SPECIFIC_THREAD_ID:
            return
        
        goal = await self.get_goal(message.author.id)
        if goal <= 0:
            return
            
        confirm = await message.channel.send(f"{message.author.mention}, did you just post a workout image? Reply 'yes' or 'no'.")
        def check(m):
            return m.author == message.author and m.channel == message.channel and m.content.lower() in ("yes","no")
        try:
            reply = await self.bot.wait_for("message", timeout=60, check=check)
            if reply.content.lower() == "yes":
                now = datetime.now()
                # Log workout in SQLite
                async with await DatabaseManager.get_connection() as conn:
                    await conn.execute("INSERT OR IGNORE INTO workout_history (user_id, timestamp) VALUES (?, ?);", (message.author.id, now.isoformat()))
                    await conn.commit()
                
                ws = now.replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=now.weekday())
                w = await self.get_workouts(message.author.id)
                count = sum(1 for d in w if d >= ws)
                
                await message.channel.send(
                    f"Workout logged for {message.author.mention}! Total this week: {count} (Goal: {goal})."
                )
            await confirm.delete()
            await reply.delete()
        except asyncio.TimeoutError:
            try:
                await confirm.delete()
            except:
                pass

    async def schedule_weekly_reset(self):
        self.weekly_reset_time = get_next_weekly_reset()
        while True:
            try:
                now = datetime.now()
                delay = (self.weekly_reset_time - now).total_seconds()
                if delay > self.warning_threshold:
                    await asyncio.sleep(delay - self.warning_threshold)
                    await self.send_reminders()
                    await asyncio.sleep(self.warning_threshold)
                else:
                    await asyncio.sleep(delay)
                
                await self.reset_weekly_goals()
                self.weekly_reset_time = get_next_weekly_reset()
                print(f"[WorkoutTracker] Next weekly reset scheduled for: {self.weekly_reset_time}")
            except Exception as e:
                print(f"[WorkoutTracker] Error in schedule_weekly_reset: {e}")
                await asyncio.sleep(60)

    async def send_reminders(self):
        start_of_week = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=datetime.now().weekday())
        
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT user_id, goal FROM workout_goals;") as cursor:
                users = await cursor.fetchall()
                
        for user_id, goal in users:
            w = await self.get_workouts(user_id)
            weekly_count = sum(1 for d in w if d >= start_of_week)
            if weekly_count < goal:
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(
                        f"⚠️ Reminder: You haven't met your weekly workout goal of {goal} workouts. Log your workouts before the week resets!"
                    )
                    print(f"[WorkoutTracker] Reminder sent to {user_id}.")
                except discord.Forbidden:
                    print(f"[WorkoutTracker] Unable to send reminder to user {user_id}. DMs might be disabled.")

    async def reset_weekly_goals(self):
        print("[WorkoutTracker] Running reset_weekly_goals...")
        channel = self.bot.get_channel(self.leaderboard_channel)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(self.leaderboard_channel)
            except Exception as e:
                print(f"[WorkoutTracker] Leaderboard channel {self.leaderboard_channel} not found: {e}")
                return

        start_of_week = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=datetime.now().weekday())
        
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT user_id, goal FROM workout_goals;") as cursor:
                users = await cursor.fetchall()

        met = []
        missed = []
        for uid, goal in users:
            w = await self.get_workouts(uid)
            weekly_count = sum(1 for d in w if d >= start_of_week)
            if weekly_count >= goal:
                met.append((uid, goal, weekly_count))
            else:
                misses = await self.calculate_consecutive_misses(uid)
                missed.append((uid, goal, weekly_count, misses))

        # Announce who hit goals
        if met:
            msg = "🎉 **Users Who Met Their Goal** 🎉\n"
            for uid, g, c in met:
                s = await self.calculate_streak(uid)
                msg += f"**<@{uid}>**: Goal **{g}** - Logged **{c}**"
                if s:
                    msg += f" - Streak: **{s} week{'s' if s>1 else ''}**"
                msg += " ✅\n"
            await channel.send(msg[:2000])

        # Process old warnings that were NOT acknowledged within 1 week
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT user_id, message_id, timestamp FROM pending_workout_warnings;") as cursor:
                pending_warnings = await cursor.fetchall()
            
            for p_uid, p_msg_id, p_ts_str in pending_warnings:
                p_ts = datetime.fromisoformat(p_ts_str)
                if datetime.now() - p_ts > timedelta(weeks=1):
                    # Kick user out of tracker
                    await conn.execute("DELETE FROM workout_goals WHERE user_id = ?;", (p_uid,))
                    await conn.execute("DELETE FROM workout_history WHERE user_id = ?;", (p_uid,))
                    await conn.execute("DELETE FROM pending_workout_warnings WHERE user_id = ?;", (p_uid,))
                    await conn.commit()
                    
                    try:
                        # Attempt to edit button message to say they were removed
                        msg = await channel.fetch_message(p_msg_id)
                        await msg.edit(content=f"❌ **<@{p_uid}> did not acknowledge their warning in time and was removed from the tracker.** Quitting is for the weak! 😠", view=None)
                    except:
                        await channel.send(f"❌ <@{p_uid}> did not acknowledge their warning in time and was removed from the tracker.")

        # Announce failures & Create new warnings with Interactive Buttons
        for uid, g, c, misses in missed:
            dm = get_demeaning_message()
            if misses < self.miss_threshold:
                text = f"**<@{uid}>**: Goal **{g}** - Logged **{c}** ❌\n> {dm}"
                await channel.send(text[:2000])
            else:
                text = (
                    f"⚠️ **<@{uid}>**: Goal **{g}** - Logged **{c}** ❌\n"
                    f"You missed **{misses} consecutive weeks**! Acknowledge this warning below within 1 week to stay in the tracker!\n> {dm}"
                )
                # Attach Acknowledge Button View
                view = AcknowledgeWorkoutButton()
                sent = await channel.send(text[:2000], view=view)
                
                # Save pending warning in SQLite
                async with await DatabaseManager.get_connection() as conn:
                    await conn.execute(
                        "INSERT OR REPLACE INTO pending_workout_warnings (user_id, message_id, timestamp) VALUES (?, ?, ?);",
                        (uid, sent.id, datetime.now().isoformat())
                    )
                    await conn.commit()

        print("[WorkoutTracker] Weekly goals reset successfully.")

async def setup(bot):
    await bot.add_cog(WorkoutTracker(bot))
