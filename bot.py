import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents and bot setup
intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True

# Provide a placeholder for `command_prefix`
bot = commands.Bot(command_prefix="!", intents=intents)  # "!" is a placeholder

@bot.event
async def on_ready():
    for guild in bot.guilds:
        print(f"Fetching members for guild: {guild.name}")
        async for member in guild.fetch_members(limit=None):
            # This will fetch and cache all members
            pass
    print(f"Logged in as {bot.user}")
    #channel = bot.get_channel(1327019216510910546)
    #if channel:
    #     await channel.send("https://c.tenor.com/OjplKC2PXmQAAAAC/tenor.gif")  # Bender saying "I'm back, baby!"

    # Load the BirthdayCog extension
    await bot.load_extension("cogs.birthdays")
    print("Birthday cog loaded!")
    # Load the Discord Wrapped extension
    await bot.load_extension("cogs.server_wrapped")
    print("Server Wrapped cog loaded!")
    # Load the Discord Wrapped extension
    await bot.load_extension("cogs.fishspeech")
    print("Fish Speech cog loaded!")
    await bot.load_extension("cogs.workouttracker")
    print("WorkoutTracker cog loaded!")
    await bot.load_extension("cogs.connectionchart")
    print("Connection Chart cog loaded!")

    # Sync slash commands globally
    try:
        await bot.tree.sync()
        print("Slash commands synced globally!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    for command in bot.tree.get_commands():
        command.dm_permission = True
    print("All commands set to work in DMs!")

# Run the bot
bot.run(TOKEN)
