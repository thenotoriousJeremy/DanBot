import sys
import types
import asyncio
import json
import urllib.request
import urllib.parse
import io

# Create minimal dummy `discord` package to allow importing the cog for testing
discord = types.ModuleType("discord")
ext_mod = types.ModuleType("discord.ext")
commands = types.ModuleType("discord.ext.commands")

# minimal Cog base class
class Cog:
    def __init__(self, *args, **kwargs):
        pass

commands.Cog = Cog

# tasks.loop decorator stub
tasks = types.ModuleType("discord.ext.tasks")

def loop(**kwargs):
    def decorator(f):
        class TaskStub:
            def __init__(self, func):
                self.func = func
            def before_loop(self, func2):
                return func2
            def start(self):
                return None
        return TaskStub(f)
    return decorator

tasks.loop = loop

# app_commands.command stub
app_commands = types.ModuleType("discord.app_commands")

def command(**kwargs):
    def deco(f):
        return f
    return deco

app_commands.command = command

# utils module stub
utils = types.ModuleType("discord.utils")

def get(iterable, **kwargs):
    return None

utils.get = get

# attach to modules
discord.ext = ext_mod = types.ModuleType("discord.ext")
ext_mod = ext_mod
ext_mod.commands = commands
ext_mod.tasks = tasks

# minimal top-level names
sys.modules['discord'] = discord
sys.modules['discord.ext'] = ext_mod
sys.modules['discord.ext.commands'] = commands
sys.modules['discord.ext.tasks'] = tasks
sys.modules['discord.app_commands'] = app_commands
sys.modules['discord.utils'] = utils

# Minimal requests shim using urllib for environments without `requests` installed
class _Resp:
    def __init__(self, code, body, headers):
        self.status_code = code
        self._body = body
        self.headers = headers
        self.text = body.decode('utf-8', errors='replace') if isinstance(body, (bytes, bytearray)) else str(body)

    def json(self):
        import json as _json
        try:
            return _json.loads(self.text)
        except Exception:
            return {}

class _RequestsShim:
    def get(self, url, params=None, headers=None, timeout=10):
        try:
            if params:
                url = url + ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers=(headers or {}))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                hdrs = dict(r.getheaders())
                return _Resp(r.getcode(), body, hdrs)
        except Exception as e:
            return _Resp(599, str(e).encode('utf-8'), {})

requests = _RequestsShim()
sys.modules['requests'] = requests

# Add minimal annotation types on the top-level discord module
class Interaction:
    pass

class Member:
    pass

discord.Interaction = Interaction
discord.Member = Member
discord.app_commands = app_commands
discord.utils = utils

# Now import the cog and run the helpers
from cogs.birthdays import BirthdayCog

async def main():
    cog = BirthdayCog(bot=None)
    date = '12-27'
    famous = await cog.fetch_famous_person(date)
    events = await cog.fetch_history_events(date, max_events=3)
    song = await cog.fetch_song_release(date)
    out = {
        'date': date,
        'famous': famous,
        'history_events': events,
        'song': song,
    }
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
