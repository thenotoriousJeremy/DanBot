import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents and bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

# Provide a placeholder for `command_prefix`
bot = commands.Bot(command_prefix="!", intents=intents)  # "!" is a placeholder

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Load the BirthdayCog extension
    await bot.load_extension("cogs.birthdays")
    print("Birthday cog loaded!")
    # Load the Discord Wrapped extension
    await bot.load_extension("cogs.server_wrapped")
    print("Server Wrapped cog loaded!")
    # Load the Discord Wrapped extension
    await bot.load_extension("cogs.fishspeech")
    print("Fish Speech cog loaded!")

    # Sync slash commands globally
    try:
        await bot.tree.sync()
        print("Slash commands synced globally!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Run the bot
bot.run(TOKEN)
