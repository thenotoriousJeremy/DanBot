import asyncio
import os
import shutil
import random
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

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url', '')
        self.played_seconds = 0.0

    def read(self):
        data = super().read()
        if data:
            self.played_seconds += 0.02
        return data

    @classmethod
    async def create_source(cls, query, *, loop=None, volume=0.5):
        """Creates an FFmpeg streaming audio source from query."""
        loop = loop or asyncio.get_running_loop()
        
        def fetch_data():
            try:
                data = ytdl.extract_info(f"ytsearch:{query}" if not query.startswith('http') else query, download=False)
                if 'entries' in data:
                    return data['entries'][0]
                return data
            except Exception as e:
                print(f"[Music] Error extracting ytsearch info: {e}")
                return None
        
        data = await loop.run_in_executor(None, fetch_data)
        if not data:
            raise ValueError(f"Could not find any results for: {query}")
        
        filename = data['url']
        return cls(discord.FFmpegPCMAudio(filename, executable=FFMPEG_EXECUTABLE, **ffmpeg_options), data=data, volume=volume)

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
                print(f"[Music] Error fetching metadata: {e}")
                return None
                
        data = await loop.run_in_executor(None, fetch_data)
        if not data:
            raise ValueError(f"Could not find results for: {query}")
        return data


def get_progress_bar(played: float, total: float, bar_length: int = 15) -> str:
    """Renders a beautiful visual Spotify-style progress bar slider."""
    if total <= 0:
        return "🔴 Live Stream"
    progress = played / total
    progress = max(0.0, min(1.0, progress))
    num_filled = int(progress * bar_length)
    num_empty = bar_length - num_filled
    
    bar = "▬" * num_filled + "🔘" + "▬" * num_empty
    
    def format_time(seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    return f"`{format_time(played)}` {bar} `{format_time(total)}`"


class GuildMusicPlayer:
    def __init__(self, bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = []
        self.current = None
        self.vc = None
        self.text_channel = None
        self.volume = 0.5
        self.loop = False
        self.loop_queue = False
        self.shuffle = False
        self.current_message = None
        self._update_task = None

    def create_player_embed(self) -> discord.Embed:
        """Create a premium styled Discord Embed for the music player."""
        if not self.current:
            embed = discord.Embed(
                title="🎵 Music Player",
                description="Nothing is playing right now.",
                color=discord.Color.dark_gray()
            )
            return embed

        source = self.current
        embed = discord.Embed(
            title=source.title,
            url=source.webpage_url,
            color=discord.Color.from_rgb(29, 185, 84) # Spotify Green
        )
        
        # Player status indicator
        status = "⏸️ Paused" if self.vc and self.vc.is_paused() else "▶️ Now Playing"
        embed.set_author(name=status, icon_url=self.bot.user.display_avatar.url)
        
        # Thumbnail image
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
            
        # Progress Bar & Duration
        progress = get_progress_bar(source.played_seconds, source.duration)
        embed.add_field(name="Progress", value=progress, inline=False)
        
        # Queue count
        embed.add_field(name="Queue Size", value=f"`{len(self.queue)} track(s)`", inline=True)
        
        # Volume
        embed.add_field(name="Volume", value=f"`{int(self.volume * 100)}%`", inline=True)
        
        # Loop Status
        loop_status = "Single Track" if self.loop else ("Whole Queue" if self.loop_queue else "Off")
        embed.add_field(name="Looping", value=f"`{loop_status}`", inline=True)
        
        # Requester footer
        req = source.data.get('requester')
        if req:
            embed.set_footer(text=f"Requested by {req.display_name}", icon_url=req.display_avatar.url)
            
        return embed

    async def _update_loop(self):
        """Asynchronously updates the player embed progress bar in real-time."""
        while self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            try:
                if self.current_message and self.current:
                    embed = self.create_player_embed()
                    view = MusicPlayerView(self)
                    await self.current_message.edit(embed=embed, view=view)
            except Exception as e:
                print(f"[Music] Error updating embed: {e}")
            await asyncio.sleep(8) # 8 seconds to prevent rate-limiting

    async def play_next(self):
        """Logic to advance player queue and launch next track."""
        if not self.vc or not self.vc.is_connected():
            return

        # Clean up last message/embed
        if self.current_message:
            try:
                await self.current_message.edit(view=None)
            except Exception:
                pass
            self.current_message = None

        if self.loop and self.current:
            # Loop current song
            query = self.current.data.get('webpage_url') or self.current.title
            requester = self.current.data.get('requester')
        elif self.loop_queue and self.current:
            # Loop queue: append current to end and fetch next
            old_item = {
                'original_query': self.current.data.get('webpage_url') or self.current.title,
                'title': self.current.title,
                'requester': self.current.data.get('requester'),
                'thumbnail': self.current.thumbnail,
                'duration': self.current.duration
            }
            self.queue.append(old_item)
            if not self.queue:
                self.current = None
                return
            if self.shuffle:
                next_item = self.queue.pop(random.randint(0, len(self.queue) - 1))
            else:
                next_item = self.queue.pop(0)
            query = next_item['original_query']
            requester = next_item.get('requester')
        else:
            # standard queue advancement
            if not self.queue:
                self.current = None
                if self.text_channel:
                    await self.text_channel.send("Queue finished. 🎵")
                return
            if self.shuffle:
                next_item = self.queue.pop(random.randint(0, len(self.queue) - 1))
            else:
                next_item = self.queue.pop(0)
            query = next_item['original_query']
            requester = next_item.get('requester')

        try:
            player = await YTDLSource.create_source(query, volume=self.volume)
            player.data['requester'] = requester
            self.current = player
            
            self.vc.play(
                player,
                after=lambda e: self.bot.loop.call_soon_threadsafe(
                    asyncio.create_task, self.play_next()
                )
            )

            # Post player card message
            embed = self.create_player_embed()
            view = MusicPlayerView(self)
            self.current_message = await self.text_channel.send(embed=embed, view=view)
            
            # Restart update task
            if self._update_task:
                self._update_task.cancel()
            self._update_task = self.bot.loop.create_task(self._update_loop())
            
        except Exception as e:
            if self.text_channel:
                await self.text_channel.send(f"Failed to play next track: {e}")
            await self.play_next()

    async def stop(self):
        """Stops audio, clears queue, disconnects voice, and cleans up tasks."""
        self.queue.clear()
        self.current = None
        self.loop = False
        self.loop_queue = False
        
        if self._update_task:
            self._update_task.cancel()
            self._update_task = None
            
        if self.current_message:
            try:
                await self.current_message.edit(view=None)
            except Exception:
                pass
            self.current_message = None
            
        if self.vc:
            self.vc.stop()
            await self.vc.disconnect()
            self.vc = None


class MusicPlayerView(discord.ui.View):
    def __init__(self, player: GuildMusicPlayer):
        super().__init__(timeout=None)
        self.player = player
        self.update_button_styles()

    def update_button_styles(self):
        """Update aesthetic labels and visual button highlights based on player states."""
        # 1. Play/Pause Button
        play_btn = [b for b in self.children if b.custom_id == "play_pause"][0]
        if self.player.vc and self.player.vc.is_paused():
            play_btn.label = "▶️ Resume"
            play_btn.style = discord.ui.ButtonStyle.green
        else:
            play_btn.label = "⏸️ Pause"
            play_btn.style = discord.ui.ButtonStyle.grey

        # 2. Loop Button
        loop_btn = [b for b in self.children if b.custom_id == "loop"][0]
        if self.player.loop:
            loop_btn.label = "🔁 Single"
            loop_btn.style = discord.ui.ButtonStyle.green
        elif self.player.loop_queue:
            loop_btn.label = "🔁 Queue"
            loop_btn.style = discord.ui.ButtonStyle.blurple
        else:
            loop_btn.label = "🔁 Loop Off"
            loop_btn.style = discord.ui.ButtonStyle.grey

        # 3. Shuffle Button
        shuffle_btn = [b for b in self.children if b.custom_id == "shuffle"][0]
        if self.player.shuffle:
            shuffle_btn.style = discord.ui.ButtonStyle.green
        else:
            shuffle_btn.style = discord.ui.ButtonStyle.grey

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Validate if interactive user is in identical VC as bot."""
        if not interaction.guild.voice_client:
            await interaction.response.send_message("I am not in a voice channel.", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel != interaction.guild.voice_client.channel:
            await interaction.response.send_message("You must be inside my voice channel to operate the player! 😠", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏸️ Pause", style=discord.ui.ButtonStyle.grey, custom_id="play_pause")
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.vc:
            await interaction.response.send_message("Not currently playing.", ephemeral=True)
            return

        if self.player.vc.is_paused():
            self.player.vc.resume()
            await interaction.response.send_message("Resumed playback.", ephemeral=True)
        else:
            self.player.vc.pause()
            await interaction.response.send_message("Paused playback.", ephemeral=True)
        self.update_button_styles()
        await interaction.message.edit(embed=self.player.create_player_embed(), view=self)

    @discord.ui.button(label="⏭️ Skip", style=discord.ui.ButtonStyle.grey, custom_id="skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.vc:
            self.player.vc.stop()
            await interaction.response.send_message("Skipped track.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ui.ButtonStyle.red, custom_id="stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.stop()
        await interaction.response.send_message("Playback stopped and channel disconnected.", ephemeral=True)

    @discord.ui.button(label="🔁 Loop Off", style=discord.ui.ButtonStyle.grey, custom_id="loop")
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.loop and not self.player.loop_queue:
            self.player.loop = True
            await interaction.response.send_message("Looping single track.", ephemeral=True)
        elif self.player.loop:
            self.player.loop = False
            self.player.loop_queue = True
            await interaction.response.send_message("Looping entire queue.", ephemeral=True)
        else:
            self.player.loop_queue = False
            await interaction.response.send_message("Looping disabled.", ephemeral=True)
        self.update_button_styles()
        await interaction.message.edit(embed=self.player.create_player_embed(), view=self)

    @discord.ui.button(label="🔀 Shuffle", style=discord.ui.ButtonStyle.grey, custom_id="shuffle")
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.shuffle = not self.player.shuffle
        state = "enabled" if self.player.shuffle else "disabled"
        await interaction.response.send_message(f"Shuffle {state}.", ephemeral=True)
        self.update_button_styles()
        await interaction.message.edit(embed=self.player.create_player_embed(), view=self)

    @discord.ui.button(label="📜 Queue", style=discord.ui.ButtonStyle.grey, custom_id="queue_list")
    async def view_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue_list = self.player.queue
        if not queue_list:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        
        desc = "\n".join(f"{i+1}. **{item['title']}**" for i, item in enumerate(queue_list[:15]))
        if len(queue_list) > 15:
            desc += f"\n... and {len(queue_list) - 15} more tracks."
            
        embed = discord.Embed(
            title="Guild Playlist Queue",
            description=desc,
            color=discord.Color.from_rgb(29, 185, 84)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class YouTubeMusic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players = {}

    def get_player(self, guild_id: int) -> GuildMusicPlayer:
        """Fetch or spawn the dedicated music player for a given guild."""
        if guild_id not in self.players:
            self.players[guild_id] = GuildMusicPlayer(self.bot, guild_id)
        return self.players[guild_id]

    async def ensure_voice(self, interaction: discord.Interaction) -> GuildMusicPlayer:
        """Helper to guarantee voice connection and return current guild player."""
        if interaction.guild is None:
            await interaction.response.send_message("Commands must be used in a server.", ephemeral=True)
            return None
            
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await interaction.response.send_message("You must join a voice channel first!", ephemeral=True)
            return None

        player = self.get_player(interaction.guild.id)
        player.text_channel = interaction.channel

        try:
            if interaction.guild.voice_client is None:
                vc = await interaction.user.voice.channel.connect(
                    timeout=20.0,
                    reconnect=True,
                    self_deaf=True
                )
                player.vc = vc
            else:
                player.vc = interaction.guild.voice_client
                if interaction.guild.voice_client.channel != interaction.user.voice.channel:
                    await interaction.guild.voice_client.move_to(interaction.user.voice.channel)
            return player
        except Exception as e:
            await interaction.response.send_message(f"Could not link to voice channel: {e}", ephemeral=True)
            return None

    @app_commands.command(name="join", description="Joins your current voice channel.")
    async def join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = await self.ensure_voice(interaction)
        if player and player.vc:
            await interaction.followup.send(f"Connected to voice channel {player.vc.channel.mention}", ephemeral=True)

    @app_commands.command(name="play", description="Plays audio from a YouTube search or URL. Adds to queue if playing.")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)
        
        player = await self.ensure_voice(interaction)
        if not player:
            return

        try:
            metadata = await YTDLSource.get_metadata(query)
            title = metadata.get('title', 'Unknown Track')
            thumbnail = metadata.get('thumbnail')
            duration = metadata.get('duration', 0)
            webpage_url = metadata.get('webpage_url', '')
        except Exception as e:
            await interaction.followup.send(f"Failed to resolve search query: {e}", ephemeral=True)
            return

        queue_item = {
            'original_query': webpage_url or query,
            'title': title,
            'requester': interaction.user,
            'thumbnail': thumbnail,
            'duration': duration
        }

        if player.vc.is_playing() or player.vc.is_paused():
            player.queue.append(queue_item)
            await interaction.followup.send(f"Added to queue: **{title}** ➕", ephemeral=True)
        else:
            await interaction.followup.send(f"Now playing: **{title}** 🎵", ephemeral=True)
            player.queue.append(queue_item)
            await player.play_next()

    @app_commands.command(name="pause", description="Pauses current playback.")
    async def pause(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        if player.vc and player.vc.is_playing():
            player.vc.pause()
            await interaction.response.send_message("Playback paused.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resumes paused playback.")
    async def resume(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        if player.vc and player.vc.is_paused():
            player.vc.resume()
            await interaction.response.send_message("Playback resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("bot is not currently paused.", ephemeral=True)

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        if player.vc and (player.vc.is_playing() or player.vc.is_paused()):
            player.vc.stop()
            await interaction.response.send_message("Skipped track.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)

    @app_commands.command(name="stop", description="Stops music and leaves voice.")
    async def stop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        await player.stop()
        await interaction.response.send_message("Player stopped.", ephemeral=True)

    @app_commands.command(name="leave", description="Leaves the current voice channel.")
    async def leave(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        await player.stop()
        await interaction.response.send_message("bot disconnected.", ephemeral=True)

    @app_commands.command(name="queue", description="Shows the current tracks in the queue.")
    async def queue(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        if not player.queue:
            await interaction.response.send_message("The playlist queue is empty.", ephemeral=True)
            return

        desc = "\n".join(f"{i+1}. **{item['title']}**" for i, item in enumerate(player.queue[:10]))
        if len(player.queue) > 10:
            desc += f"\n... and {len(player.queue) - 10} more tracks."

        embed = discord.Embed(
            title="Music Queue",
            description=desc,
            color=discord.Color.from_rgb(29, 185, 84)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="volume", description="Sets the music volume (0-100).")
    async def volume(self, interaction: discord.Interaction, vol: int):
        if vol < 0 or vol > 100:
            await interaction.response.send_message("Volume range must be between 0 and 100.", ephemeral=True)
            return

        player = self.get_player(interaction.guild.id)
        player.volume = vol / 100
        if player.vc and player.vc.source:
            player.vc.source.volume = player.volume

        await interaction.response.send_message(f"Volume adjusted to **{vol}%**.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeMusic(bot))
