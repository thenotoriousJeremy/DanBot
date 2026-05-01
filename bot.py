import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "Missing Discord token. Set DISCORD_TOKEN or BOT_TOKEN in the environment."
    )

COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
ENABLED_COGS = os.getenv("ENABLED_COGS")

intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True


class DanBot(commands.Bot):
    async def setup_hook(self):
        await self.load_cogs()
        await self.tree.sync()
        for command in self.tree.get_commands():
            command.dm_permission = True

    async def load_cogs(self):
        cogs_path = Path(__file__).resolve().parent / "cogs"
        default_cogs = sorted(
            p.stem for p in cogs_path.glob("*.py") if p.is_file() and p.name != "__init__.py"
        )
        enabled = ENABLED_COGS.split(",") if ENABLED_COGS else default_cogs
        enabled = [c.strip() for c in enabled if c.strip()]

        for cog_name in sorted(enabled):
            if cog_name not in default_cogs:
                print(f"Skipping unknown cog: {cog_name}")
                continue
            try:
                await self.load_extension(f"cogs.{cog_name}")
                print(f"Loaded cog: {cog_name}")
            except Exception as exc:
                print(f"Failed to load cog {cog_name}: {exc}")

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})")
        print("DanBot is ready.")


bot = DanBot(command_prefix=COMMAND_PREFIX, intents=intents)

if __name__ == "__main__":
    bot.run(TOKEN)
 