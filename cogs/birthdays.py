import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import sqlite3
import requests
from urllib.parse import quote
import random
from typing import List
from urllib.parse import urlencode
import re
import time
import os
import json


class BirthdayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.birthday_check_time = "09:00"  # Set the time for the daily check (24-hour format: HH:MM)
        self.conn = sqlite3.connect('birthdays.db')
        self.create_table()
        self.birthday_reminder.start()

    def create_table(self):
        with self.conn:
            c = self.conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS birthdays (
                user_id INTEGER,
                username TEXT,
                birthday TEXT,
                PRIMARY KEY (user_id, username)
            )''')

    async def fetch_famous_person(self, birthday_str):
        """
        Fetch a famous person born on the given date (MM-DD) using Wikipedia's OnThisDay API
        and return a dict with keys: name, description, extract, thumbnail (url).
        Returns None if nothing found or on error.
        """
        try:
            month, day = birthday_str.split("-")

            def _fetch():
                try:
                    url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/births/{int(month)}/{int(day)}"
                    headers = {"User-Agent": "DanBot/1.0 (https://github.com/thenotoriousJeremy/DanBot)"}
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code != 200:
                        return None
                    data = r.json()

                    # Collect page entries
                    pages = []
                    for entry in data.get("births", []):
                        for p in entry.get("pages", []):
                            pages.append(p)

                    if not pages:
                        return None

                    random.shuffle(pages)
                    # pick first candidate
                    page = pages[0]
                    title = page.get("normalizedtitle") or page.get("title")
                    if not title:
                        return None

                    # fetch summary
                    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
                    rs = requests.get(summary_url, headers=headers, timeout=10)
                    if rs.status_code != 200:
                        return None
                    summary = rs.json()

                    name = summary.get("title") or title
                    extract = summary.get("extract") or summary.get("description") or ""
                    thumbnail = None
                    if summary.get("thumbnail"):
                        thumbnail = summary.get("thumbnail", {}).get("source")

                    return {"name": name, "description": summary.get("description"), "extract": extract, "thumbnail": thumbnail}
                except Exception:
                    return None

            return await asyncio.to_thread(_fetch)
        except Exception:
            return None

    async def fetch_history_events(self, birthday_str, max_events: int = 3):
        """
        Fetch 'This Day in History' events for the given MM-DD from Wikipedia's OnThisDay API.
        Returns a list of strings like 'YEAR — short description'.
        """
        try:
            month, day = birthday_str.split("-")

            def _fetch():
                try:
                    url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{int(month)}/{int(day)}"
                    headers = {"User-Agent": "DanBot/1.0 (https://github.com/thenotoriousJeremy/DanBot)"}
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code != 200:
                        return []
                    data = r.json()

                    events = []
                    for entry in data.get("events", []):
                        year = entry.get("year")
                        text = entry.get("text") or ""
                        # remove any bracketed references
                        text = re.sub(r"\s*\[[^\]]*\]", "", text)
                        # shorten
                        summary = text.strip()
                        if year:
                            events.append(f"{year} — {summary}")
                        else:
                            events.append(summary)
                        if len(events) >= max_events:
                            break

                    return events
                except Exception:
                    return []

            return await asyncio.to_thread(_fetch)
        except Exception:
            return []

    async def fetch_song_release(self, birthday_str):
        """
        Fetch a "song of the day" using the Song Of Today public API (/v2/today).
        Returns a dict: title, description, wiki_url, youtube_search, thumbnail or None.
        """
        try:
            month, day = birthday_str.split("-")
            # lightweight cache in repo
            cache_path = os.path.join(os.path.dirname(__file__), "..", ".cache_song_search.json")
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

            def _fetch():
                headers = {"User-Agent": "DanBot/1.0 (https://github.com/thenotoriousJeremy/DanBot)"}
                now_year = datetime.now().year
                years_back = 30
                mm = int(month)
                dd = int(day)

                # pick a random year in the past `years_back` years
                start = now_year - years_back
                candidate_years = list(range(start, now_year + 1))
                random.shuffle(candidate_years)

                for year in candidate_years:
                    date_full = f"{year:04d}-{mm:02d}-{dd:02d}"
                    if DEBUG:
                        print(f"DEBUG_SONG_SEARCH: trying year {year} -> {date_full}")
                    # Attempt to use the `billboard.py` library first (more reliable than scraping raw HTML)
                    try:
                        import billboard as _bb
                        if DEBUG:
                            print(f"DEBUG_SONG_SEARCH: trying billboard.py for {date_full}")
                        try:
                            chart = _bb.ChartData('hot-100', date=date_full)
                            if chart and len(chart) > 0:
                                top = chart[0]
                                title = getattr(top, 'title', None)
                                artist = getattr(top, 'artist', None)
                                if title:
                                    if DEBUG:
                                        print(f"DEBUG_SONG_SEARCH: billboard.py returned title={title!r} artist={artist!r}")
                                    bb_cache_k = f"billboard:{date_full}"
                                    bb = {"title": title, "artist": artist, "source": "billboard_py", "date": date_full}
                                    _cache_set(bb_cache_k, bb)
                                    return {"title": title, "description": f"{artist or ''} — #1 on the Hot 100 on {date_full}", "wiki_url": f"https://www.billboard.com/charts/hot-100/{date_full}", "youtube_search": "https://www.youtube.com/results?" + urlencode({"search_query": f'"{_clean(title)}" "{_clean(artist or "")}" {year} official video'})}
                        except Exception as _e:
                            if DEBUG:
                                print(f"DEBUG_SONG_SEARCH: billboard.py ChartData error for {date_full}: {_e}")
                    except Exception:
                        # billboard.py not available or failed to import — continue to scraping/fallback
                        pass
                    # 1) Try Billboard chart archive for this date (Hot 100)
                    bb_cache_k = f"billboard:{date_full}"
                    bb = _cache_get(bb_cache_k)
                    if bb is None:
                        try:
                            bb_url = f"https://www.billboard.com/charts/hot-100/{date_full}"
                            r = requests.get(bb_url, headers=headers, timeout=10)
                            if DEBUG:
                                try:
                                    sc = getattr(r, 'status_code', None)
                                except Exception:
                                    sc = None
                                print(f"DEBUG_SONG_SEARCH: billboard GET {bb_url} status={sc}")
                            if r.status_code == 200:
                                html = r.text
                                if DEBUG:
                                    # print a short context around potential markers to aid debugging
                                    marker = None
                                    for key in ['data-rank="1"', 'chart-number-one', 'chart-element__information', 'Hot 100']:
                                        idx = html.find(key)
                                        if idx != -1:
                                            marker = (key, idx)
                                            break
                                    if marker:
                                        key, idx = marker
                                        start = max(0, idx - 200)
                                        end = min(len(html), idx + 400)
                                        snippet = html[start:end]
                                        print(f"DEBUG_SONG_SEARCH: billboard snippet around {key}:\n{snippet}\n---END SNIPPET---")
                                    else:
                                        # try to extract __NEXT_DATA__ JSON blob used by Next.js sites
                                        nd_idx = html.find('<script id="__NEXT_DATA__"')
                                        if nd_idx != -1:
                                            sidx = html.find('>', nd_idx)
                                            eidx = html.find('</script>', sidx)
                                            if sidx != -1 and eidx != -1:
                                                blob = html[sidx+1:eidx]
                                                print(f"DEBUG_SONG_SEARCH: found __NEXT_DATA__ JSON snippet (truncated):\n{blob[:2000]}\n---END BLOB---")
                                            else:
                                                print(f"DEBUG_SONG_SEARCH: __NEXT_DATA__ tag present but content not extractable; printing first 2000 chars:\n{html[:2000]}\n---END SNIPPET---")
                                        else:
                                            print(f"DEBUG_SONG_SEARCH: billboard page did not contain known markers; printing first 2000 chars:\n{html[:2000]}\n---END SNIPPET---")
                                # attempt several patterns to find the #1 song
                                # pattern A: look for 'data-rank="1"' then title/artist
                                m = re.search(r'data-rank="1"[\s\S]{0,300}?<h3[^>]*>([^<]+)</h3>[\s\S]{0,300}?<span[^>]*>([^<]+)</span>', html, re.IGNORECASE)
                                if not m:
                                    # pattern B: look for first occurrence of chart-element__title and chart-element__artist
                                    m = re.search(r'"chart-element__information"[\s\S]{0,400}?"chart-element__information__song">\s*([^<]+)\s*<', html, re.IGNORECASE)
                                if m:
                                    # best-effort extraction
                                    if len(m.groups()) >= 2:
                                        title = m.group(1).strip()
                                        artist = m.group(2).strip()
                                    else:
                                        title = m.group(1).strip()
                                        # try to find artist nearby
                                        a = re.search(re.escape(title) + r'[\s\S]{0,200}?>([^<]{1,100})<', html)
                                        artist = a.group(1).strip() if a else None
                                    bb = {"title": title, "artist": artist, "source": "billboard", "date": date_full}
                                    if DEBUG:
                                        print(f"DEBUG_SONG_SEARCH: billboard matched title={title!r} artist={artist!r}")
                                else:
                                    bb = {"title": None}
                            else:
                                bb = {"title": None}
                        except Exception:
                            bb = {"title": None}
                        _cache_set(bb_cache_k, bb)

                    if bb and bb.get("title"):
                        # found a #1 song
                        title = bb.get("title")
                        artist = bb.get("artist")
                        # build youtube search and a placeholder url (no direct billboard track URL)
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

                    # 2) Fallback: search MusicBrainz releases on this exact date and pick a popular recording
                    mb_cache_k = f"mb_releases:{date_full}"
                    data = _cache_get(mb_cache_k)
                    if data is None:
                        try:
                            mb_release_search = "https://musicbrainz.org/ws/2/release/"
                            params = {"query": f"date:{date_full} AND status:Official", "fmt": "json", "limit": 50}
                            r = requests.get(mb_release_search, params=params, headers=headers, timeout=10)
                            if r.status_code == 200:
                                data = r.json()
                                _cache_set(mb_cache_k, data)
                                if DEBUG:
                                    releases_count = len(data.get('releases', []))
                                    print(f"DEBUG_SONG_SEARCH: musicbrainz search for {date_full} returned {releases_count} releases")
                            else:
                                data = {"releases": []}
                        except Exception:
                            data = {"releases": []}

                    releases = data.get("releases", [])
                    if releases:
                        chosen = releases[0]
                        rel_id = chosen.get("id")
                        if rel_id:
                            rel_cache_k = f"mb_release_detail:{rel_id}"
                            rel_data = _cache_get(rel_cache_k)
                            if rel_data is None:
                                try:
                                    rel_lookup = f"https://musicbrainz.org/ws/2/release/{rel_id}"
                                    rl = requests.get(rel_lookup, params={"fmt": "json", "inc": "recordings+artist-credits"}, headers=headers, timeout=10)
                                    if rl.status_code == 200:
                                        rel_data = rl.json()
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
                                    first = tracks[0]
                                    recording = first.get("recording") or first
                                    first_track = recording
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

                    # polite wait before trying next year
                    time.sleep(0.8)

                return None

            return await asyncio.to_thread(_fetch)
        except Exception:
            return None

    @app_commands.command(name="set_birthday", description="Set a birthday for yourself or another user")
    async def set_birthday(self, interaction: discord.Interaction, target_user: discord.Member = None, date: str = None):
        """
        Save a birthday for yourself or another user. Format: MM-DD.
        """
        if target_user is None:
            target_user = interaction.user  # Default to the user who invoked the command

        if date is None:
            await interaction.response.send_message(
                "You need to provide a date in MM-DD format. Example: `/set_birthday @user 12-25`.",
                ephemeral=True,
            )
            return

        try:
            datetime.strptime(date, '%m-%d')  # Validate date format

            # Save to the database
            with self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO birthdays (user_id, username, birthday) VALUES (?, ?, ?)",
                    (target_user.id, target_user.name, date),
                )
            await interaction.response.send_message(
                f"{target_user.mention}, your birthday has been set to {date}. 🎉",  # Tag the user
                ephemeral=False,
            )
        except ValueError:
            await interaction.response.send_message(
                "Invalid date format. Please use MM-DD (e.g., 12-25).",
                ephemeral=True,
            )

    @app_commands.command(name="when_is", description="Ask when a user's birthday is")
    async def when_is(self, interaction: discord.Interaction, target_user: discord.Member):
        """
        Ask when a user's birthday is.
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT birthday FROM birthdays WHERE user_id = ?", (target_user.id,))
            result = cursor.fetchone()

        if result:
            await interaction.response.send_message(
                f"{target_user.mention}'s birthday is on {result[0]}. 🎂",  # Tag the target user
                ephemeral=False,
            )
        else:
            await interaction.response.send_message(
                f"I don't have a birthday saved for {target_user.mention}. 😔",
                ephemeral=False,
            )
    
    @app_commands.command(name="list_birthdays", description="List all known birthdays")
    async def list_birthdays(self, interaction: discord.Interaction):
        """
        List all saved birthdays in the database.
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT username, birthday FROM birthdays ORDER BY birthday")
            birthdays = cursor.fetchall()

        if birthdays:
            birthday_list = "\n".join(
                [f"🎂 **{username}**: {birthday}" for username, birthday in birthdays]
            )
            await interaction.response.send_message(
                f"Here are all the birthdays I know:\n{birthday_list}", ephemeral=False
            )
        else:
            await interaction.response.send_message(
                "I don't have any birthdays saved yet. 😔", ephemeral=False
            )


    @tasks.loop(hours=24)
    async def birthday_reminder(self):
        today = datetime.now().strftime('%m-%d')
        next_week = (datetime.now() + timedelta(days=7)).strftime('%m-%d')
        channel = discord.utils.get(self.bot.get_all_channels(), name='chat-sponsored-by-raid-shadow-legends')  # Replace with your channel name

        if not channel:
            return

        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT user_id, username, birthday FROM birthdays")
            birthdays = cursor.fetchall()

            for user_id, username, birthday in birthdays:
                user_mention = f"<@{user_id}>"

                if birthday == next_week:
                    # Only send a simple heads-up for the week-before message
                    content = f"🎉 Heads up! {user_mention}'s birthday is coming up in a week!"
                    await channel.send(content)
                elif birthday == today:
                    # For the actual birthday, attempt to fetch a famous person and include an embed
                    content = f"🎂 Happy Birthday, {user_mention}! 🎉"
                    famous = None
                    try:
                        famous = await self.fetch_famous_person(birthday)
                    except Exception as e:
                        print(f"Error fetching famous person for {birthday}: {e}")

                    if famous:
                        embed = discord.Embed(
                            title=f"Also born on this day: {famous.get('name','Unknown')}",
                            description=famous.get('extract',''),
                            color=0x00FF00,
                        )
                        if famous.get('thumbnail'):
                            embed.set_image(url=famous.get('thumbnail'))

                        # Fetch 'This Day in History' events and add as a field
                        try:
                            events = await self.fetch_history_events(birthday, max_events=3)
                            if events:
                                # Join events, ensure field length <= 1024
                                value = "\n".join(events)
                                if len(value) > 1000:
                                    value = value[:997] + "..."
                                embed.add_field(name="This Day in History", value=value, inline=False)
                        except Exception as e:
                            print(f"Error fetching history events for {birthday}: {e}")

                        # Fetch a famous song released this day and add as a field
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
                            print(f"Error fetching song released on {birthday}: {e}")

                        await channel.send(content=content, embed=embed)
                    else:
                        await channel.send(content)

    @birthday_reminder.before_loop
    async def before_birthday_reminder(self):
        await self.bot.wait_until_ready()

        # Calculate the delay until the specified time
        now = datetime.now()
        target_time = datetime.strptime(self.birthday_check_time, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        if now > target_time:
            # If the target time today has already passed, set it for tomorrow
            target_time += timedelta(days=1)

        delay = (target_time - now).total_seconds()
        print(f"Waiting {delay} seconds to start the birthday reminder.")
        await asyncio.sleep(delay)

async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
