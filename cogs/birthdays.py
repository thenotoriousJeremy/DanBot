import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import sqlite3


class BirthdayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.birthday_check_time = "09:00"  # Set the time for the daily check (24-hour format: HH:MM)
        self.conn = sqlite3.connect('birthdays.db')
        self.create_table()
        self.birthday_reminder.start()

    def create_table(self):
        with self.conn:
            c = self.conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS birthdays (
                user_id INTEGER,
                username TEXT,
                birthday TEXT,
                PRIMARY KEY (user_id, username)
            )''')

    @app_commands.command(name="set_birthday", description="Set a birthday for yourself or another user")
    async def set_birthday(self, interaction: discord.Interaction, target_user: discord.Member = None, date: str = None):
        """
        Save a birthday for yourself or another user. Format: MM-DD.
        """
        if target_user is None:
            target_user = interaction.user  # Default to the user who invoked the command

        if date is None:
            await interaction.response.send_message(
                "You need to provide a date in MM-DD format. Example: `/set_birthday @user 12-25`.",
                ephemeral=True,
            )
            return

        try:
            datetime.strptime(date, '%m-%d')  # Validate date format

            # Save to the database
            with self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO birthdays (user_id, username, birthday) VALUES (?, ?, ?)",
                    (target_user.id, target_user.name, date),
                )
            await interaction.response.send_message(
                f"{target_user.mention}, your birthday has been set to {date}. 🎉",  # Tag the user
                ephemeral=False,
            )
        except ValueError:
            await interaction.response.send_message(
                "Invalid date format. Please use MM-DD (e.g., 12-25).",
                ephemeral=True,
            )

    @app_commands.command(name="when_is", description="Ask when a user's birthday is")
    async def when_is(self, interaction: discord.Interaction, target_user: discord.Member):
        """
        Ask when a user's birthday is.
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT birthday FROM birthdays WHERE user_id = ?", (target_user.id,))
            result = cursor.fetchone()

        if result:
            await interaction.response.send_message(
                f"{target_user.mention}'s birthday is on {result[0]}. 🎂",  # Tag the target user
                ephemeral=False,
            )
        else:
            await interaction.response.send_message(
                f"I don't have a birthday saved for {target_user.mention}. 😔",
                ephemeral=False,
            )
    
    @app_commands.command(name="list_birthdays", description="List all known birthdays")
    async def list_birthdays(self, interaction: discord.Interaction):
        """
        List all saved birthdays in the database.
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT username, birthday FROM birthdays ORDER BY birthday")
            birthdays = cursor.fetchall()

        if birthdays:
            birthday_list = "\n".join(
                [f"🎂 **{username}**: {birthday}" for username, birthday in birthdays]
            )
            await interaction.response.send_message(
                f"Here are all the birthdays I know:\n{birthday_list}", ephemeral=False
            )
        else:
            await interaction.response.send_message(
                "I don't have any birthdays saved yet. 😔", ephemeral=False
            )


    @tasks.loop(hours=24)
    async def birthday_reminder(self):
        today = datetime.now().strftime('%m-%d')
        next_week = (datetime.now() + timedelta(days=7)).strftime('%m-%d')
        channel = discord.utils.get(self.bot.get_all_channels(), name='dpca-irl')  # Replace 'dpca-irl' with your channel name

        if not channel:
            return

        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT user_id, username, birthday FROM birthdays")
            birthdays = cursor.fetchall()

            for user_id, username, birthday in birthdays:
                user_mention = f"<@{user_id}>"
                if birthday == next_week:
                    await channel.send(f"🎉 Heads up! {user_mention}'s birthday is coming up in a week!")
                elif birthday == today:
                    await channel.send(f"🎂 Happy Birthday, {user_mention}! 🎉")

    @birthday_reminder.before_loop
    async def before_birthday_reminder(self):
        await self.bot.wait_until_ready()

        # Calculate the delay until the specified time
        now = datetime.now()
        target_time = datetime.strptime(self.birthday_check_time, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        if now > target_time:
            # If the target time today has already passed, set it for tomorrow
            target_time += timedelta(days=1)

        delay = (target_time - now).total_seconds()
        print(f"Waiting {delay} seconds to start the birthday reminder.")
        await asyncio.sleep(delay)

async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
