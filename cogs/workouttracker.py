import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")

if OPENAI_TOKEN:
    client = OpenAI(api_key=OPENAI_TOKEN)

def generate_demeaning_message(missed_weeks: int):
    """
    Generate a short, brutally honest message in one or two sentences for someone
    who has missed their workout goals for the given number of consecutive weeks.
    """
    if not OPENAI_TOKEN:
        return f"Missed your workouts for {missed_weeks} consecutive weeks. Get it together."
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "developer", "content": "You are a brutally honest and mean friend named Dan."},
                {"role": "user", "content": (
                    f"Generate a short, brutally honest message in one or two sentences for someone who has missed "
                    f"their workout goals for {missed_weeks} consecutive week{'s' if missed_weeks != 1 else ''}. "
                    "Keep it succinct and mean."
                )}
            ],
            temperature=1.5,
        )
        message = response.choices[0].message.content.strip()
        print(f"Generated demeaning message: {message}")
        return message
    except Exception as e:
        print(f"Error generating message: {e}")
        return f"Missed your workouts for {missed_weeks} consecutive weeks. Get it together."

def get_next_weekly_reset():
    now = datetime.now()
    days_until_sunday = (6 - now.weekday()) % 7
    next_reset = now.replace(hour=22, minute=59, second=59, microsecond=0) + timedelta(days=days_until_sunday)
    if next_reset < now:
        next_reset += timedelta(weeks=1)
    return next_reset

