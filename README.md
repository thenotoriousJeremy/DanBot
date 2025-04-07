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

### **Fish Speech**
- **Text-to-Speech (TTS)**: Generates TTS audio from input text using the Fish Speech API.
- **Voice Channel Integration**: Plays the generated audio in a Discord voice channel.
- **Dynamic Commands**: Commands like `/say` to generate and play TTS and `/leave` to disconnect from the voice channel.

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
     FISH_TOKEN=your_fish_token (optional)
     OPENAI_TOKEN=your_openai_token (optional)
     ```

4. **Run the Bot**  
   Start the bot:

   ```bash
   python bot.py
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

### **Fish Speech**
- `/say`: Generate TTS from text and play it in the voice channel.
- `/leave`: Make the bot leave the voice channel.

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
- **Workout Tracker Thread**: Replace `SPECIFIC_THREAD_ID` in `WorkoutTracker` with your specific thread ID.
- **TTS Configuration**: Ensure `FISH_TOKEN` and `MODEL_ID` are correctly set in the `.env` file if using TTS.
- **FFmpeg Setup (Music)**: Place `ffmpeg.exe` in your main folder or update the path in the Music cog if needed.
- **Authentication for Age-Restricted YouTube Videos (Music)**: Export your YouTube cookies (using an extension like cookies.txt) and update the `yt-dlp` options if necessary.

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
     - **Connect and Speak** (for TTS and Music features).

3. **Use Commands**
   - Type `/` in any server channel to view all available slash commands.
   - Example usage:
     - `/server_wrapped`: View the server's yearly activity report.
     - `/set_birthday 12-25`: Set your birthday to December 25th.
     - `/say Hello everyone!`: Generate TTS audio and play it in a voice channel.
     - `/join` & `/play`: Use music commands to play YouTube music.
     - `/addconnection` & `/connectionchart`: Manage and view your connection network.

4. **Track Workouts**
   - Use `/set_goal` to set your weekly workout goal.
   - Log workouts by posting a workout image in the specified thread and confirming the post.
   - At weekly reset, demeaning messages will be sent if you miss your goal. If you miss too many weeks consecutively, you'll need to react with 👍 within one week to remain in the tracker.

5. **Birthday Notifications**
   - Set your birthday with `/set_birthday` to receive special mentions on your day!

6. **Enjoy Interactive Features**
   - Generate TTS audio and fun visuals with commands like `/say` and `/server_wrapped`.

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