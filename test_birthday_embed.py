import asyncio
import json
from datetime import datetime

# Import the cog helpers
from cogs.birthdays import BirthdayCog

async def build_preview(date_mmdd="12-24", user_id=1234567890):
    # Instantiate without running BirthdayCog.__init__ (avoids starting background task)
    cog = object.__new__(BirthdayCog)

    # Call helpers
    famous = await cog.fetch_famous_person(date_mmdd)
    events = await cog.fetch_history_events(date_mmdd, max_events=3)
    song = await cog.fetch_song_release(date_mmdd)

    preview = {
        "content": f"🎂 Happy Birthday, <@{user_id}>! 🎉",
        "date": date_mmdd,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "famous": famous,
        "history_events": events,
        "song": song,
    }
    return preview

if __name__ == "__main__":
    date = input('Enter date (MM-DD) [default 12-24]: ').strip() or "12-24"
    data = asyncio.run(build_preview(date))
    print(json.dumps(data, indent=2, ensure_ascii=False))
