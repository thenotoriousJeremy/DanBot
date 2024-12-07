import asyncio
import json
from io import BytesIO  # Import BytesIO for in-memory binary streams
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image, ImageDraw, ImageFont
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import pytz  # To handle timezone conversions
import re
import os
from collections import defaultdict
from PIL import Image, ImageDraw
import numpy as np
import matplotlib.colors as mcolors
from matplotlib.collections import LineCollection

class ServerWrapped(commands.Cog):
    CACHE_FILE = "server_wrapped_cache.json"
    CACHE_EXPIRY = timedelta(hours=24)  # Cache data for 24 hours
    EST = pytz.timezone("America/New_York")  # Timezone for Eastern Standard Time

    def __init__(self, bot):
        self.bot = bot
        self.current_year = datetime.now().year
        self.cache = self.load_cache()

    def load_cache(self):
        """
        Load cached data from the file.
        """
        if os.path.exists(self.CACHE_FILE):
            with open(self.CACHE_FILE, "r") as f:
                return json.load(f)
        return {}

    def save_cache(self):
        """
        Save cached data to the file.
        """
        with open(self.CACHE_FILE, "w") as f:
            json.dump(self.cache, f)

    def is_cache_valid(self, guild_id):
        """
        Check if cached data for the guild is still valid.
        """
        if str(guild_id) in self.cache:
            last_scraped = datetime.fromisoformat(self.cache[str(guild_id)]["last_scraped"])
            return datetime.now() - last_scraped < self.CACHE_EXPIRY
        return False

    @app_commands.command(name="server_wrapped", description="Generate a detailed server activity report for this year")
    async def server_wrapped(self, interaction: discord.Interaction):
        """
        Generate a detailed server activity infographic by pulling historical data from the current year.
        """
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Defer response to handle processing
        await interaction.response.defer()

        # Check cache validity
        if self.is_cache_valid(guild.id):
            print("Using cached data.")
            cached_data = self.cache[str(guild.id)]
            messages = [
                self.reconstruct_message(msg_data, guild) for msg_data in cached_data["messages"]
            ]
            word_cloud_data = cached_data["word_cloud_data"]
            word_counts = cached_data["word_counts"]  # Load word counts from cache
            message_counts = cached_data["message_counts"]
            reaction_counts = cached_data["reaction_counts"]
            active_hours = cached_data["active_hours"]
        else:
            messages, word_cloud_data, message_counts, word_counts, reaction_counts, active_hours = await self.fetch_historical_data(guild)
            # Save essential data to cache
            self.cache[str(guild.id)] = {
                "last_scraped": datetime.now().isoformat(),
                "messages": [
                    {"content": msg["content"], "author_id": msg["author_id"], "id": msg["id"], "channel_id": msg["channel_id"]}
                    for msg in messages
                ],
                "word_cloud_data": word_cloud_data,
                "message_counts": message_counts,
                "word_counts": word_counts,  # Include word counts in the cache
                "reaction_counts": reaction_counts,
                "active_hours": active_hours,
            }

            self.save_cache()

        # Generate Word Cloud
        filtered_word_cloud_data = self.filter_text(word_cloud_data)
        wordcloud_path = self.generate_word_cloud(filtered_word_cloud_data)

        # Generate Activity Heatmap
        heatmap_path = self.generate_activity_heatmap(active_hours)

        # Generate Message Count Graph
        message_count_graph_path = await self.generate_message_count_graph(guild, message_counts)

        # Generate Most Reacted Messages Text
        most_reacted_messages = await self.generate_most_reacted_messages(guild, reaction_counts, messages)

        # Generate Longest Messages Text
        longest_messages = await self.generate_longest_messages(guild, messages)

        # Add description
        description = (
            "**What is Server Wrapped?**\n"
            "Server Wrapped is your personalized yearly recap of server activity! 🎉\n"
            "It highlights this community's most active hours, top contributors, most reacted messages, "
            "and even generates a fun word cloud from your conversations. Dive in and relive the year! 🎨✨\n\n"
        )

        # Generate Word Count Graph
        word_count_graph_path = await self.generate_word_count_graph(guild, word_counts)

        # Send all the generated images
        paths = [
            wordcloud_path,
            heatmap_path,
            message_count_graph_path,
            word_count_graph_path,  # Include the word count graph
        ]
        files = [discord.File(path, filename=os.path.basename(path)) for path in paths]

        await interaction.followup.send(
            content=f"{description}🎉 Here's your Server Wrapped!\n\n**Most Reacted Messages:**\n{most_reacted_messages}\n\n**Longest Messages:**\n{longest_messages}\n",
            files=files,
        )

        # Cleanup
        for path in paths:
            os.remove(path)

    def reconstruct_message(self, msg_data, guild):
        """
        Reconstruct a minimal message-like object from cached data.
        """
        class CachedMessage:
            def __init__(self, content, author, msg_id, channel_id):
                self.content = content
                self.author = author  # This should be a Member or User object
                self.id = msg_id
                self.channel_id = channel_id

        author = guild.get_member(msg_data["author_id"]) or discord.Object(id=msg_data["author_id"])
        return CachedMessage(
            content=msg_data["content"],
            author=author,
            msg_id=msg_data["id"],
            channel_id=msg_data["channel_id"]
        )


    async def fetch_historical_data(self, guild):
        """
        Fetch historical messages from all channels in the server for the entire year.
        """
        start_of_year = datetime(self.current_year, 1, 1)
        messages = []
        word_cloud_data = ""
        message_counts = defaultdict(int)
        word_counts = defaultdict(int)  # Initialize word_counts
        reaction_counts = {}  # Store message ID and channel ID
        active_hours = [0] * 24

        print(f"Fetching historical data for guild: {guild.name} ({guild.id})")

        for channel in guild.text_channels:
            try:
                print(f"Starting to fetch messages from channel: {channel.name} ({channel.id})")
                
                async for message in channel.history(after=start_of_year, oldest_first=True, limit=None):
                    if message.author.bot:
                        continue  # Ignore bot messages

                    # Append minimal data to messages
                    messages.append({
                        "content": message.content,
                        "author_id": message.author.id,
                        "id": message.id,
                        "channel_id": channel.id,  # Add channel ID
                    })
                    word_cloud_data += f" {message.content}"
                    message_counts[message.author.id] += 1
                    word_counts[message.author.id] += len(message.content.split())  # Count words per user

                    # Convert message creation time to EST
                    est_time = message.created_at.astimezone(self.EST)
                    active_hours[est_time.hour] += 1

                    for reaction in message.reactions:
                        reaction_counts[message.id] = {
                            "channel_id": channel.id,
                            "reaction_count": reaction_counts.get(message.id, {}).get("reaction_count", 0) + reaction.count,
                        }

                print(f"Completed fetching messages from channel: {channel.name} ({channel.id})")
            except discord.Forbidden:
                print(f"Cannot access channel: {channel.name} ({channel.id})")
            except discord.HTTPException as e:
                print(f"Error fetching history for channel {channel.name} ({channel.id}): {e}")

        print(f"Finished fetching historical data for guild: {guild.name} ({guild.id})")

        return messages, word_cloud_data, message_counts, word_counts, reaction_counts, active_hours

    def filter_text(self, text):
        """
        Filter URLs, non-English letters, and common words from text.
        """
        text = re.sub(r"http\S+|www\S+", "", text)  # Remove URLs
        text = re.sub(r"[^a-zA-Z\s]", "", text)  # Remove non-English letters
        stopwords = {
            "the", "and", "a", "to", "of", "in", "is", "you", "that", "it", "for", "on",
            "with", "as", "was", "this", "have", "just", "if", "one", "we", "or", "my",
            "like", "so", "at", "be", "by", "not", "what", "about", "which", "but", "im", "ive"
        }
        return " ".join(word for word in text.split() if word.lower() not in stopwords)

    async def generate_most_reacted_messages(self, guild, reaction_counts, top_n=5):
        """
        Generate a list of the most reacted-to messages and return a string with links.
        """
        # Validate top_n
        if not isinstance(top_n, int) or top_n < 1:
            top_n = 5  # Default to 5 if top_n is invalid

        # Ensure reaction_counts is properly structured
        try:
            sorted_messages = sorted(
                reaction_counts.items(),
                key=lambda x: x[1]["reaction_count"],
                reverse=True
            )
        except KeyError as e:
            print(f"Error sorting reaction counts: {e}")
            return "No reacted messages found in this server for the current year."

        # Slice the top N messages
        top_messages = sorted_messages[:top_n]

        if not top_messages:
            return "No reacted messages found in this server for the current year."

        message_links = []
        for msg_id, data in top_messages:
            channel_id = data["channel_id"]
            reaction_count = data["reaction_count"]

            try:
                # Fetch the channel and message
                channel = guild.get_channel(channel_id)
                message = await channel.fetch_message(msg_id)
                link = f"https://discord.com/channels/{guild.id}/{channel.id}/{message.id}"
                message_links.append(f"**[{message.author.display_name}](<{link}>)**: {reaction_count} reactions")
            except Exception as e:
                print(f"Error fetching message ID {msg_id}: {e}")
                message_links.append(f"Message ID `{msg_id}`: {reaction_count} reactions (Message not accessible)")

        return "\n".join(message_links)
    
    async def generate_longest_messages(self, guild, messages, top_n=5):
        """
        Generate a list of the longest messages and return a string with links.
        """
        # Validate top_n
        if not isinstance(top_n, int) or top_n < 1:
            top_n = 5  # Default to 5 if top_n is invalid

        # Sort messages by length of content
        sorted_messages = sorted(messages, key=lambda x: len(x.content), reverse=True)  # Use attribute access

        # Slice the top N longest messages
        top_messages = sorted_messages[:top_n]

        if not top_messages:
            return "No long messages found in this server for the current year."

        message_links = []
        for msg in top_messages:
            channel_id = msg.channel_id
            message_id = msg.id
            content_length = len(msg.content)
            author_id = msg.author.id

            try:
                # Fetch the channel and message
                channel = guild.get_channel(channel_id)
                if not channel:
                    raise discord.Forbidden

                message = await channel.fetch_message(message_id)
                link = f"https://discord.com/channels/{guild.id}/{channel.id}/{message.id}"
                author_name = message.author.display_name
                message_links.append(f"**[{author_name}](<{link}>)**: {content_length} characters")
            except discord.Forbidden:
                author = guild.get_member(author_id) or discord.Object(id=author_id)
                author_name = author.display_name if isinstance(author, discord.Member) else "Unknown"
                message_links.append(f"Message by **{author_name}**: {content_length} characters (Message not accessible)")
            except Exception as e:
                print(f"Error processing message ID {message_id}: {e}")
                message_links.append(f"Message ID `{message_id}`: {content_length} characters (Error: {e})")

        return "\n".join(message_links)

    def generate_word_cloud(self, text):
        """
        Generate a word cloud for the server's messages.
        """
        wordcloud = WordCloud(
            width=1024,
            height=1024,
            background_color="black",
            colormap="Set3"
        ).generate(text)

        wordcloud_path = "wordcloud.png"
        wordcloud.to_file(wordcloud_path)

        return wordcloud_path

    def generate_activity_heatmap(self, active_hours):
        """
        Generate a heatmap showing the server's activity by hour (converted to EST) using a gradient line.
        """
        # Normalize the values for the gradient
        total_messages = sum(active_hours)
        normalized_values = [count / max(active_hours) if max(active_hours) > 0 else 0 for count in active_hours]

        hours = range(24)

        # Create the figure
        fig, ax = plt.subplots(figsize=(12, 6))
        background_color = "#2C2F33"  # Discord darker background
        fig.patch.set_facecolor(background_color)
        ax.set_facecolor(background_color)

        # Gradient color map (from blue to red)
        cmap = mcolors.LinearSegmentedColormap.from_list("activity_gradient", ["blue", "red"])
        colors = cmap(normalized_values)

        # Create segments for the line plot
        points = np.array([hours, active_hours]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        lc = LineCollection(segments, cmap=cmap, norm=plt.Normalize(0, max(active_hours)))
        lc.set_array(np.array(active_hours))
        lc.set_linewidth(3)

        # Add the line to the plot
        ax.add_collection(lc)
        ax.plot(hours, active_hours, color="white", alpha=0.2, zorder=0)  # Light base line for clarity

        # Labels and titles
        ax.set_title("Activity by Hour (EST)", color="white", fontsize=16)
        ax.set_xlabel("Hour of the Day", color="white")
        ax.set_ylabel("Messages", color="white")
        ax.tick_params(axis="both", colors="white")
        ax.set_xticks(hours)  # Correctly set ticks for x-axis
        ax.set_xticklabels([f"{hour}:00" for hour in hours], rotation=45, color="white")
        ax.set_yticks(range(0, max(active_hours) + 1, max(max(active_hours) // 10, 1)))  # Dynamically set y-axis ticks

        # Adjust layout
        plt.tight_layout()

        # Save the graph
        heatmap_path = "activity_heatmap.png"
        plt.savefig(heatmap_path, transparent=False, facecolor=fig.get_facecolor())
        plt.close()

        return heatmap_path

    async def generate_message_count_graph(self, guild, message_counts):
        """
        Generate a horizontal bar graph of message counts styled to match Discord's darker theme.
        """
        sorted_users = sorted(message_counts.items(), key=lambda x: x[1])  # Sort by least to most messages
        num_users = len(sorted_users)

        # Dynamically adjust the figure size: height depends on the number of users
        fig_width = 10  # Fixed width in inches
        fig_height = max(6, num_users * 0.5)  # Minimum height of 6 inches, scales with user count

        # Create the figure with the calculated dimensions
        fig, ax = plt.subplots(figsize=(fig_width, fig_height))
        background_color = "#36393F"  # Discord darker background
        fig.patch.set_facecolor("#2C2F33")  # Set figure background
        ax.set_facecolor("#2C2F33")  # Set axes background

        # Prepare data
        y = range(num_users)
        x = [count for _, count in sorted_users]
        names = []
        avatars = []
        bar_colors = []

        for user_id, _ in sorted_users:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if member:
                names.append(member.display_name)
                avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                try:
                    # Fetch avatar and calculate average color
                    async with self.bot.http._HTTPClient__session.get(avatar_url) as response:
                        avatar_data = await response.read()
                    avatar = Image.open(BytesIO(avatar_data)).resize((20, 20))  # Resize avatar for graph
                    avatar_array = np.array(avatar)
                    avg_color = tuple(avatar_array.mean(axis=(0, 1)).astype(int))
                    bar_colors.append(f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}")
                    avatars.append(avatar)
                except Exception as e:
                    print(f"Error fetching avatar for {member.display_name}: {e}")
                    bar_colors.append("cyan")  # Fallback color
                    avatars.append(None)
            else:
                names.append("Unknown")
                bar_colors.append("cyan")  # Fallback color
                avatars.append(None)

        # Plot horizontal bars
        bar_height = 0.5  # Reduced bar height for tighter spacing
        ax.barh(y, x, color=bar_colors, height=bar_height)
        ax.set_title("Message Counts by User", color="#FFFFFF", fontsize=18)  # Larger title font
        ax.set_xlabel("Messages", color="#FFFFFF", fontsize=14)  # Larger x-axis label font
        ax.set_ylabel("Users", color="#FFFFFF", fontsize=14)  # Larger y-axis label font
        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12, ha="right", x=-0.01)  # Reduced spacing with x=-0.01
        ax.tick_params(axis="x", colors="#FFFFFF", labelsize=12)  # Updated x-axis ticks to match Discord text color

        # Add avatars and message counts at the end of each bar
        for i, (name, count, avatar) in enumerate(zip(names, x, avatars)):
            # Add message count slightly beyond the end of the bar
            ax.text(count + max(x) * 0.03, i, str(count), va="center", color="#FFFFFF", fontsize=12)

            if avatar:
                # Convert avatar to a circular image
                mask = Image.new("L", avatar.size, 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                avatar = avatar.convert("RGBA")
                avatar.putalpha(mask)

                # Display the circular avatar centered at the end of the bar
                avatar_imagebox = OffsetImage(avatar, zoom=1)
                ab = AnnotationBbox(
                    avatar_imagebox,
                    (count, i),  # Center the avatar at the end of the bar
                    frameon=False,
                    xycoords="data",
                    box_alignment=(0.5, 0.5),
                )
                ax.add_artist(ab)

        # Add buffer space to the graph
        ax.set_xlim(0, max(x) + max(x) * 0.3)  # Add extra space for avatars and counts
        ax.set_ylim(-0.5, num_users - 0.5)  # Adjust for clarity

        # Save the graph
        graph_path = "message_count_graph.png"
        plt.savefig(graph_path, bbox_inches="tight", transparent=False, facecolor=fig.get_facecolor())
        plt.close()

        return graph_path

    async def generate_word_count_graph(self, guild, word_counts):
        """
        Generate a horizontal bar graph of word counts styled to match Discord's darker theme.
        """
        # Sort by word count descending to display most words at the top
        sorted_users = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        num_users = len(sorted_users)

        # Dynamically adjust the figure size: height depends on the number of users
        fig_width = 10  # Fixed width in inches
        fig_height = max(6, num_users * 0.5)  # Minimum height of 6 inches, scales with user count

        # Create the figure with the calculated dimensions
        fig, ax = plt.subplots(figsize=(fig_width, fig_height))
        background_color = "#36393F"  # Discord darker background
        fig.patch.set_facecolor("#2C2F33")  # Set figure background
        ax.set_facecolor("#2C2F33")  # Set axes background

        # Prepare data
        y = list(range(num_users - 1, -1, -1))  # Create descending order for y-axis
        x = [count for _, count in sorted_users]  # Word counts
        names = []  # User display names
        avatars = []  # User avatars
        bar_colors = []  # Colors for bars

        for user_id, _ in sorted_users:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if member:
                names.append(member.display_name)
                avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                try:
                    # Fetch avatar and calculate average color
                    async with self.bot.http._HTTPClient__session.get(avatar_url) as response:
                        avatar_data = await response.read()
                    avatar = Image.open(BytesIO(avatar_data)).resize((20, 20))  # Resize avatar for graph
                    avatar_array = np.array(avatar)
                    avg_color = tuple(avatar_array.mean(axis=(0, 1)).astype(int))
                    bar_colors.append(f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}")
                    avatars.append(avatar)
                except Exception as e:
                    print(f"Error fetching avatar for {member.display_name}: {e}")
                    bar_colors.append("cyan")  # Fallback color
                    avatars.append(None)
            else:
                names.append("Unknown")
                bar_colors.append("cyan")  # Fallback color
                avatars.append(None)

        # Plot horizontal bars
        bar_height = 0.5  # Reduced bar height for tighter spacing
        ax.barh(y, x, color=bar_colors, height=bar_height)
        ax.set_title("Word Counts by User", color="#FFFFFF", fontsize=18)  # Larger title font
        ax.set_xlabel("Words", color="#FFFFFF", fontsize=14)  # Larger x-axis label font
        ax.set_ylabel("Users", color="#FFFFFF", fontsize=14)  # Larger y-axis label font
        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12, ha="right", x=-0.01)  # Correct alignment
        ax.tick_params(axis="x", colors="#FFFFFF", labelsize=12)  # Updated x-axis ticks to match Discord text color

        # Add avatars and word counts at the end of each bar
        for i, (name, count, avatar) in enumerate(zip(names, x, avatars)):
            # Add word count slightly beyond the end of the bar
            ax.text(count + max(x) * 0.03, y[i], str(count), va="center", color="#FFFFFF", fontsize=12)

            if avatar:
                # Convert avatar to a circular image
                mask = Image.new("L", avatar.size, 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                avatar = avatar.convert("RGBA")
                avatar.putalpha(mask)

                # Display the circular avatar centered at the end of the bar
                avatar_imagebox = OffsetImage(avatar, zoom=1)
                ab = AnnotationBbox(
                    avatar_imagebox,
                    (count, y[i]),  # Center the avatar at the end of the bar
                    frameon=False,
                    xycoords="data",
                    box_alignment=(0.5, 0.5),
                )
                ax.add_artist(ab)

        # Add buffer space to the graph
        ax.set_xlim(0, max(x) + max(x) * 0.3)  # Add extra space for avatars and counts
        ax.set_ylim(-0.5, num_users - 0.5)  # Adjust for clarity

        # Save the graph
        graph_path = "word_count_graph.png"
        plt.savefig(graph_path, bbox_inches="tight", transparent=False, facecolor=fig.get_facecolor())
        plt.close()

        return graph_path

async def setup(bot):
    await bot.add_cog(ServerWrapped(bot))
