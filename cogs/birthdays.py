import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import aiohttp
from urllib.parse import quote, urlencode
import random
import re
import os
import json
from database import DatabaseManager

class BirthdayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.birthday_check_time = "09:00"  # Time for daily check (24-hour format: HH:MM)
        self.birthday_reminder.start()

    async def fetch_famous_person(self, birthday_str):
        """
        Fetch a famous person born on the given date (MM-DD) using Wikipedia's OnThisDay API
        asynchronously and return a dict with keys: name, description, extract, thumbnail (url).
        """
        try:
            month, day = birthday_str.split("-")
            url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/births/{int(month)}/{int(day)}"
            headers = {"User-Agent": "DanBot/1.0 (https://github.com/thenotoriousJeremy/DanBot)"}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()

            # Collect page entries
            pages = []
            for entry in data.get("births", []):
                for p in entry.get("pages", []):
                    pages.append(p)

            if not pages:
                return None

            random.shuffle(pages)
            page = pages[0]
            title = page.get("normalizedtitle") or page.get("title")
            if not title:
                return None

            # Fetch summary
            summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
            async with aiohttp.ClientSession() as session:
                async with session.get(summary_url, headers=headers, timeout=10) as rs:
                    if rs.status != 200:
                        return None
                    summary = await rs.json()

            name = summary.get("title") or title
            extract = summary.get("extract") or summary.get("description") or ""
            thumbnail = None
            if summary.get("thumbnail"):
                thumbnail = summary.get("thumbnail", {}).get("source")

            return {
                "name": name, 
                "description": summary.get("description"), 
                "extract": extract, 
                "thumbnail": thumbnail
            }
        except Exception as e:
            print(f"[Birthdays] Error fetching famous person for {birthday_str}: {e}")
            return None

    async def fetch_history_events(self, birthday_str, max_events: int = 3):
        """
        Fetch 'This Day in History' events for the given MM-DD from Wikipedia's OnThisDay API asynchronously.
        """
        try:
            month, day = birthday_str.split("-")
            url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{int(month)}/{int(day)}"
            headers = {"User-Agent": "DanBot/1.0 (https://github.com/thenotoriousJeremy/DanBot)"}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()

            events = []
            for entry in data.get("events", []):
                year = entry.get("year")
                text = entry.get("text") or ""
                text = re.sub(r"\s*\[[^\]]*\]", "", text)
                summary = text.strip()
                if year:
                    events.append(f"{year} — {summary}")
                else:
                    events.append(summary)
                if len(events) >= max_events:
                    break

            return events
        except Exception as e:
            print(f"[Birthdays] Error fetching history events for {birthday_str}: {e}")
            return []

    async def fetch_song_release(self, birthday_str):
        """
        Fetch a "song of the day" using Billboard or MusicBrainz asynchronously.
        """
        try:
            month, day = birthday_str.split("-")
            cache_path = os.path.join(os.getenv("DATA_DIR", "."), ".cache_song_search.json")
            try:
                cache_path = os.path.abspath(cache_path)
                if os.path.exists(cache_path):
                    with open(cache_path, "r", encoding="utf-8") as fh:
                        _CACHE = json.load(fh)
                else:
                    _CACHE = {}
            except Exception:
                _CACHE = {}

            DEBUG = os.environ.get("DEBUG_SONG_SEARCH", "0") in ("1", "true", "True")

            def _cache_get(k):
                return _CACHE.get(k)

            def _cache_set(k, v):
                try:
                    _CACHE[k] = v
                    with open(cache_path, "w", encoding="utf-8") as fh:
                        json.dump(_CACHE, fh)
                except Exception:
                    pass

            def _clean(s: str) -> str:
                if not s:
                    return ""
                s2 = re.sub(r"[\(\[].*?[\)\]]", "", s)
                s2 = re.sub(r"\s+", " ", s2).strip()
                return s2

            async def _fetch():
                headers = {"User-Agent": "DanBot/1.0 (https://github.com/thenotoriousJeremy/DanBot)"}
                now_year = datetime.now().year
                years_back = 30
                mm = int(month)
                dd = int(day)

                start = now_year - years_back
                candidate_years = list(range(start, now_year + 1))
                random.shuffle(candidate_years)

                for year in candidate_years:
                    date_full = f"{year:04d}-{mm:02d}-{dd:02d}"
                    if DEBUG:
                        print(f"DEBUG_SONG_SEARCH: trying year {year} -> {date_full}")
                    
                    # 1) Try Billboard chart via scraping
                    bb_cache_k = f"billboard:{date_full}"
                    bb = _cache_get(bb_cache_k)
                    if bb is None:
                        try:
                            bb_url = f"https://www.billboard.com/charts/hot-100/{date_full}"
                            async with aiohttp.ClientSession() as session:
                                async with session.get(bb_url, headers=headers, timeout=10) as r:
                                    if r.status == 200:
                                        html = await r.text()
                                        m = re.search(r'data-rank="1"[\s\S]{0,300}?<h3[^>]*>([^<]+)</h3>[\s\S]{0,300}?<span[^>]*>([^<]+)</span>', html, re.IGNORECASE)
                                        if not m:
                                            m = re.search(r'"chart-element__information"[\s\S]{0,400}?"chart-element__information__song">\s*([^<]+)\s*<', html, re.IGNORECASE)
                                        
                                        if m:
                                            if len(m.groups()) >= 2:
                                                title = m.group(1).strip()
                                                artist = m.group(2).strip()
                                            else:
                                                title = m.group(1).strip()
                                                artist = None
                                            bb = {"title": title, "artist": artist, "source": "billboard", "date": date_full}
                                        else:
                                            bb = {"title": None}
                                    else:
                                        bb = {"title": None}
                        except Exception:
                            bb = {"title": None}
                        _cache_set(bb_cache_k, bb)

                    if bb and bb.get("title"):
                        title = bb.get("title")
                        artist = bb.get("artist")
                        q = []
                        if title:
                            q.append(f'"{_clean(title)}"')
                        if artist:
                            q.append(f'"{_clean(artist)}"')
                        q.append(str(year))
                        q.append("official video")
                        youtube_search = "https://www.youtube.com/results?" + urlencode({"search_query": " ".join(q)})
                        description = f"{artist or ''} — #1 on the Hot 100 on {date_full}"
                        return {"title": title, "description": description, "wiki_url": f"https://www.billboard.com/charts/hot-100/{date_full}", "youtube_search": youtube_search}

                    # 2) Fallback: MusicBrainz release search
                    mb_cache_k = f"mb_releases:{date_full}"
                    data = _cache_get(mb_cache_k)
                    if data is None:
                        try:
                            mb_release_search = "https://musicbrainz.org/ws/2/release/"
                            params = {"query": f"date:{date_full} AND status:Official", "fmt": "json", "limit": 50}
                            async with aiohttp.ClientSession() as session:
                                async with session.get(mb_release_search, params=params, headers=headers, timeout=10) as r:
                                    if r.status == 200:
                                        data = await r.json()
                                        _cache_set(mb_cache_k, data)
                                    else:
                                        data = {"releases": []}
                        except Exception:
                            data = {"releases": []}

                    releases = data.get("releases", []) if data else []
                    if releases:
                        chosen = releases[0]
                        rel_id = chosen.get("id")
                        if rel_id:
                            rel_cache_k = f"mb_release_detail:{rel_id}"
                            rel_data = _cache_get(rel_cache_k)
                            if rel_data is None:
                                try:
                                    rel_lookup = f"https://musicbrainz.org/ws/2/release/{rel_id}"
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(rel_lookup, params={"fmt": "json", "inc": "recordings+artist-credits"}, headers=headers, timeout=10) as rl:
                                            if rl.status == 200:
                                                rel_data = await rl.json()
                                                _cache_set(rel_cache_k, rel_data)
                                            else:
                                                rel_data = {}
                                except Exception:
                                    rel_data = {}

                            media = rel_data.get("media") or chosen.get("media") or []
                            first_track = None
                            for m in media:
                                tracks = m.get("tracks") or m.get("track-list") or []
                                if tracks:
                                    first_track = tracks[0].get("recording") or tracks[0]
                                    break

                            if first_track:
                                title = first_track.get("title") or chosen.get("title")
                                artists = rel_data.get("artist-credit") or chosen.get("artist-credit") or []
                                artist_name = None
                                if artists:
                                    parts = [a.get("name") or a.get("artist", {}).get("name") for a in artists]
                                    artist_name = ", ".join([p for p in parts if p])
                                rec_id = first_track.get("id")
                                mb_link = f"https://musicbrainz.org/recording/{rec_id}" if rec_id else f"https://musicbrainz.org/release/{rel_id}"
                                clean_title = _clean(title)
                                clean_artist = _clean(artist_name or "")
                                parts = []
                                if clean_title:
                                    parts.append(f'"{clean_title}"')
                                if clean_artist:
                                    parts.append(f'"{clean_artist}"')
                                parts.append(str(year))
                                parts.append("official video")
                                query_str = " ".join(parts).strip()
                                youtube_search = "https://www.youtube.com/results?" + urlencode({"search_query": query_str})
                                description = f"{artist_name or ''} — Released {date_full}"
                                return {"title": title, "description": description, "wiki_url": mb_link, "youtube_search": youtube_search}

                    # Non-blocking wait before checking the next year to avoid rate limits
                    await asyncio.sleep(0.8)

                return None

            return await _fetch()
        except Exception as e:
            print(f"[Birthdays] Error in fetch_song_release: {e}")
            return None

    @app_commands.command(name="set_birthday", description="Set a birthday for yourself or another user")
    async def set_birthday(self, interaction: discord.Interaction, target_user: discord.Member = None, date: str = None):
        """Save a birthday for yourself or another user. Format: MM-DD."""
        if target_user is None:
            target_user = interaction.user

        if date is None:
            await interaction.response.send_message(
                "You need to provide a date in MM-DD format. Example: `/set_birthday @user 12-25`.",
                ephemeral=True,
            )
            return

        try:
            datetime.strptime(date, '%m-%d')  # Validate date format

            # Save asynchronously to SQLite
            async with await DatabaseManager.get_connection() as conn:
                await conn.execute(
                    "INSERT OR REPLACE INTO birthdays (user_id, username, birthday) VALUES (?, ?, ?);",
                    (target_user.id, target_user.name, date)
                )
                await conn.commit()

            await interaction.response.send_message(
                f"{target_user.mention}, your birthday has been set to {date}. 🎉",
                ephemeral=False,
            )
        except ValueError:
            await interaction.response.send_message(
                "Invalid date format. Please use MM-DD (e.g., 12-25).",
                ephemeral=True,
            )

    @app_commands.command(name="when_is", description="Ask when a user's birthday is")
    async def when_is(self, interaction: discord.Interaction, target_user: discord.Member):
        """Ask when a user's birthday is."""
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT birthday FROM birthdays WHERE user_id = ?;", (target_user.id,)) as cursor:
                result = await cursor.fetchone()

        if result:
            await interaction.response.send_message(
                f"{target_user.mention}'s birthday is on {result[0]}. 🎂",
                ephemeral=False,
            )
        else:
            await interaction.response.send_message(
                f"I don't have a birthday saved for {target_user.mention}. 😔",
                ephemeral=False,
            )
    
    @app_commands.command(name="list_birthdays", description="List all known birthdays")
    async def list_birthdays(self, interaction: discord.Interaction):
        """List all saved birthdays in the database."""
        await interaction.response.defer()
        
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT username, birthday FROM birthdays ORDER BY birthday;") as cursor:
                birthdays = await cursor.fetchall()

        if birthdays:
            birthday_list = "\n".join(
                [f"🎂 **{username}**: {birthday}" for username, birthday in birthdays]
            )
            
            msg = f"Here are all the birthdays I know:\n{birthday_list}"
            if len(msg) > 2000:
                chunks = [msg[i:i+1999] for i in range(0, len(msg), 1999)]
                for i, chunk in enumerate(chunks):
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(msg)
        else:
            await interaction.followup.send("I don't have any birthdays saved yet. 😔")

    @tasks.loop(hours=24)
    async def birthday_reminder(self):
        today = datetime.now().strftime('%m-%d')
        next_week = (datetime.now() + timedelta(days=7)).strftime('%m-%d')

        # Robust Channel Loading with multiple fallbacks
        channel_env = os.getenv("BIRTHDAY_CHANNEL_ID")
        channel = None
        if channel_env:
            try:
                channel = self.bot.get_channel(int(channel_env)) or await self.bot.fetch_channel(int(channel_env))
            except Exception:
                pass
        
        if not channel:
            for name in ['birthdays', 'birthday', 'general', 'chat', 'chat-sponsored-by-raid-shadow-legends']:
                channel = discord.utils.get(self.bot.get_all_channels(), name=name)
                if channel:
                    break

        if not channel:
            for g in self.bot.guilds:
                channel = g.system_channel or (g.text_channels[0] if g.text_channels else None)
                if channel:
                    break

        if not channel:
            print("[Birthdays] Error: Could not find any suitable text channel for birthday announcements.")
            return

        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT user_id, username, birthday FROM birthdays;") as cursor:
                birthdays = await cursor.fetchall()

        for user_id, username, birthday in birthdays:
            user_mention = f"<@{user_id}>"

            if birthday == next_week:
                content = f"🎉 Heads up! {user_mention}'s birthday is coming up in a week!"
                await channel.send(content)
            elif birthday == today:
                content = f"🎂 Happy Birthday, {user_mention}! 🎉"
                famous = await self.fetch_famous_person(birthday)

                if famous:
                    embed = discord.Embed(
                        title=f"Also born on this day: {famous.get('name','Unknown')}",
                        description=famous.get('extract',''),
                        color=0x00FF00,
                    )
                    if famous.get('thumbnail'):
                        embed.set_image(url=famous.get('thumbnail'))

                    # Fetch 'This Day in History' events
                    try:
                        events = await self.fetch_history_events(birthday, max_events=3)
                        if events:
                            value = "\n".join(events)
                            if len(value) > 1000:
                                value = value[:997] + "..."
                            embed.add_field(name="This Day in History", value=value, inline=False)
                    except Exception as e:
                        print(f"[Birthdays] Error fetching history events: {e}")

                    # Fetch famous song release
                    try:
                        song = await self.fetch_song_release(birthday)
                        if song:
                            song_title = song.get('title')
                            wiki = song.get('wiki_url')
                            yt = song.get('youtube_search')
                            song_value = f"[{song_title}]({wiki})"
                            if yt:
                                song_value += f" — Listen: {yt}"
                            if len(song_value) > 1000:
                                song_value = song_value[:997] + "..."
                            embed.add_field(name="Famous song released this day", value=song_value, inline=False)
                    except Exception as e:
                        print(f"[Birthdays] Error fetching song release: {e}")

                    await channel.send(content=content, embed=embed)
                else:
                    await channel.send(content)

    @birthday_reminder.before_loop
    async def before_birthday_reminder(self):
        await self.bot.wait_until_ready()

        now = datetime.now()
        target_time = datetime.strptime(self.birthday_check_time, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        if now > target_time:
            target_time += timedelta(days=1)

        delay = (target_time - now).total_seconds()
        print(f"[Birthdays] Waiting {delay:.1f} seconds to start the birthday reminder.")
        await asyncio.sleep(delay)

async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
