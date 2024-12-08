import discord
from discord import app_commands
from discord.ext import commands
from discord import FFmpegPCMAudio
from fish_audio_sdk import Session, TTSRequest
import os
from dotenv import load_dotenv

# Load the .env file
load_dotenv()

# Initialize the Fish Audio session
FISH_TOKEN = os.getenv("FISH_TOKEN")
MODEL_ID = os.getenv("MODEL_ID")

if not FISH_TOKEN or not MODEL_ID:
    raise ValueError("FISH_TOKEN or MODEL_ID is not set in the .env file.")

session = Session(FISH_TOKEN)


class FishSpeech(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def join_voice_channel(self, interaction: discord.Interaction):
        """
        Joins the user's current voice channel if the bot is not already in one.
        """
        if interaction.user.voice is None:
            await interaction.response.send_message("You must be in a voice channel to use this command!", ephemeral=True)
            return None

        channel = interaction.user.voice.channel
        if interaction.guild.voice_client is None:
            await channel.connect()
        elif interaction.guild.voice_client.channel != channel:
            await interaction.guild.voice_client.move_to(channel)

        return interaction.guild.voice_client

    async def generate_tts(self, text):
        """
        Generates TTS audio from the Fish Speech API and saves it as an MP3 file.
        """
        file_path = "tts_output.mp3"
        with open(file_path, "wb") as f:
            for chunk in session.tts(
                TTSRequest(reference_id=MODEL_ID, text=text)
            ):
                f.write(chunk)
        return file_path

    @app_commands.command(name="say", description="Generate TTS from text and play it in the voice channel.")
    async def say(self, interaction: discord.Interaction, text: str):
        """
        Command to generate and play TTS in a voice channel.
        """
        # Join the user's voice channel
        voice_client = await self.join_voice_channel(interaction)
        if voice_client is None:
            return

        # Acknowledge the command to let the user know it's processing
        await interaction.response.defer(ephemeral=True)

        # Generate TTS audio
        try:
            tts_path = await self.generate_tts(text)
        except Exception as e:
            await interaction.followup.send(f"Failed to generate TTS: {e}")
            return

        # Play the audio
        try:
            audio_source = FFmpegPCMAudio(tts_path)
            if not voice_client.is_playing():
                voice_client.play(audio_source, after=lambda e: os.remove(tts_path) if os.path.exists(tts_path) else None)
                await interaction.followup.send(f"🎙️ Playing: {text}", ephemeral=True)
            else:
                await interaction.followup.send("Already playing audio! Please wait.")
        except Exception as e:
            await interaction.followup.send(f"Failed to play TTS: {e}")

    @app_commands.command(name="leave", description="Make the bot leave the voice channel.")
    async def leave(self, interaction: discord.Interaction):
        """
        Disconnects the bot from the voice channel.
        """
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("Disconnected from the voice channel.", ephemeral=True)
        else:
            await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Sync the slash commands when the bot is ready.
        """
        await self.bot.tree.sync()
        print(f"Slash commands synced for FishSpeech Cog.")

# Add the Cog to the bot
async def setup(bot):
    await bot.add_cog(FishSpeech(bot))
