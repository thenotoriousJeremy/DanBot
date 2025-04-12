import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio

# Updated yt-dlp options with default_search.
ytdl_format_options = {
    'format': 'bestaudio/best',
    'default_search': 'ytsearch',  # Automatically search YouTube if query is not a URL.
    'noplaylist': True,
    'quiet': True,
    'cookies': 'cookies.txt'
}
ffmpeg_options = {
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, executable="./ffmpeg.exe", **ffmpeg_options), data=data)

class YouTubeMusic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # This dictionary maps guild IDs to a list of YTDLSource objects (the queue)
        self.music_queues = {}

    async def ensure_voice(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("You are not in a voice channel!", ephemeral=True)
            return None
        if interaction.guild.voice_client is None:
            return await interaction.user.voice.channel.connect()
        return interaction.guild.voice_client

    async def play_next(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return
        queue = self.music_queues.get(interaction.guild.id)
        if queue and len(queue) > 0:
            next_song = queue.pop(0)
            vc.play(next_song, after=lambda e: self.bot.loop.call_soon_threadsafe(
                asyncio.create_task, self.play_next(interaction)))
            # Use the text channel to send a message (since the interaction has been responded to already)
            await interaction.channel.send(f"Now playing: **{next_song.title}**")

    @app_commands.command(name="join", description="Joins your current voice channel.")
    async def join(self, interaction: discord.Interaction):
        vc = await self.ensure_voice(interaction)
        if vc:
            await interaction.response.send_message(f"Joined {vc.channel.mention}", ephemeral=True)

    @app_commands.command(name="play", description="Plays audio from a YouTube URL or search query. Adds to queue if something is already playing.")
    async def play(self, interaction: discord.Interaction, query: str):
        vc = await self.ensure_voice(interaction)
        if not vc:
            return
        # Defer the response because processing may take time.
        await interaction.response.defer()
        try:
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred while processing the query: {e}")
            return
        if vc.is_playing() or vc.is_paused():
            queue = self.music_queues.setdefault(interaction.guild.id, [])
            queue.append(player)
            await interaction.followup.send(f"Added to queue: **{player.title}**")
        else:
            vc.play(player, after=lambda e: self.bot.loop.call_soon_threadsafe(
                asyncio.create_task, self.play_next(interaction)))
            await interaction.followup.send(f"Now playing: **{player.title}**")

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
        else:
            vc.stop()  # This will trigger play_next in the after callback.
            await interaction.response.send_message("Skipped current song.", ephemeral=True)

    @app_commands.command(name="queue", description="Displays the current song queue.")
    async def queue(self, interaction: discord.Interaction):
        queue = self.music_queues.get(interaction.guild.id, [])
        if not queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
        else:
            message = "\n".join(f"{i+1}. {song.title}" for i, song in enumerate(queue))
            await interaction.response.send_message(f"**Queue:**\n{message}")

    @app_commands.command(name="stop", description="Stops playback and clears the queue.")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            self.music_queues[interaction.guild.id] = []
            await interaction.response.send_message("Playback stopped and queue cleared.", ephemeral=True)
        else:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeMusic(bot))
