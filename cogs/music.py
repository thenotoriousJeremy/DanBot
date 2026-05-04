import asyncio
import os
import shutil
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

BASE_DIR = Path(__file__).resolve().parent.parent
COOKIE_FILE = Path(os.getenv("YTDLP_COOKIE_FILE", Path(os.getenv("DATA_DIR", BASE_DIR)) / "cookies.txt"))
FFMPEG_EXECUTABLE = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg") or (str(BASE_DIR / "ffmpeg.exe") if os.name == 'nt' else "ffmpeg")
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

if COOKIE_FILE.exists():
    ytdl_format_options['cookies'] = str(COOKIE_FILE)

ffmpeg_options = {
    'options': '-vn -f s16le -acodec pcm_s16le',
    'before_options': '-protocol_whitelist file,http,https,tcp,tls,crypto -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.FFmpegPCMAudio):
    def __init__(self, source, *, data):
        super().__init__(source, executable=FFMPEG_EXECUTABLE, **ffmpeg_options)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def create_source(cls, query, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        
        # we do NOT want to download the file, just stream
        def fetch_data():
            try:
                # `extract_info` returns a dict with 'entries' for a search or playlist
                data = ytdl.extract_info(f"ytsearch:{query}" if not query.startswith('http') else query, download=False)
                if 'entries' in data:
                    return data['entries'][0]
                return data
            except Exception as e:
                print(f"[Music] Error fetching data for {query}: {e}")
                return None
                
        data = await loop.run_in_executor(None, fetch_data)
        
        if not data:
            raise ValueError(f"Could not find any results for: {query}")
            
        filename = data['url']
        return cls(filename, data=data)

    @classmethod
    async def get_metadata(cls, query, *, loop=None):
        """Fetch metadata without creating an FFmpeg process."""
        loop = loop or asyncio.get_running_loop()
        
        def fetch_data():
            try:
                data = ytdl.extract_info(f"ytsearch:{query}" if not query.startswith('http') else query, download=False)
                if 'entries' in data:
                    return data['entries'][0]
                return data
            except Exception as e:
                print(f"[Music] Error fetching data for {query}: {e}")
                return None
                
        data = await loop.run_in_executor(None, fetch_data)
        
        if not data:
            raise ValueError(f"Could not find any results for: {query}")
            
        return data

class YouTubeMusic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Mapping guild_id -> list of queries (dicts with original_query and title)
        self.music_queues = {}

    async def ensure_voice(self, interaction: discord.Interaction):
        if interaction.guild is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("Music commands must be used in a server.", ephemeral=True)
            return None
            
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("You are not in a voice channel!", ephemeral=True)
            return None

        try:
            if interaction.guild.voice_client is None:
                return await interaction.user.voice.channel.connect(
                    timeout=30.0,
                    reconnect=True,
                    self_deaf=False,
                    self_mute=False,
                )

            if interaction.guild.voice_client.channel != interaction.user.voice.channel:
                await interaction.guild.voice_client.move_to(interaction.user.voice.channel)

            return interaction.guild.voice_client
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"An error occurred while connecting to voice: {e}", ephemeral=True
                )
            return None

    def _play_next_sync(self, error, guild_id, channel_id):
        if error:
            print(f"[Music] Player error: {error}")
        self.bot.loop.call_soon_threadsafe(
            asyncio.create_task,
            self.play_next(guild_id, channel_id),
        )

    async def play_next(self, guild_id: int, channel_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        vc = guild.voice_client
        if not vc:
            return

        queue = self.music_queues.get(guild_id, [])
        if not queue:
            return

        # Pop the query/metadata from the queue
        next_item = queue.pop(0)
        query = next_item.get('original_query')
        
        channel = guild.get_channel(channel_id)

        try:
            player = await YTDLSource.create_source(query)
            
            vc.play(
                player,
                after=lambda e: self._play_next_sync(e, guild_id, channel_id)
            )

            if channel:
                await channel.send(f"Now playing: **{player.title}**")
        except Exception as e:
            if channel:
                await channel.send(f"Failed to play the next song: {e}")
            # Try to play the next one
            await self.play_next(guild_id, channel_id)

    @app_commands.command(name="join", description="Joins your current voice channel.")
    async def join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        vc = await self.ensure_voice(interaction)
        if vc:
            await interaction.followup.send(f"Joined {vc.channel.mention}", ephemeral=True)

    @app_commands.command(name="play", description="Plays audio from a YouTube URL or search query. Adds to queue if something is already playing.")
    async def play(self, interaction: discord.Interaction, query: str):
        # Respond immediately to avoid 3-second interaction timeout
        await interaction.response.defer(ephemeral=True)
        
        vc = await self.ensure_voice(interaction)
        if not vc:
            return

        # Fetch metadata just to confirm it's valid and to get the title for queueing
        try:
            metadata = await YTDLSource.get_metadata(query)
            title = metadata.get('title', 'Unknown Title')
        except Exception as e:
            await interaction.followup.send(f"An error occurred while processing the query: {e}")
            return

        queue_item = {
            'original_query': metadata.get('webpage_url', query),
            'title': title
        }

        if vc.is_playing() or vc.is_paused():
            queue = self.music_queues.setdefault(interaction.guild.id, [])
            queue.append(queue_item)
            await interaction.followup.send(f"Added to queue: **{title}**")
        else:
            await interaction.followup.send(f"Starting playback for: **{title}**")
            
            try:
                player = await YTDLSource.create_source(queue_item['original_query'])
                vc.play(
                    player,
                    after=lambda e: self._play_next_sync(e, interaction.guild.id, interaction.channel.id)
                )
                await interaction.channel.send(f"Now playing: **{player.title}**")
            except Exception as e:
                await interaction.channel.send(f"Failed to play {title}: {e}")

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return

        vc.stop()
        await interaction.response.send_message("Skipped current song.", ephemeral=True)

    @app_commands.command(name="queue", description="Displays the current song queue.")
    async def queue(self, interaction: discord.Interaction):
        queue = self.music_queues.get(interaction.guild.id, [])
        if not queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return

        message = "\n".join(f"{i+1}. {item.get('title')}" for i, item in enumerate(queue))
        await interaction.response.send_message(f"**Queue:**\n{message}")

    @app_commands.command(name="stop", description="Stops playback and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self.music_queues[interaction.guild.id] = []
            vc.stop()
            await interaction.response.send_message("Playback stopped and queue cleared.", ephemeral=True)
        else:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)

    @app_commands.command(name="leave", description="Leaves the current voice channel.")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            self.music_queues.pop(interaction.guild.id, None)
            await interaction.response.send_message("Left the voice channel.", ephemeral=True)
        else:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeMusic(bot))
