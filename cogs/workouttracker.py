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
        # OLD JSON format: user_goals maps user_id to an integer (the weekly goal)
        self.user_goals = {}
        self.user_workouts = defaultdict(list)
        # Pending reactions: maps user_id (as a string) to {"message_id": int, "timestamp": isoformat string}
        self.pending_reactions = {}
        self.warning_threshold = 12 * 60 * 60  # 6 hours before reset (in seconds)
        self.leaderboard_channel = 1327019216510910546  # Channel where leaderboard is posted
        self.weekly_reset_time = get_next_weekly_reset()
        self.miss_threshold = 2  # Number of consecutive missed weeks to trigger reaction requirement
        self.load_data()
        bot.loop.create_task(self.schedule_weekly_reset())
        print(f"Weekly reset scheduled for: {self.weekly_reset_time}")

    def get_goal(self, user_id: int) -> int:
        """Return the workout goal for the user as an integer."""
        goal = self.user_goals.get(user_id)
        if isinstance(goal, list):
            return goal[0]
        return goal

    def calculate_streak(self, user_id: int) -> int:
        workouts = self.user_workouts.get(user_id, [])
        if user_id not in self.user_goals or self.get_goal(user_id) <= 0:
            return 0

        workouts = sorted(workouts)
        now = datetime.now()
        current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        current_week_end = current_week_start + timedelta(days=7)

        streak = 0
        current_week_count = sum(1 for workout in workouts if current_week_start <= workout < current_week_end)
        if current_week_count >= self.get_goal(user_id):
            streak += 1
            week_start = current_week_start - timedelta(days=7)
        else:
            week_start = current_week_start - timedelta(days=7)

        while True:
            week_end = week_start + timedelta(days=7)
            week_count = sum(1 for workout in workouts if week_start <= workout < week_end)
            if week_count >= self.get_goal(user_id):
                streak += 1
            else:
                break
            week_start -= timedelta(days=7)
        return streak

    def calculate_consecutive_misses(self, user_id: int) -> int:
        """
        Calculate the number of consecutive full weeks (before the current week)
        in which the user missed their goal.
        """
        if user_id not in self.user_goals or self.get_goal(user_id) <= 0:
            return 0

        workouts = sorted(self.user_workouts.get(user_id, []))
        goal = self.get_goal(user_id)
        now = datetime.now()
        current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        consecutive_misses = 0
        week_start = current_week_start - timedelta(days=7)
        while True:
            week_end = week_start + timedelta(days=7)
            week_count = sum(1 for workout in workouts if week_start <= workout < week_end)
            if week_count < goal:
                consecutive_misses += 1
            else:
                break
            week_start -= timedelta(days=7)
        return consecutive_misses

    def save_data(self):
        data = {
            "user_goals": self.user_goals,
            "user_workouts": {str(key): [dt.isoformat() for dt in value] for key, value in self.user_workouts.items()},
            "pending_reactions": self.pending_reactions
        }
        with open(self.STORAGE_FILE, "w") as f:
            json.dump(data, f)

    def load_data(self):
        if os.path.exists(self.STORAGE_FILE):
            with open(self.STORAGE_FILE, "r") as f:
                data = json.load(f)
                # Assume user_goals stored as integers or lists.
                self.user_goals = {int(key): value for key, value in data.get("user_goals", {}).items()}
                self.user_workouts = {int(key): [datetime.fromisoformat(dt).replace(tzinfo=None) for dt in value]
                                      for key, value in data.get("user_workouts", {}).items()}
                self.pending_reactions = data.get("pending_reactions", {})
        else:
            print("No storage file found. Initializing empty data.")
            self.user_goals = {}
            self.user_workouts = defaultdict(list)
            self.pending_reactions = {}
        for user_id in self.user_goals:
            if user_id not in self.user_workouts:
                print(f"Initializing missing workouts for user {user_id}.")
                self.user_workouts[user_id] = []

    def cog_unload(self):
        self.save_data()
        self.reset_task.cancel()

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
        
        if interaction.user.id not in self.user_workouts:
            self.user_workouts[interaction.user.id] = []

    @app_commands.command(name="opt_out", description="Opt out of the workout tracker.")
    async def opt_out(self, interaction: discord.Interaction):
        if interaction.user.id in self.user_goals:
            del self.user_goals[interaction.user.id]
            # DO NOT delete their workouts; we keep historical data.
            if str(interaction.user.id) in self.pending_reactions:
                del self.pending_reactions[str(interaction.user.id)]
            self.save_data()

            await interaction.response.send_message(
                "You have opted out of the workout tracker. But remember, quitting is for the weak! 😠", ephemeral=False
            )

            channel = interaction.channel
            if channel:
                await channel.send(
                    f"📢 {interaction.user.mention} has quit the workout tracker. I'm not really surprised. Are you?"
                )
        else:
            await interaction.response.send_message("You're not currently participating in the tracker.", ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the workout leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        if not self.user_goals:
            await interaction.response.send_message("No one has logged any workouts yet! Be the first to start!", ephemeral=True)
            return

        total_workouts = {user_id: len(self.user_workouts.get(user_id, [])) for user_id in self.user_goals}
        leaderboard = sorted(total_workouts.items(), key=lambda x: x[1], reverse=True)
        leaderboard_message = "**🏋️ Workout Leaderboard (All-Time) 🏋️**\n\n"

        for i, (user_id, workout_count) in enumerate(leaderboard, start=1):
            if interaction.guild:
                member = interaction.guild.get_member(user_id)
                if not member:
                    try:
                        member = await interaction.guild.fetch_member(user_id)
                    except discord.NotFound:
                        member = None
            else:
                try:
                    member = await self.bot.fetch_user(user_id)
                except Exception:
                    member = None

            if member:
                display_name = getattr(member, "display_name", None) or getattr(member, "name", None) or f"User {user_id}"
            else:
                display_name = f"Unknown User ({user_id})"

            leaderboard_message += f"{i}. {display_name}: {workout_count} workouts\n"

        await interaction.response.send_message(leaderboard_message, ephemeral=False)

    @app_commands.command(name="my_workouts", description="Check how many workouts you've logged this week.")
    async def my_workouts(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        start_of_week = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())
        user_workouts = self.user_workouts.get(user_id, [])
        weekly_workouts = [workout for workout in user_workouts if workout >= start_of_week]
        total_workouts = len(user_workouts)
        total_this_week = len(weekly_workouts)

        streak = self.calculate_streak(user_id)
        streak_message = f" You're on a **{streak} week streak!**" if streak > 0 else ""

        await interaction.response.send_message(
            f"You've logged **{total_this_week} workouts** this week and **{total_workouts} workouts** total! (Goal: {self.get_goal(user_id)} workouts).{streak_message} Keep it up! 🏋️",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

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
                reply = response.choices[0].message.content
            except Exception as e:
                print(f"Error generating DM reply: {e}")
                reply = "Sorry, I encountered an error processing your request."
            await message.channel.send(reply)
            return

        if message.author.bot or not message.attachments:
            return

        if not isinstance(message.channel, discord.Thread) or message.channel.id != self.SPECIFIC_THREAD_ID:
            print(f"Wrong thread: {message.channel.id}")
            return

        if message.author.id not in self.user_goals:
            print(f"User {message.author.id} is not opted into the workout tracker.")
            return

        if message.author.id not in self.user_workouts:
            print(f"Initializing workout list for user {message.author.id}.")
            self.user_workouts[message.author.id] = []

        confirmation_message = await message.channel.send(
            f"{message.author.mention}, did you just post a workout image? Reply with 'yes' or 'no'."
        )

        def check(reply):
            return (
                reply.channel == message.channel
                and reply.author == message.author
                and reply.content.lower() in ['yes', 'no']
            )

        try:
            reply = await self.bot.wait_for('message', timeout=60.0, check=check)
            if reply.content.lower() == 'yes':
                current_time = datetime.now()
                self.user_workouts[message.author.id].append(current_time)
                start_of_week = current_time.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current_time.weekday())
                weekly_workouts = [workout for workout in self.user_workouts[message.author.id] if workout >= start_of_week]
                total_workouts_this_week = len(weekly_workouts)
                await message.channel.send(
                    f"Workout logged for {message.author.mention}! Total workouts this week: {total_workouts_this_week} (Goal: {self.get_goal(message.author.id)} workouts)."
                )
                print(f"Workout logged: {current_time}")
            await confirmation_message.delete()
            await reply.delete()
        except asyncio.TimeoutError:
            await confirmation_message.delete()

    async def schedule_weekly_reset(self):
        self.weekly_reset_time = get_next_weekly_reset()

        while True:
            try:
                now = datetime.now()
                time_until_reset = (self.weekly_reset_time - now).total_seconds()

                if time_until_reset > self.warning_threshold:
                    await asyncio.sleep(time_until_reset - self.warning_threshold)
                    await self.send_reminders()
                    remaining_time = (self.weekly_reset_time - datetime.now()).total_seconds()
                    await asyncio.sleep(remaining_time)
                else:
                    await asyncio.sleep(time_until_reset)
                await self.reset_weekly_goals()

                self.weekly_reset_time = get_next_weekly_reset()
                print(f"Next weekly reset scheduled for: {self.weekly_reset_time}")
            except Exception as e:
                print(f"Error in schedule_weekly_reset: {e}")
                await asyncio.sleep(60)
    
    async def send_reminders(self):
        start_of_week = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())

        for user_id, goal in self.user_goals.items():
            if user_id not in self.user_workouts:
                self.user_workouts[user_id] = []
            weekly_workouts = [workout for workout in self.user_workouts[user_id] if workout >= start_of_week]
            if len(weekly_workouts) < goal:
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

        start_of_week = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())
        print(f"Start of week calculated as: {start_of_week}")

        met_goal = []
        did_not_meet_goal = []

        for user_id, goal in self.user_goals.items():
            if user_id not in self.user_workouts:
                self.user_workouts[user_id] = []
            weekly_workouts = [workout for workout in self.user_workouts[user_id] if workout >= start_of_week]
            weekly_count = len(weekly_workouts)
            print(f"User {user_id}: Goal = {goal}, Workouts Logged = {weekly_count}")

            if weekly_count >= goal:
                met_goal.append((user_id, goal, weekly_count))
            else:
                consecutive_misses = self.calculate_consecutive_misses(user_id)
                did_not_meet_goal.append((user_id, goal, weekly_count, consecutive_misses))

        if met_goal:
            leaderboard_message = "🎉 **Users Who Met Their Goal** 🎉\n"
            for user_id, goal, count in met_goal:
                streak = self.calculate_streak(user_id)
                leaderboard_message += f"**<@{user_id}>**: Goal **{goal}** - Logged **{count} workouts**"
                if streak > 0:
                    leaderboard_message += f" - Streak: **{streak} week{'s' if streak != 1 else ''}**"
                leaderboard_message += " ✅\n"
            leaderboard_message += "\n"
            await channel.send(leaderboard_message[:2000])

        # Process pending reactions from previous resets.
        for user_id_str in list(self.pending_reactions.keys()):
            uid = int(user_id_str)
            pending = self.pending_reactions[user_id_str]
            try:
                pending_msg = await channel.fetch_message(pending["message_id"])
                reacted = False
                for reaction in pending_msg.reactions:
                    if str(reaction.emoji) == "👍":
                        users = await reaction.users().flatten()
                        if any(u.id == uid for u in users):
                            reacted = True
                            break
                if reacted:
                    await channel.send(f"<@{uid}> acknowledged the reminder and remains in the tracker.")
                    del self.pending_reactions[user_id_str]
                else:
                    pending_time = datetime.fromisoformat(pending["timestamp"])
                    if datetime.now() - pending_time > timedelta(weeks=1):
                        await channel.send(f"<@{uid}> did not acknowledge the reminder and has been removed from tracking.")
                        if uid in self.user_goals:
                            del self.user_goals[uid]
                        # Do not delete their workout logs.
                        del self.pending_reactions[user_id_str]
            except Exception as e:
                print(f"Error checking pending reaction for user {uid}: {e}")
                del self.pending_reactions[user_id_str]

        # Process new failures.
        for user_id, goal, count, misses in did_not_meet_goal:
            if misses < self.miss_threshold:
                demeaning_message = generate_demeaning_message(misses)
                fail_message = (
                    f"👎 **You Did Not Meet Your Goal** 👎\n"
                    f"**<@{user_id}>**: Goal **{goal}** - Logged **{count} workouts** ❌\n"
                    f"> {demeaning_message}"
                )
                await channel.send(fail_message[:2000])
            else:
                demeaning_message = generate_demeaning_message(misses)
                fail_message = (
                    f"👎 **You Did Not Meet Your Goal for {misses} consecutive week{'s' if misses != 1 else ''}** 👎\n"
                    f"**<@{user_id}>**: Goal **{goal}** - Logged **{count} workouts** ❌\n"
                    f"> {demeaning_message}\n"
                    f"Please react with 👍 within 1 week to acknowledge and remain in the tracker. Otherwise, you will be removed from tracking."
                )
                sent_message = await channel.send(fail_message[:2000])
                self.pending_reactions[str(user_id)] = {
                    "message_id": sent_message.id,
                    "timestamp": datetime.now().isoformat()
                }

        self.save_data()
        print("Weekly goals reset and data saved!")

async def setup(bot):
    await bot.add_cog(WorkoutTracker(bot))
