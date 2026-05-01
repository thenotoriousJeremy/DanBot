# DanBot

DanBot is a modular Discord bot designed to provide a variety of features, including a yearly recap of server activity, managing birthdays, workout tracking, music playback, relationship mapping, and a text-to-speech system. It supports custom commands and features to enhance community interaction.

## Features

### **Server Wrapped**
- **Word Cloud Generation**: Creates a word cloud from messages sent in the server.
- **Activity Heatmap**: Visualizes server activity by hour.
- **Message Count Analysis**: Graphs message counts by user.
- **Word Count Analysis**: Graphs word counts by user.
- **Most Reacted Messages**: Highlights the top messages based on reactions.
- **Longest Messages**: Highlights the longest messages sent in the server.
- **Customizable Reporting**: Allows you to adjust the number of top messages for various features.
- **Caching**: Uses caching to minimize API calls and optimize performance.

### **Birthday Tracker**
- **Set Birthday**: Allows users to set their birthdays.
- **Birthday Reminders**: Notifies the server when a user's birthday is approaching or on the day.
- **List Birthdays**: Provides a list of all known birthdays in the server.

### **Workout Tracker**
- **Weekly Workout Goals**: Users can set weekly workout goals.
- **Workout Logging**: Tracks and logs user workouts via confirmation in a specific thread.
- **Leaderboard**: Displays the leaderboard of users based on workouts logged.
- **Weekly Reset with Demeaning Messages**: At the weekly reset, the bot sends demeaning messages to users who didn’t meet their goal. If a user misses their goal for too many consecutive weeks, they must react with 👍 within one week to remain in the tracker. (Workouts are kept even if tracking stops.)

### **Music**
- **YouTube Music Playback**: Play music directly from YouTube using modern, reliable methods.
- **Queue System**: If a song is already playing, new tracks are added to the queue.
- **Slash Commands**: Use slash commands such as `/join`, `/play`, `/skip`, `/queue`, `/stop`, and `/leave` for controlling music playback.
- **yt-dlp & FFmpeg Integration**: Uses the yt-dlp library to extract audio and FFmpeg (with a locally specified `ffmpeg.exe`) for audio streaming.
- **Search Support**: If a plain text query is provided instead of a URL, the bot automatically searches YouTube and plays the first result.

### **Relationship Tree**
- **User-Editable Network Mapping**: Create and edit connections between users to build a visual network (or "tree") of relationships.
- **Add/Remove Connections**: Use slash commands such as `/addconnection` and `/removeconnection` to manage user connections.
- **Graphical Display**: Generate a visual representation of the network using NetworkX and Matplotlib.
- **Customizable Labels and Colors**: Display user avatars and names on the graph with different edge colors representing different types of connections (for example, sibling, friend, roommate, partner, acquaintance, cousin).

## Installation

1. **Clone the Repository**  
   Clone this repository to your local machine:

   ```bash
   git clone https://github.com/thenotoriousJeremy/DanBot.git
   cd DanBot
   ```

2. **Install Dependencies**  
   Use `pip` to install the required libraries:

   ```bash
   pip install -r requirements.txt
   ```

