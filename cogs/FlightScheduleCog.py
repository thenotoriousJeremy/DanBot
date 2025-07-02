import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import io
import pdfplumber
import json
import os
from bs4 import BeautifulSoup

class FlightScheduleCog(commands.Cog):
    """
    Cog to scrape the 72-hour flight schedule PDF from Joint Base Andrews
    and notify on new flights once per day, plus a manual slash command.
    """
    BASE_URL = "https://www.amc.af.mil/AMC-Travel-Site/Terminals/CONUS-Terminals/Joint-Base-Andrews-Passenger-Terminal/"
    DATA_FILE = "flight_schedule.json"
    CHECK_INTERVAL_HOURS = 24  # Check once every 24 hours
    TARGET_CHANNEL = "flight-updates"  # change to your channel name or ID

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.flight_data = self._load_data()
        self.daily_check.start()

    def _load_data(self) -> list:
        if os.path.exists(self.DATA_FILE):
            with open(self.DATA_FILE, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return []
        return []

    def _save_data(self):
        with open(self.DATA_FILE, "w") as f:
            json.dump(self.flight_data, f, indent=2)

    def _fetch_pdf_url(self) -> str:
        resp = requests.get(self.BASE_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "72-Hour-Schedule" in href and href.lower().endswith(".pdf"):
                return href if href.startswith("http") else requests.compat.urljoin(self.BASE_URL, href)
        raise RuntimeError("Could not find 72-hour schedule PDF link.")

    def _parse_flights(self, pdf_bytes: bytes) -> list:
        flights = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                # Each flight line: e.g., '1115 Dover AFB, DE 44F'
                for line in text.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3 and parts[0].isdigit():
                        flight = parts[0]
                        arrival = parts[-1]
                        dest = " ".join(parts[1:-1])
                        flights.append({
                            "Flight": flight,
                            "Destination": dest,
                            "Seats": arrival
                        })
        return flights

    def _flight_key(self, flight: dict) -> str:
        return f"{flight.get('Flight')}|{flight.get('Destination')}|{flight.get('Seats')}"

    def _get_new(self, latest: list) -> list:
        old_keys = {self._flight_key(f) for f in self.flight_data}
        return [f for f in latest if self._flight_key(f) not in old_keys]

    @tasks.loop(hours=CHECK_INTERVAL_HOURS)
    async def daily_check(self):
        """Daily task: fetch, parse, and post new flights."""
        await self.bot.wait_until_ready()
        try:
            pdf_url = self._fetch_pdf_url()
            resp = requests.get(pdf_url)
            resp.raise_for_status()
            latest = self._parse_flights(resp.content)
            new_flights = self._get_new(latest)
            if new_flights:
                self.flight_data = latest
                self._save_data()
                channel = discord.utils.get(self.bot.get_all_channels(), name=self.TARGET_CHANNEL)
                if channel:
                    for flight in new_flights:
                        msg = (
                            f"✈️ **New Flight**: {flight['Flight']}\n"
                            f"• To: {flight['Destination']}\n"
                            f"• Seats: {flight['Seats']}"
                        )
                        await channel.send(msg)
        except Exception as e:
            print(f"[FlightScheduleCog] Error in daily_check: {e}")

    @daily_check.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="check_flights", description="Manually check the 72-hour flight schedule.")
    async def manual_check(self, interaction: discord.Interaction):
        """Handles the /check_flights command."""
        await interaction.response.defer()
        try:
            pdf_url = self._fetch_pdf_url()
            resp = requests.get(pdf_url)
            resp.raise_for_status()
            flights = self._parse_flights(resp.content)
            if not flights:
                return await interaction.followup.send("No flights found in the schedule.")
            lines = [f"{i+1}. {f['Flight']} to {f['Destination']} ({f['Seats']})" for i, f in enumerate(flights[:5])]
            await interaction.followup.send("**Upcoming Flights (first 5):**\n" + "\n".join(lines))
        except Exception as e:
            await interaction.followup.send(f"Error during manual check: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(FlightScheduleCog(bot))
