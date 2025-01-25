import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict
import json
import os
from datetime import timedelta
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")

if OPENAI_TOKEN:
    client = OpenAI(api_key=OPENAI_TOKEN)

def generate_demeaning_message():
    if not OPENAI_TOKEN:
        return (
            "Honestly, you set this goal for yourself, and you couldn't even stick to it for a single week. "
            "That's just sad. Do better next time. 😒"
        )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use the updated model for generating messages
            messages=[
                {"role": "system", "content": "You are a brutally honest and mean assistant."},
                {"role": "user", "content": "Generate a mean/demeaning message for people who failed to meet their own workout goals for the week. Keep it unique, somber, insulting and brutally honest. No Exclamation marks"}
            ],
        )
        message = response.choices[0].message.content
        print(f"Generated demeaning message: {message}")  # Print the message to the terminal
        return message
    except Exception as e:
        print(f"Error generating message: {e}")
        return (
            "Honestly, you set this goal for yourself, and you couldn't even stick to it for a single week. "
            "That's just sad. Do better next time. 😒"
        )

generate_demeaning_message()

class WorkoutTracker(commands.Cog):
    STORAGE_FILE = "workout_data.json"
    SPECIFIC_THREAD_ID = 1327019216510910546  # Replace with your thread ID

    def __init__(self, bot):
        self.bot = bot
        self.user_goals = {}
        self.user_workouts = defaultdict(list)
        self.warning_threshold = 12 * 60 * 60  # 6 hours before reset
        self.leaderboard_channel = 1115982069550559322  # Channel where leaderboard is posted
        self.weekly_reset_time = datetime.now().replace(hour=22, minute=59, second=59) + timedelta(days=(6 - datetime.now().weekday()))
        self.load_data()
        bot.loop.create_task(self.schedule_weekly_reset())
        print(f"Weekly reset scheduled for: {self.weekly_reset_time}")

    def save_data(self):
        """Save user goals and workouts to a file."""
        data = {
            "user_goals": self.user_goals,
            "user_workouts": {key: [dt.isoformat() for dt in value] for key, value in self.user_workouts.items()}
        }
        with open(self.STORAGE_FILE, "w") as f:
            json.dump(data, f)

    def load_data(self):
        """Load user goals and workouts from a file."""
        if os.path.exists(self.STORAGE_FILE):
            with open(self.STORAGE_FILE, "r") as f:
                data = json.load(f)
                self.user_goals = {int(key): value for key, value in data.get("user_goals", {}).items()}
                self.user_workouts = {int(key): [datetime.fromisoformat(dt).replace(tzinfo=None) for dt in value] for key, value in data.get("user_workouts", {}).items()}
            print(f"Loaded user goals: {self.user_goals}")
            print(f"Loaded user workouts: {self.user_workouts}")
        else:
            print("No storage file found. Initializing empty data.")
            self.user_goals = {}
            self.user_workouts = defaultdict(list)
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

        self.user_goals[interaction.user.id] = (goal_per_week, self.user_goals.get(interaction.user.id, (0, 0))[1])
        self.save_data()

        await interaction.response.send_message(f"Your weekly workout goal is set to {goal_per_week} workouts! Let's get moving!", ephemeral=True)

        channel = interaction.channel
        if channel:
            await channel.send(f"📢 {interaction.user.mention} has joined the workout tracker with a goal of {goal_per_week} workouts per week!")
        
        self.user_workouts[interaction.user.id] = self.user_workouts.get(interaction.user.id, [])


    @app_commands.command(name="opt_out", description="Opt out of the workout tracker.")
    async def opt_out(self, interaction: discord.Interaction):
        if interaction.user.id in self.user_goals:
            del self.user_goals[interaction.user.id]
            del self.user_workouts[interaction.user.id]
            self.save_data()

            await interaction.response.send_message(
                "You have opted out of the workout tracker. But remember, quitting is for the weak! 😠", ephemeral=False
            )

            channel = interaction.channel
            if channel:
                await channel.send(f"📢 {interaction.user.mention} has quit the workout tracker. Shame! 😡")
        else:
            await interaction.response.send_message("You're not currently participating in the tracker.", ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the workout leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        if not self.user_goals:
            await interaction.response.send_message("No one has logged any workouts yet! Be the first to start!", ephemeral=True)
            return

        # Calculate total workouts for all time
        total_workouts = {
            user_id: len(self.user_workouts.get(user_id, [])) for user_id in self.user_goals
        }

        # Sort users by total workouts
        leaderboard = sorted(total_workouts.items(), key=lambda x: x[1], reverse=True)

        # Build the leaderboard message
        leaderboard_message = "**🏋️ Workout Leaderboard (All-Time) 🏋️**\n\n"
        for i, (user_id, workout_count) in enumerate(leaderboard, start=1):
            member = interaction.guild.get_member(user_id)
            if not member:
                # Fetch the member if not cached
                try:
                    member = await interaction.guild.fetch_member(user_id)
                except discord.NotFound:
                    member = None

            if member:
                display_name = member.display_name  # Use the display name (nickname or username fallback)
            else:
                display_name = f"Unknown User ({user_id})"  # Handle cases where the user can't be fetched
            leaderboard_message += f"{i}. {display_name}: {workout_count} workouts\n"

        # Send the leaderboard
        await interaction.response.send_message(leaderboard_message, ephemeral=False)

    @app_commands.command(name="my_workouts", description="Check how many workouts you've logged this week.")
    async def my_workouts(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        start_of_week = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())
        print(f"Start of week: {start_of_week}")

        user_workouts = self.user_workouts.get(user_id, [])
        print(f"User workouts (raw): {user_workouts}")

        weekly_workouts = [workout for workout in user_workouts if workout >= start_of_week]
        print(f"Weekly workouts: {weekly_workouts}")

        total_workouts = len(user_workouts)
        total_this_week = len(weekly_workouts)
        await interaction.response.send_message(
            f"You've logged **{total_this_week} workouts** this week and **{total_workouts} workouts** total! Keep it up! 🏋️",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.attachments:
            return

        # Ensure the message is from the specific thread
        if not isinstance(message.channel, discord.Thread) or message.channel.id != self.SPECIFIC_THREAD_ID:
            print(f"Wrong thread: {message.channel.id}")
            return

        # Check if the user is opted into the tracker
        if message.author.id not in self.user_goals:
            print(f"User {message.author.id} is not opted into the workout tracker.")
            return

        # Ensure the user's workout list is initialized
        if message.author.id not in self.user_workouts:
            print(f"Initializing workout list for user {message.author.id}.")
            self.user_workouts[message.author.id] = []

        # Ask the user if this is a workout image in the thread
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
                # Ensure the workout list is initialized
                if message.author.id not in self.user_workouts:
                    self.user_workouts[message.author.id] = []

                # Log workout with time
                current_time = datetime.now()
                self.user_workouts[message.author.id].append(current_time)

                # Calculate start of the week in UTC
                start_of_week = current_time.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current_time.weekday())
                weekly_workouts = [
                    workout for workout in self.user_workouts[message.author.id] if workout >= start_of_week
                ]
                total_workouts_this_week = len(weekly_workouts)

                # Update user goals without overwriting unrelated data
                self.user_goals[message.author.id] = (
                    self.user_goals[message.author.id][0],  # Keep the weekly goal
                    total_workouts_this_week               # Update only the workouts count
                )

                # Save the data and log publicly
                self.save_data()
                await message.channel.send(
                    f"Workout logged for {message.author.mention}! Total workouts this week: {total_workouts_this_week}."
                )

                # Debugging
                print(f"Workout logged: {current_time}")
                print(f"Start of week: {start_of_week}")
                print(f"Weekly workouts: {weekly_workouts}")

            # Delete the confirmation exchange regardless of the response
            await confirmation_message.delete()
            await reply.delete()

        except asyncio.TimeoutError:
            # Delete the confirmation message if there's no response
            await confirmation_message.delete()


    async def schedule_weekly_reset(self):
        while True:
            now = datetime.now()
            time_until_reset = (self.weekly_reset_time - now).total_seconds()

            # Schedule reminders 6 hours before reset
            if time_until_reset > self.warning_threshold:
                await asyncio.sleep(time_until_reset - self.warning_threshold)
                await self.send_reminders()

            # Schedule the weekly reset
            await asyncio.sleep(time_until_reset)
            await self.reset_weekly_goals()
            self.weekly_reset_time += timedelta(weeks=1)  # Schedule for next week

    async def send_reminders(self):
        start_of_week = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())

        for user_id, (goal_per_week, _) in self.user_goals.items():
            if user_id not in self.user_workouts:
                self.user_workouts[user_id] = []

            # Filter weekly workouts
            weekly_workouts = [workout for workout in self.user_workouts[user_id] if workout >= start_of_week]

            if len(weekly_workouts) < goal_per_week:
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(
                        f"⚠️ Reminder: You haven't met your weekly workout goal of {goal_per_week} workouts. Log your workouts before the week resets!"
                    )
                except discord.Forbidden:
                    print(f"Unable to send reminder to user {user_id}. DMs might be disabled.")

    async def reset_weekly_goals(self):
        channel = self.bot.get_channel(self.leaderboard_channel)
        if not channel:
            print(f"Leaderboard channel {self.leaderboard_channel} not found!")
            return

        start_of_week = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())

        # Separate users into groups based on whether they met their goal
        met_goal = []
        did_not_meet_goal = []

        for user_id, (goal_per_week, _) in self.user_goals.items():
            # Ensure the user's workout list is initialized
            if user_id not in self.user_workouts:
                self.user_workouts[user_id] = []

            # Filter weekly workouts (non-destructive)
            weekly_workouts = [workout for workout in self.user_workouts[user_id] if workout >= start_of_week]
            weekly_count = len(weekly_workouts)

            if weekly_count >= goal_per_week:
                met_goal.append((user_id, goal_per_week, weekly_count))
            else:
                did_not_meet_goal.append((user_id, goal_per_week, weekly_count))

        # Construct the leaderboard message
        leaderboard_message = "📅 **Weekly Leaderboard Reset** 📅\n\n"

        # Add users who met their goal
        if met_goal:
            leaderboard_message += "🎉 **Users Who Met Their Goal** 🎉\n"
            for user_id, goal, count in met_goal:
                leaderboard_message += f"**<@{user_id}>**: Goal **{goal}** - Logged **{count} workouts** ✅\n"
            leaderboard_message += "\n"

        # Add users who did not meet their goal
        if did_not_meet_goal:
            leaderboard_message += "👎 **Users Who Did Not Meet Their Goal** 👎\n"
            for user_id, goal, count in did_not_meet_goal:
                demeaning_message = generate_demeaning_message()
                leaderboard_message += (
                    f"**<@{user_id}>**: Goal **{goal}** - Logged **{count} workouts** ❌\n"
                    f"> {demeaning_message}\n"
                )

        # Save updated data to ensure consistency
        self.save_data()

        # Send the consolidated leaderboard message
        await channel.send(leaderboard_message)

async def setup(bot):
    await bot.add_cog(WorkoutTracker(bot))
