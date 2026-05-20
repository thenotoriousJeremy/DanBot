import asyncio
import json
import os
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from io import BytesIO
import numpy as np
import pytz

import discord
from discord.ext import commands
from discord import app_commands

# Plotting & Image processing libs
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.collections import LineCollection
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image, ImageDraw
from wordcloud import WordCloud

from database import DatabaseManager

class ServerWrapped(commands.Cog):
    CACHE_EXPIRY = timedelta(hours=24)  # Cache data for 24 hours
    EST = pytz.timezone("America/New_York")  # Timezone for Eastern Standard Time

    def __init__(self, bot):
        self.bot = bot
        self.current_year = datetime.now().year
        self._member_cache = {}
        self.bot.loop.create_task(self.init_tables())

    async def init_tables(self):
        """Create the server wrapped tables asynchronously if they do not exist."""
        try:
            async with await DatabaseManager.get_connection() as conn:
                # 1. Word frequencies
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS server_wrapped_word_freq (
                        guild_id INTEGER,
                        year INTEGER,
                        word TEXT,
                        count INTEGER,
                        PRIMARY KEY (guild_id, year, word)
                    );
                """)
                # 2. Most reacted messages
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS server_wrapped_most_reacted (
                        guild_id INTEGER,
                        year INTEGER,
                        message_id INTEGER,
                        channel_id INTEGER,
                        author_id INTEGER,
                        reaction_count INTEGER,
                        PRIMARY KEY (guild_id, year, message_id)
                    );
                """)
                # 3. Longest messages
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS server_wrapped_longest_messages (
                        guild_id INTEGER,
                        year INTEGER,
                        message_id INTEGER,
                        channel_id INTEGER,
                        author_id INTEGER,
                        content_length INTEGER,
                        PRIMARY KEY (guild_id, year, message_id)
                    );
                """)
                # 4. Cache status
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS server_wrapped_cache_status (
                        guild_id INTEGER,
                        year INTEGER,
                        last_scraped TEXT,
                        PRIMARY KEY (guild_id, year)
                    );
                """)
                await conn.commit()
            print("[ServerWrapped] Database tables initialized successfully.")
        except Exception as e:
            print(f"[ServerWrapped] Error initializing tables: {e}")

    async def is_cache_valid(self, guild_id: int, year: int) -> bool:
        """Check if cached data for the guild and year is still valid."""
        try:
            async with await DatabaseManager.get_connection() as conn:
                async with conn.execute(
                    "SELECT last_scraped FROM server_wrapped_cache_status WHERE guild_id = ? AND year = ?;",
                    (guild_id, year)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        last_scraped = datetime.fromisoformat(row[0])
                        return datetime.now() - last_scraped < self.CACHE_EXPIRY
            return False
        except Exception as e:
            print(f"[ServerWrapped] Error checking cache validity: {e}")
            return False

    @app_commands.command(name="server_wrapped", description="Generate a detailed server activity report for this year")
    async def server_wrapped(self, interaction: discord.Interaction):
        """Generate a detailed server activity infographic by pulling historical data from the current year."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Defer response to handle processing
        await interaction.response.defer()

        year = self.current_year

        # Check cache validity
        cache_valid = await self.is_cache_valid(guild.id, year)
        if cache_valid:
            print(f"[ServerWrapped] Using cached database statistics for guild: {guild.name}")
        else:
            print(f"[ServerWrapped] Cache invalid/expired for guild: {guild.name}. Fetching historical data...")
            await self.fetch_historical_data(guild, year)

        # Load values from DB
        active_hours = [0] * 24
        message_counts = {}
        word_counts = {}
        word_frequencies = {}

        async with await DatabaseManager.get_connection() as conn:
            # 1. Active hours
            async with conn.execute(
                "SELECT active_hours FROM server_wrapped_metrics WHERE guild_id = ? AND year = ?;",
                (guild.id, year)
            ) as cursor:
                async for row in cursor:
                    if row[0]:
                        try:
                            hours_arr = json.loads(row[0])
                            for h in range(24):
                                active_hours[h] += hours_arr[h]
                        except Exception:
                            pass

            # 2. Message counts
            async with conn.execute(
                "SELECT user_id, message_count FROM server_wrapped_metrics WHERE guild_id = ? AND year = ? AND message_count > 0;",
                (guild.id, year)
            ) as cursor:
                async for row in cursor:
                    message_counts[row[0]] = row[1]

            # 3. Word counts
            async with conn.execute(
                "SELECT user_id, word_count FROM server_wrapped_metrics WHERE guild_id = ? AND year = ? AND word_count > 0;",
                (guild.id, year)
            ) as cursor:
                async for row in cursor:
                    word_counts[row[0]] = row[1]

            # 4. Word frequencies
            async with conn.execute(
                "SELECT word, count FROM server_wrapped_word_freq WHERE guild_id = ? AND year = ? ORDER BY count DESC LIMIT 1000;",
                (guild.id, year)
            ) as cursor:
                async for row in cursor:
                    word_frequencies[row[0]] = row[1]

        if not message_counts:
            await interaction.followup.send("No message history found in this server for the current year yet!")
            return

        # Generate Word Cloud (async via thread)
        wordcloud_path = os.path.join(os.getenv("DATA_DIR", "."), "wordcloud.png")
        if word_frequencies:
            await asyncio.to_thread(self._generate_word_cloud_sync, word_frequencies, wordcloud_path)
        else:
            # fallback
            await asyncio.to_thread(self._generate_word_cloud_sync, {"dan": 1}, wordcloud_path)

        # Generate Activity Heatmap (async via thread)
        heatmap_path = os.path.join(os.getenv("DATA_DIR", "."), "activity_heatmap.png")
        await asyncio.to_thread(self._generate_activity_heatmap_sync, active_hours, heatmap_path)

        # Generate Message Count Graph (concurrent fetch + async plot)
        message_count_graph_path = await self.generate_message_count_graph(guild, message_counts)

        # Generate Word Count Graph (concurrent fetch + async plot)
        word_count_graph_path = await self.generate_word_count_graph(guild, word_counts)

        # Generate Most Reacted Messages Text
        most_reacted_messages = await self.generate_most_reacted_messages(guild, year)

        # Generate Longest Messages Text
        longest_messages = await self.generate_longest_messages(guild, year)

        # Description details
        description = (
            "**What is Server Wrapped?**\n"
            "Server Wrapped is your personalized yearly recap of server activity! 🎉\n"
            "It highlights this community's most active hours, top contributors, most reacted messages, "
            "and even generates a fun word cloud from your conversations. Dive in and relive the year! 🎨✨\n\n"
        )

        paths = [
            wordcloud_path,
            heatmap_path,
            message_count_graph_path,
            word_count_graph_path
        ]
        files = []
        for path in paths:
            if os.path.exists(path):
                files.append(discord.File(path, filename=os.path.basename(path)))

        await interaction.followup.send(
            content=f"{description}🎉 Here's your Server Wrapped!\n\n**Most Reacted Messages:**\n{most_reacted_messages}\n\n**Longest Messages:**\n{longest_messages}\n",
            files=files,
        )

        # Cleanup files
        for path in paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    async def fetch_historical_data(self, guild, year: int):
        """Fetch historical messages from all channels in the server for the given year and save them to SQLite."""
        start_of_year = datetime(year, 1, 1)
        
        # In-memory accumulators
        global_word_counter = Counter()
        message_counts = defaultdict(int)
        word_counts = defaultdict(int)
        user_reaction_counts = defaultdict(int)
        user_active_hours = defaultdict(lambda: [0] * 24)
        
        most_reacted_list = []  # list of dicts
        longest_messages_list = []  # list of dicts

        print(f"[ServerWrapped] Fetching historical data for guild: {guild.name} ({guild.id})")

        for channel in guild.text_channels:
            try:
                print(f"[ServerWrapped] Fetching: #{channel.name}")
                msg_counter = 0
                async for message in channel.history(after=start_of_year, oldest_first=True, limit=None):
                    if message.author.bot:
                        continue

                    author_id = message.author.id
                    content = message.content or ""
                    content_length = len(content)

                    # 1. Message counts & Word counts
                    message_counts[author_id] += 1
                    words = content.split()
                    word_counts[author_id] += len(words)

                    # Filter and accumulate word frequencies for the WordCloud
                    filtered = self.filter_text(content)
                    if filtered:
                        global_word_counter.update(filtered.split())

                    # 2. Hourly activity (EST)
                    est_time = message.created_at.astimezone(self.EST)
                    user_active_hours[author_id][est_time.hour] += 1

                    # 3. Reactions
                    total_reactions = 0
                    for rx in message.reactions:
                        total_reactions += rx.count
                    
                    if total_reactions > 0:
                        user_reaction_counts[author_id] += total_reactions
                        most_reacted_list.append({
                            "message_id": message.id,
                            "channel_id": channel.id,
                            "author_id": author_id,
                            "reaction_count": total_reactions
                        })

                    # 4. Longest messages
                    if content_length > 0:
                        longest_messages_list.append({
                            "message_id": message.id,
                            "channel_id": channel.id,
                            "author_id": author_id,
                            "content_length": content_length
                        })

                    msg_counter += 1
                    if msg_counter % 100 == 0:
                        await asyncio.sleep(0.1)

                await asyncio.sleep(0.2)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                print(f"[ServerWrapped] Error on channel #{channel.name}: {e}")

        # Top 10 lists
        most_reacted_list = sorted(most_reacted_list, key=lambda x: x["reaction_count"], reverse=True)[:10]
        longest_messages_list = sorted(longest_messages_list, key=lambda x: x["content_length"], reverse=True)[:10]

        # Write to SQLite in a single transaction blocks
        async with await DatabaseManager.get_connection() as conn:
            # Clear old year data
            await conn.execute("DELETE FROM server_wrapped_metrics WHERE guild_id = ? AND year = ?;", (guild.id, year))
            await conn.execute("DELETE FROM server_wrapped_word_freq WHERE guild_id = ? AND year = ?;", (guild.id, year))
            await conn.execute("DELETE FROM server_wrapped_most_reacted WHERE guild_id = ? AND year = ?;", (guild.id, year))
            await conn.execute("DELETE FROM server_wrapped_longest_messages WHERE guild_id = ? AND year = ?;", (guild.id, year))

            # Insert Metrics
            all_users = set(message_counts.keys()) | set(word_counts.keys())
            for uid in all_users:
                m_count = message_counts[uid]
                w_count = word_counts[uid]
                r_count = user_reaction_counts[uid]
                hours_json = json.dumps(user_active_hours[uid])
                
                await conn.execute("""
                    INSERT INTO server_wrapped_metrics (guild_id, user_id, year, message_count, word_count, active_hours, reaction_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (guild.id, uid, year, m_count, w_count, hours_json, r_count))

            # Insert Word Frequencies (Top 1000 to keep database compact)
            top_words = global_word_counter.most_common(1000)
            for word, freq in top_words:
                await conn.execute("""
                    INSERT INTO server_wrapped_word_freq (guild_id, year, word, count)
                    VALUES (?, ?, ?, ?);
                """, (guild.id, year, word, freq))

            # Insert Most Reacted Messages
            for m in most_reacted_list:
                await conn.execute("""
                    INSERT INTO server_wrapped_most_reacted (guild_id, year, message_id, channel_id, author_id, reaction_count)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (guild.id, year, m["message_id"], m["channel_id"], m["author_id"], m["reaction_count"]))

            # Insert Longest Messages
            for m in longest_messages_list:
                await conn.execute("""
                    INSERT INTO server_wrapped_longest_messages (guild_id, year, message_id, channel_id, author_id, content_length)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (guild.id, year, m["message_id"], m["channel_id"], m["author_id"], m["content_length"]))

            # Update cache status
            await conn.execute("""
                INSERT OR REPLACE INTO server_wrapped_cache_status (guild_id, year, last_scraped)
                VALUES (?, ?, ?);
            """, (guild.id, year, datetime.now().isoformat()))

            await conn.commit()

        print(f"[ServerWrapped] History caching successfully completed in SQLite.")

    def filter_text(self, text):
        """Filter URLs, non-English letters, and common words from text."""
        text = re.sub(r"http\S+|www\S+", "", text)  # Remove URLs
        text = re.sub(r"[^a-zA-Z\s]", "", text)  # Remove non-English letters
        stopwords = {
            "the", "and", "a", "to", "of", "in", "is", "you", "that", "it", "for", "on",
            "with", "as", "was", "this", "have", "just", "if", "one", "we", "or", "my",
            "like", "so", "at", "be", "by", "not", "what", "about", "which", "but", "im", "ive"
        }
        return " ".join(word for word in text.split() if word.lower() not in stopwords)

    async def generate_most_reacted_messages(self, guild, year, top_n=5):
        """Generate a list of the most reacted-to messages and return a string with links."""
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("""
                SELECT message_id, channel_id, reaction_count FROM server_wrapped_most_reacted
                WHERE guild_id = ? AND year = ?
                ORDER BY reaction_count DESC LIMIT ?;
            """, (guild.id, year, top_n)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return "No reacted messages found in this server for the current year."

        message_links = []
        for msg_id, channel_id, reaction_count in rows:
            try:
                channel = guild.get_channel(channel_id)
                if not channel:
                    raise discord.Forbidden
                message = await self._safe_fetch_message(channel, msg_id)
                link = f"https://discord.com/channels/{guild.id}/{channel.id}/{message.id}"
                message_links.append(f"**[{message.author.display_name}](<{link}>)**: {reaction_count} reactions")
            except Exception as e:
                message_links.append(f"Message ID `{msg_id}`: {reaction_count} reactions (Message not accessible)")

        return "\n".join(message_links)

    async def generate_longest_messages(self, guild, year, top_n=5):
        """Generate a list of the longest messages and return a string with links."""
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("""
                SELECT message_id, channel_id, author_id, content_length FROM server_wrapped_longest_messages
                WHERE guild_id = ? AND year = ?
                ORDER BY content_length DESC LIMIT ?;
            """, (guild.id, year, top_n)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return "No long messages found in this server for the current year."

        message_links = []
        for msg_id, channel_id, author_id, content_length in rows:
            try:
                channel = guild.get_channel(channel_id)
                if not channel:
                    raise discord.Forbidden

                message = await self._safe_fetch_message(channel, msg_id)
                link = f"https://discord.com/channels/{guild.id}/{channel.id}/{message.id}"
                author_name = message.author.display_name
                message_links.append(f"**[{author_name}](<{link}>)**: {content_length} characters")
            except discord.Forbidden:
                author = guild.get_member(author_id) or discord.Object(id=author_id)
                author_name = author.display_name if isinstance(author, discord.Member) else f"User {author_id}"
                message_links.append(f"Message by **{author_name}**: {content_length} characters (Message not accessible)")
            except Exception as e:
                message_links.append(f"Message ID `{msg_id}`: {content_length} characters (Error: {e})")

        return "\n".join(message_links)

    async def _safe_fetch_message(self, channel, message_id, retries: int = 5):
        """Fetch a message with simple exponential backoff to handle 429s."""
        delay = 0.5
        last_exc = None
        for attempt in range(retries):
            try:
                return await channel.fetch_message(message_id)
            except discord.HTTPException as e:
                last_exc = e
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)
            except Exception:
                raise
        if last_exc:
            raise last_exc

    def _generate_word_cloud_sync(self, frequencies, out_path):
        """Generates word cloud from a dict of frequencies inside background thread."""
        wordcloud = WordCloud(
            width=1024,
            height=1024,
            background_color="black",
            colormap="Set3"
        ).generate_from_frequencies(frequencies)
        wordcloud.to_file(out_path)

    def _generate_activity_heatmap_sync(self, active_hours, out_path):
        """Generates activity heatmap inside background thread."""
        # Normalize values
        max_val = max(active_hours) if active_hours else 1
        normalized_values = [count / max_val for count in active_hours]
        hours = range(24)

        fig, ax = plt.subplots(figsize=(12, 6))
        background_color = "#2C2F33"  # Discord darker background
        fig.patch.set_facecolor(background_color)
        ax.set_facecolor(background_color)

        # Gradient color map (from blue to red)
        cmap = mcolors.LinearSegmentedColormap.from_list("activity_gradient", ["blue", "red"])

        points = np.array([hours, active_hours]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        lc = LineCollection(segments, cmap=cmap, norm=plt.Normalize(0, max_val))
        lc.set_array(np.array(active_hours))
        lc.set_linewidth(3)

        ax.add_collection(lc)
        ax.plot(hours, active_hours, color="white", alpha=0.2, zorder=0)

        ax.set_title("Activity by Hour (EST)", color="white", fontsize=16)
        ax.set_xlabel("Hour of the Day", color="white")
        ax.set_ylabel("Messages", color="white")
        ax.tick_params(axis="both", colors="white")
        ax.set_xticks(hours)
        ax.set_xticklabels([f"{hour}:00" for hour in hours], rotation=45, color="white")
        
        y_step = max(1, max_val // 10)
        ax.set_yticks(range(0, max_val + 1, y_step))

        plt.tight_layout()
        plt.savefig(out_path, transparent=False, facecolor=fig.get_facecolor())
        plt.close(fig)

    async def generate_message_count_graph(self, guild, message_counts):
        """Generate a horizontal bar graph of message counts concurrently with beautiful visual styling."""
        sorted_users = sorted(message_counts.items(), key=lambda x: x[1])[-15:]  # Limit to top 15 users
        num_users = len(sorted_users)

        fig_width = 10
        fig_height = max(6, num_users * 0.6)

        # Resolve members concurrently to fetch avatars
        resolved_members = []
        for user_id, _ in sorted_users:
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None
            resolved_members.append(member)

        # Fetch all avatars concurrently
        async def fetch_avatar(session, member):
            if not member:
                return None
            try:
                avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                async with session.get(str(avatar_url), timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except Exception:
                pass
            return None

        import aiohttp
        async with aiohttp.ClientSession() as session:
            avatar_tasks = [fetch_avatar(session, m) for m in resolved_members]
            avatars_data = await asyncio.gather(*avatar_tasks)

        out_path = os.path.join(os.getenv("DATA_DIR", "."), "message_count_graph.png")

        # Delegate Matplotlib rendering to worker thread
        await asyncio.to_thread(
            self._render_bar_graph_sync,
            sorted_users,
            resolved_members,
            avatars_data,
            out_path,
            "Message Counts by User",
            "Messages"
        )
        return out_path

    async def generate_word_count_graph(self, guild, word_counts):
        """Generate a horizontal bar graph of word counts concurrently with beautiful visual styling."""
        sorted_users = sorted(word_counts.items(), key=lambda x: x[1])[-15:]  # Limit to top 15 users
        num_users = len(sorted_users)

        fig_width = 10
        fig_height = max(6, num_users * 0.6)

        # Resolve members
        resolved_members = []
        for user_id, _ in sorted_users:
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None
            resolved_members.append(member)

        # Fetch avatars concurrently
        async def fetch_avatar(session, member):
            if not member:
                return None
            try:
                avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                async with session.get(str(avatar_url), timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except Exception:
                pass
            return None

        import aiohttp
        async with aiohttp.ClientSession() as session:
            avatar_tasks = [fetch_avatar(session, m) for m in resolved_members]
            avatars_data = await asyncio.gather(*avatar_tasks)

        out_path = os.path.join(os.getenv("DATA_DIR", "."), "word_count_graph.png")

        # Delegate Matplotlib rendering to worker thread
        await asyncio.to_thread(
            self._render_bar_graph_sync,
            sorted_users,
            resolved_members,
            avatars_data,
            out_path,
            "Word Counts by User",
            "Words"
        )
        return out_path

    def _render_bar_graph_sync(self, sorted_data, resolved_members, avatars_data, out_path, title, x_label):
        """Thread-safe synchronous Matplotlib bar rendering helper."""
        num_users = len(sorted_data)
        fig_width = 10
        fig_height = max(6, num_users * 0.6)

        fig, ax = plt.subplots(figsize=(fig_width, fig_height))
        fig.patch.set_facecolor("#2C2F33")
        ax.set_facecolor("#2C2F33")

        names = []
        counts = [count for _, count in sorted_data]
        bar_colors = []
        processed_avatars = []

        for i, (user_id, count) in enumerate(sorted_data):
            member = resolved_members[i]
            avatar_bytes = avatars_data[i]
            
            display_name = member.display_name if member else f"User {user_id}"
            names.append(display_name)

            avg_hex = "#10B981"  # Emerald fallback
            avatar_img = None

            if avatar_bytes:
                try:
                    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((36, 36))
                    avatar_array = np.array(avatar)[..., :3]
                    avg_color = tuple(avatar_array.mean(axis=(0, 1)).astype(int))
                    avg_hex = f"#{avg_color[0]:02x}{avg_color[1]:02x}{avg_color[2]:02x}"
                    
                    # Circular mask
                    mask = Image.new("L", avatar.size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
                    avatar.putalpha(mask)
                    
                    # Optional: Add a subtle glowing ring outline
                    ring = Image.new("RGBA", avatar.size, (0, 0, 0, 0))
                    r_draw = ImageDraw.Draw(ring)
                    r_draw.ellipse((0, 0, avatar.size[0]-1, avatar.size[1]-1), outline=avg_color, width=2)
                    avatar = Image.alpha_composite(avatar, ring)

                    avatar_img = avatar
                except Exception:
                    pass

            bar_colors.append(avg_hex)
            processed_avatars.append(avatar_img)

        y = np.arange(num_users)
        bars = ax.barh(y, counts, color=bar_colors, height=0.5, edgecolor="none")

        ax.set_title(title, color="#FFFFFF", fontsize=18, pad=15)
        ax.set_xlabel(x_label, color="#FFFFFF", fontsize=14)
        ax.set_ylabel("Users", color="#FFFFFF", fontsize=14)
        ax.set_yticks(y)
        ax.set_yticklabels(names, color="#FFFFFF", fontsize=12)
        ax.tick_params(axis="x", colors="#FFFFFF", labelsize=12)

        max_val = max(counts) if counts else 1
        for i, b in enumerate(bars):
            val = counts[i]
            y_pos = b.get_y() + b.get_height() / 2
            avatar_img = processed_avatars[i]

            if avatar_img is not None:
                avatar_box = OffsetImage(avatar_img, zoom=0.7)
                ab = AnnotationBbox(
                    avatar_box, 
                    (val + max_val * 0.02, y_pos), 
                    frameon=False, 
                    xycoords="data", 
                    box_alignment=(0, 0.5)
                )
                ax.add_artist(ab)
                text_x = val + max_val * 0.08
            else:
                text_x = val + max_val * 0.02

            ax.text(text_x, y_pos, str(val), va="center", color="#FFFFFF", fontsize=12)

        ax.set_xlim(0, max_val + max_val * 0.15)
        ax.set_ylim(-0.5, num_users - 0.5)
        
        plt.tight_layout()
        plt.savefig(out_path, bbox_inches="tight", transparent=False, facecolor=fig.get_facecolor())
        plt.close(fig)

async def setup(bot):
    await bot.add_cog(ServerWrapped(bot))
