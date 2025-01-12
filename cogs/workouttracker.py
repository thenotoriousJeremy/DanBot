import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict
import json
import os
from datetime import timedelta

class WorkoutTracker(commands.Cog):
    STORAGE_FILE = "workout_data.json"
    SPECIFIC_THREAD_ID = 1327019216510910546  # Replace with your thread ID

    def __init__(self, bot):
        self.bot = bot
        self.user_goals = {}
        self.user_workouts = defaultdict(list)
        self.warning_threshold = 6 * 60 * 60  # 6 hours before reset
        self.leaderboard_channel = 1115982069550559322  # Channel where leaderboard is posted
        self.weekly_reset_time = datetime.now().replace(hour=22, minute=59, second=59) + timedelta(days=(6 - datetime.now().weekday()))
        self.load_data()
        self.reset_task.start()
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
                self.user_workouts = {int(key): [datetime.fromisoformat(dt) for dt in value] for key, value in data.get("user_workouts", {}).items()}
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

    @app_commands.command(name="leaderboard", description="View the current workout leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        if not self.user_goals:
            await interaction.response.send_message("No one has logged any workouts yet! Be the first to start!", ephemeral=True)
            return

        leaderboard = sorted(self.user_goals.items(), key=lambda x: x[1][1], reverse=True)
        leaderboard_message = "**🏋️ Workout Leaderboard 🏋️**\n\n"
        for i, (user_id, (_, total_workouts)) in enumerate(leaderboard, start=1):
            user = await self.bot.fetch_user(user_id)
            leaderboard_message += f"{i}. {user.display_name}: {total_workouts} workouts\n"

        await interaction.response.send_message(leaderboard_message, ephemeral=False)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.attachments:
            return

        # Ensure the message is from the specific thread
        if not isinstance(message.channel, discord.Thread) or message.channel.id != self.SPECIFIC_THREAD_ID:
            print(f"1")
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
                self.user_workouts[message.author.id].append(datetime.now())
                # Get the start of the current week (Monday at 00:00)
                start_of_week = datetime.now() - timedelta(days=datetime.now().weekday())
                weekly_workouts = [
                    workout for workout in self.user_workouts[message.author.id] if workout >= start_of_week
                ]
                total_workouts_this_week = len(weekly_workouts)
                self.user_goals[message.author.id] = (self.user_goals[message.author.id][0], total_workouts_this_week)
                self.save_data()
                # Log publicly in the thread
                await message.channel.send(f"Workout logged for {message.author.mention}! Total workouts this week: {total_workouts_this_week}.")
            # Delete the confirmation exchange regardless of the response
            await confirmation_message.delete()
            await reply.delete()
        except asyncio.TimeoutError:
            # Delete the confirmation message if there's no response
            await confirmation_message.delete()

    @tasks.loop(seconds=60)
    async def reset_task(self):
        now = datetime.now()
        if now >= self.weekly_reset_time:
            await self.reset_weekly_goals()
            self.weekly_reset_time += timedelta(weeks=1)

        for user_id, (goal_per_week, total_workouts) in self.user_goals.items():
            # Ensure the user's workout list is initialized
            if user_id not in self.user_workouts:
                print(f"User {user_id} missing in user_workouts. Initializing.")
                self.user_workouts[user_id] = []

            if now >= self.weekly_reset_time - timedelta(seconds=self.warning_threshold):
                if len(self.user_workouts[user_id]) < goal_per_week:
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

        start_of_week = datetime.now() - timedelta(days=datetime.now().weekday())
        leaderboard_message = "📅 **Weekly Leaderboard Reset** 📅\n\n"

        for user_id, (goal_per_week, _) in self.user_goals.items():
            # Ensure the user's workout list is initialized
            if user_id not in self.user_workouts:
                self.user_workouts[user_id] = []

            # Filter weekly workouts (non-destructive)
            weekly_workouts = [workout for workout in self.user_workouts[user_id] if workout >= start_of_week]
            weekly_count = len(weekly_workouts)

            if weekly_count >= goal_per_week:
                leaderboard_message += f"🎉 **<@{user_id}>** met their weekly goal of **{goal_per_week} workouts** with **{weekly_count} logged**! 🎉\n"
            else:
                leaderboard_message += f"👎 **<@{user_id}>** did not meet their goal of **{goal_per_week} workouts** with only **{weekly_count} logged**. 👎\n"

        # Save updated data
        self.save_data()

        # Send the consolidated leaderboard message
        await channel.send(leaderboard_message)


    @reset_task.before_loop
    async def before_reset_task(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(WorkoutTracker(bot))