class WorkoutTracker(commands.Cog):
    STORAGE_FILE = "workout_data.json"
    SPECIFIC_THREAD_ID = 1327019216510910546  # Replace with your thread ID

    def __init__(self, bot):
        self.bot = bot
        # user_goals maps user_id (int) to an integer representing the weekly goal.
        self.user_goals = {}
        # user_workouts maps user_id to a list of datetime objects.
        self.user_workouts = defaultdict(list)
        # pending_reactions maps user_id (as str) to {"message_id": int, "timestamp": isoformat str}
        self.pending_reactions = {}
        self.warning_threshold = 12 * 60 * 60  # 6 hours before reset
        self.leaderboard_channel = 1327019216510910546
        self.weekly_reset_time = get_next_weekly_reset()
        self.miss_threshold = 2  # Consecutive missed weeks before requiring reaction
        self.load_data()
        bot.loop.create_task(self.schedule_weekly_reset())
        print(f"Weekly reset scheduled for: {self.weekly_reset_time}")

    def get_goal(self, user_id: int) -> int:
        """Return the workout goal for a user as an integer."""
        goal = self.user_goals.get(user_id, 0)
        # In case we ever still had a list, take first element
        if isinstance(goal, list):
            return goal[0]
        return goal

    def calculate_streak(self, user_id: int) -> int:
        workouts = sorted(self.user_workouts.get(user_id, []))
        goal = self.get_goal(user_id)
        if goal <= 0:
            return 0

        now = datetime.now()
        # Determine current week boundaries
        current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        current_week_end = current_week_start + timedelta(days=7)

        streak = 0
        # Check this week
        current_week_count = sum(1 for w in workouts if current_week_start <= w < current_week_end)
        if current_week_count >= goal:
            streak += 1
            week_start = current_week_start - timedelta(days=7)
        else:
            week_start = current_week_start - timedelta(days=7)

        # Check previous weeks
        while True:
            week_end = week_start + timedelta(days=7)
            week_count = sum(1 for w in workouts if week_start <= w < week_end)
            if week_count >= goal:
                streak += 1
                week_start -= timedelta(days=7)
            else:
                break

        return streak

    def calculate_consecutive_misses(self, user_id: int) -> int:
        workouts = sorted(self.user_workouts.get(user_id, []))
        goal = self.get_goal(user_id)
        if goal <= 0:
            return 0

        now = datetime.now()
        current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        consecutive_misses = 0
        week_start = current_week_start - timedelta(days=7)

        while True:
            week_end = week_start + timedelta(days=7)
            week_count = sum(1 for w in workouts if week_start <= w < week_end)
            if week_count < goal:
                consecutive_misses += 1
                week_start -= timedelta(days=7)
            else:
                break

        return consecutive_misses

    def save_data(self):
        data = {
            "user_goals": self.user_goals,
            "user_workouts": {str(uid): [dt.isoformat() for dt in wlist] for uid, wlist in self.user_workouts.items()},
            "pending_reactions": self.pending_reactions
        }
        with open(self.STORAGE_FILE, "w") as f:
            json.dump(data, f)

    def load_data(self):
        if os.path.exists(self.STORAGE_FILE):
            with open(self.STORAGE_FILE, "r") as f:
                data = json.load(f)
            # Unwrap any list-valued goals so everything is an int
            self.user_goals = {
                int(uid): (val[0] if isinstance(val, list) else val)
                for uid, val in data.get("user_goals", {}).items()
            }
            # Load workouts
            self.user_workouts = defaultdict(list, {
                int(uid): [datetime.fromisoformat(dt) for dt in dt_list]
                for uid, dt_list in data.get("user_workouts", {}).items()
            })
            self.pending_reactions = data.get("pending_reactions", {})
        else:
            print("No storage file found. Initializing empty data.")
            self.user_goals = {}
            self.user_workouts = defaultdict(list)
            self.pending_reactions = {}
        # Ensure every tracked user has a workouts list
        for uid in list(self.user_goals.keys()):
            if uid not in self.user_workouts:
                self.user_workouts[uid] = []

    @app_commands.command(name="set_goal", description="Set your weekly workout goal and opt in to tracking.")
    async def set_goal(self, interaction: discord.Interaction, goal_per_week: int):
        if goal_per_week <= 0:
            await interaction.response.send_message("Your goal must be at least 1 workout per week.", ephemeral=True)
            return

        self.user_goals[interaction.user.id] = goal_per_week
        self.save_data()

        await interaction.response.send_message(
            f"Your weekly workout goal is set to {goal_per_week} workouts! Let's get moving!", ephemeral=True
        )

        channel = interaction.channel
        if channel:
            await channel.send(
                f"📢 {interaction.user.mention} has joined the workout tracker with a goal of {goal_per_week} workouts per week!"
            )
        # Initialize workout list if needed
        if interaction.user.id not in self.user_workouts:
            self.user_workouts[interaction.user.id] = []

    @app_commands.command(name="opt_out", description="Opt out of the workout tracker.")
    async def opt_out(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if uid in self.user_goals:
            del self.user_goals[uid]
            self.pending_reactions.pop(str(uid), None)
            self.save_data()

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
        if not self.user_goals:
            await interaction.response.send_message("No one has logged any workouts yet! Be the first to start!", ephemeral=True)
            return

        total_workouts = {uid: len(self.user_workouts.get(uid, [])) for uid in self.user_goals}
        leaderboard = sorted(total_workouts.items(), key=lambda x: x[1], reverse=True)
        msg = "**🏋️ Workout Leaderboard (All-Time) 🏋️**\n\n"

        for i, (uid, count) in enumerate(leaderboard, start=1):
            member = interaction.guild.get_member(uid) if interaction.guild else None
            if not member:
                try:
                    member = await self.bot.fetch_user(uid)
                except:
                    member = None
            name = member.display_name if member else f"User {uid}"
            msg += f"{i}. {name}: {count} workouts\n"

        await interaction.response.send_message(msg, ephemeral=False)

    @app_commands.command(name="my_workouts", description="Check how many workouts you've logged this week.")
    async def my_workouts(self, interaction: discord.Interaction):
        uid = interaction.user.id
        now = datetime.now()
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        all_w = self.user_workouts.get(uid, [])
        this_week = [w for w in all_w if w >= week_start]
        total = len(all_w)
        weekly = len(this_week)
        streak = self.calculate_streak(uid)
        streak_msg = f" You're on a **{streak} week streak!**" if streak > 0 else ""
        await interaction.response.send_message(
            f"You've logged **{weekly} workouts** this week and **{total} total**! (Goal: {self.get_goal(uid)}).{streak_msg}", 
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Handle DMs with mean replies
        if message.guild is None:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "developer", "content": "You are a brutally honest and mean friend named Dan."},
                        {"role": "user", "content": message.content}
                    ],
                    temperature=1.0
                )
                await message.channel.send(response.choices[0].message.content)
            except:
                await message.channel.send("Sorry, I encountered an error processing your request.")
            return

        # If this is the workout‐thread image check
        if not message.attachments or not isinstance(message.channel, discord.Thread) or message.channel.id != self.SPECIFIC_THREAD_ID:
            return
        if message.author.id not in self.user_goals:
            return
        # Ask for confirmation
        confirm = await message.channel.send(f"{message.author.mention}, did you just post a workout image? Reply 'yes' or 'no'.")
        def check(m):
            return m.author == message.author and m.channel == message.channel and m.content.lower() in ("yes","no")
        try:
            reply = await self.bot.wait_for("message", timeout=60, check=check)
            if reply.content.lower() == "yes":
                now = datetime.now()
                self.user_workouts[message.author.id].append(now)
                self.save_data()
                # Count this week’s total
                ws = now.replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=now.weekday())
                count = sum(1 for w in self.user_workouts[message.author.id] if w >= ws)
                await message.channel.send(
                    f"Workout logged for {message.author.mention}! Total this week: {count} (Goal: {self.get_goal(message.author.id)})."
                )
            await confirm.delete()
            await reply.delete()
        except asyncio.TimeoutError:
            await confirm.delete()

    async def schedule_weekly_reset(self):
        self.weekly_reset_time = get_next_weekly_reset()
        while True:
            try:
                now = datetime.now()
                delay = (self.weekly_reset_time - now).total_seconds()
                # send warning
                if delay > self.warning_threshold:
                    await asyncio.sleep(delay - self.warning_threshold)
                    await self.send_reminders()
                    await asyncio.sleep(self.warning_threshold)
                else:
                    await asyncio.sleep(delay)
                # do the reset
                await self.reset_weekly_goals()
                self.weekly_reset_time = get_next_weekly_reset()
                print(f"Next weekly reset scheduled for: {self.weekly_reset_time}")
            except Exception as e:
                print(f"Error in schedule_weekly_reset: {e}")
                await asyncio.sleep(60)

    async def send_reminders(self):
        start_of_week = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=datetime.now().weekday())
        for user_id in list(self.user_goals.keys()):
            goal = self.get_goal(user_id)
            workouts = self.user_workouts.get(user_id, [])
            weekly = [w for w in workouts if w >= start_of_week]
            if len(weekly) < goal:
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(
                        f"⚠️ Reminder: You haven't met your weekly workout goal of {goal} workouts. Log your workouts before the week resets!"
                    )
                    print(f"Reminder sent to {user_id}.")
                except discord.Forbidden:
                    print(f"Unable to send reminder to user {user_id}. DMs might be disabled.")

    async def reset_weekly_goals(self):
        print("Running reset_weekly_goals...")
        channel = self.bot.get_channel(self.leaderboard_channel)
        if not channel:
            print(f"Leaderboard channel {self.leaderboard_channel} not found!")
            return

        start_of_week = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=datetime.now().weekday())
        met, missed = [], []
        # Partition users
        for uid in list(self.user_goals.keys()):
            goal = self.get_goal(uid)
            workouts = self.user_workouts.get(uid, [])
            weekly_count = sum(1 for w in workouts if w >= start_of_week)
            if weekly_count >= goal:
                met.append((uid, goal, weekly_count))
            else:
                misses = self.calculate_consecutive_misses(uid)
                missed.append((uid, goal, weekly_count, misses))

        # Announce who hit their goals
        if met:
            msg = "🎉 **Users Who Met Their Goal** 🎉\n"
            for uid, g, c in met:
                s = self.calculate_streak(uid)
                msg += f"**<@{uid}>**: Goal **{g}** - Logged **{c}**"
                if s:
                    msg += f" - Streak: **{s} week{'s' if s>1 else ''}**"
                msg += " ✅\n"
            await channel.send(msg[:2000])

        # Process old pending reactions
        for uid_str, pend in list(self.pending_reactions.items()):
            uid = int(uid_str)
            try:
                msg = await channel.fetch_message(pend["message_id"])
                reacted = any(
                    str(r.emoji) == "👍" and any(u.id == uid for u in await r.users().flatten())
                    for r in msg.reactions
                )
                if reacted:
                    await channel.send(f"<@{uid}> acknowledged and remains in the tracker.")
                else:
                    ts = datetime.fromisoformat(pend["timestamp"])
                    if datetime.now() - ts > timedelta(weeks=1):
                        await channel.send(f"<@{uid}> did not acknowledge and has been removed.")
                        self.user_goals.pop(uid, None)
                del self.pending_reactions[uid_str]
            except Exception as e:
                print(f"Error checking pending reaction for user {uid}: {e}")
                del self.pending_reactions[uid_str]

        # Announce failures
        for uid, g, c, misses in missed:
            dm = generate_demeaning_message(misses)
            if misses < self.miss_threshold:
                text = f"**<@{uid}>**: Goal **{g}** - Logged **{c}** ❌\n> {dm}"
                await channel.send(text[:2000])
            else:
                text = (
                    f"**<@{uid}>**: Goal **{g}** - Logged **{c}** ❌\n"
                    f"You missed **{misses} consecutive week{'s' if misses>1 else ''}**\n> {dm}\n"
                    "React with 👍 within 1 week to stay in the tracker."
                )
                sent = await channel.send(text[:2000])
                self.pending_reactions[str(uid)] = {
                    "message_id": sent.id,
                    "timestamp": datetime.now().isoformat()
                }

        self.save_data()
        print("Weekly goals reset and data saved!")

async def setup(bot):
    await bot.add_cog(WorkoutTracker(bot))