3. **Set Up the Bot**

   - Create a bot on the [Discord Developer Portal](https://discord.com/developers/applications).
   - Copy the bot token.
   - Create a `.env` file in the project directory and add your bot token along with any additional tokens (e.g. for Fish Speech, OpenAI):

     ```env
     DISCORD_TOKEN=your_bot_token
     OPENAI_TOKEN=your_openai_token (optional)
     WORDLE_CHANNEL_ID=your_wordle_channel_id (optional)
     WORKOUT_CHANNEL_ID=your_workout_channel_id (optional)
     ```

4. **Run the Bot**  
   Start the bot:

   ```bash
   python bot.py
   ```

### Docker

DanBot is container-ready and can be launched by passing only environment variables.

**Note for Voice Features**: Music functionality requires outbound UDP connections (ports 50000-65535) for Discord voice. Ensure your Docker network configuration allows UDP traffic.

Build the container:

```bash
docker build -t danbot .
```

Run the container with your token:

```bash
docker run -d \
  --name danbot \
  -e DISCORD_TOKEN=your_bot_token \
  -e DATA_DIR=/app/data \
  -v $(pwd)/data:/app/data \
  danbot
```

If you want persistent storage for generated files or local config, mount the repo directory or specific files into `/app`.

### Docker Compose

Alternatively, you can use Docker Compose to run DanBot. The project includes a `docker-compose.yml` file that will automatically build the container and use your `.env` file for configuration.

```yaml
version: '3.8'

services:
  danbot:
    image: ghcr.io/thenotoriousjeremy/danbot:latest
    container_name: danbot
    environment:
      # Required Variables
      - DISCORD_TOKEN=your_bot_token
      
      # Optional Variables
      # - OPENAI_TOKEN=your_openai_token
      # - WORKOUT_CHANNEL_ID=1327019216510910546
      # - WORDLE_CHANNEL_ID=708795613575249941
      
      # Data Directory Configuration
      - DATA_DIR=/app/data
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

To start the bot using Docker Compose, run:

```bash
docker-compose up -d
```

## Commands

### **Server Wrapped**
- `/server_wrapped`: Generate a detailed server activity report for the current year.

### **Birthday Tracker**
- `/set_birthday`: Set your birthday or another user’s birthday in MM-DD format.
- `/when_is`: Ask when a user's birthday is.
- `/list_birthdays`: List all saved birthdays in the server.

### **Workout Tracker**
- `/set_goal`: Set a weekly workout goal.
- `/opt_out`: Opt out of the workout tracker.
- `/leaderboard`: View the all-time workout leaderboard.
- `/my_workouts`: Check how many workouts you've logged this week.

### **Music**
- `/join`: Bot joins your current voice channel.
- `/play <query>`: Plays a YouTube URL or search query. If a song is already playing, it is added to the queue.
- `/skip`: Skips the current song.
- `/queue`: Displays the current music queue.
- `/stop`: Stops playback and clears the music queue.
- `/leave`: Disconnects the bot from the voice channel.

### **Relationship Tree**
- `/addconnection`: Add a connection between yourself and another user.
- `/removeconnection`: Remove a connection between yourself and another user.
- `/connectionchart`: Display a visual chart of user connections with avatars and custom edge colors.

## Configuration

- **Cache Expiry (Server Wrapped)**: Modify `CACHE_EXPIRY` in `ServerWrapped` for server data caching duration.
- **Workout Tracker Thread**: Set `WORKOUT_CHANNEL_ID` in `.env` or in the container environment.
- **Wordle Channel**: Set `WORDLE_CHANNEL_ID` in `.env` or in the container environment.
- **FFmpeg Setup (Music)**: The music cog will use `FFMPEG_PATH` if set, otherwise it falls back to any `ffmpeg` binary on PATH or the local `ffmpeg.exe` file.
- **Authentication for Age-Restricted YouTube Videos (Music)**: Set `YTDLP_COOKIE_FILE` in `.env` if you need a cookies file.

## How to Use

### **For End Users**
1. **Invite DanBot to Your Server**
   - Obtain the bot's invite link from the server admin or bot owner.
   - Ensure you have the "Manage Server" permission to invite the bot.

2. **Set Up Permissions**
   - Grant DanBot the following permissions:
     - **Read Message History**
     - **Send Messages**
     - **Attach Files**
     - **Embed Links**
     - **Connect and Speak** (for Music features).

3. **Use Commands**
   - Type `/` in any server channel to view all available slash commands.
   - Example usage:
     - `/server_wrapped`: View the server's yearly activity report.
     - `/set_birthday 12-25`: Set your birthday to December 25th.
     - `/join` & `/play`: Use music commands to play YouTube music.
     - `/addconnection` & `/connectionchart`: Manage and view your connection network.

4. **Track Workouts**
   - Use `/set_goal` to set your weekly workout goal.
   - Log workouts by posting a workout image in the specified thread and confirming the post.
   - At weekly reset, demeaning messages will be sent if you miss your goal. If you miss too many weeks consecutively, you'll need to react with 👍 within one week to remain in the tracker.

5. **Birthday Notifications**
   - Set your birthday with `/set_birthday` to receive special mentions on your day!

6. **Enjoy Interactive Features**
   - Enjoy fun visuals with commands like `/server_wrapped` or listen to music using `/play`.

### **For Server Admins**
- Ensure DanBot has access to the necessary channels.
- Designate a specific thread or channel for logging workouts (used by the Workout Tracker cog).
- Confirm that the Music and Relationship Tree cogs are loaded and configured appropriately.

## Contributing

Contributions are welcome! If you have suggestions for new features or find a bug, feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

---

This updated README now includes sections for Music and Relationship Tree along with all of your existing features. Let me know if you need any further adjustments!