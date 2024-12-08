Server Wrapped Bot
==================

Server Wrapped is a Discord bot designed to provide a yearly recap of server activity. It analyzes your server's messages to create detailed reports with activity heatmaps, word clouds, and insights like most reacted messages, longest messages, and more. It's a fun and interactive way to reflect on the past year with your community!

Features
--------

-   **Word Cloud Generation**: Creates a word cloud from messages sent in the server.
-   **Activity Heatmap**: Visualizes server activity by hour.
-   **Message Count Analysis**: Graphs message counts by user.
-   **Word Count Analysis**: Graphs word counts by user.
-   **Most Reacted Messages**: Highlights the top messages based on reactions.
-   **Longest Messages**: Highlights the longest messages sent in the server.
-   **Customizable Reporting**: Allows you to adjust the number of top messages for various features.
-   **Caching**: Uses caching to minimize API calls and optimize performance.

Installation
------------

1.  **Clone the Repository**\
    Clone this repository to your local machine:

    `git clone https://github.com/thenotoriousJeremy/DanBot.git
    cd server-wrapped-bot`

2.  **Install Dependencies**\
    Use `pip` to install the required libraries:

    `pip install -r requirements.txt`

3.  **Set Up the Bot**

    -   Create a bot on the Discord Developer Portal.
    -   Copy the bot token.
    -   Create a `.env` file in the project directory and add your bot token:

        `DISCORD_TOKEN=your_bot_token`

4.  **Run the Bot**\
    Start the bot:

    `python bot.py`

Commands
--------

### `/server_wrapped`

Generate a detailed server activity report for the current year. The report includes:

-   **Word Cloud**: A visualization of the most common words used in the server.
-   **Activity Heatmap**: A chart showing the server's most active hours.
-   **Message Count Graph**: A graph showing the number of messages sent by each user.
-   **Word Count Graph**: A graph showing the number of words sent by each user.
-   **Most Reacted Messages**: A list of messages with the highest number of reactions.
-   **Longest Messages**: A list of the longest messages sent in the server.

#### Usage

Type `/server_wrapped` in any server channel where the bot has permissions. The bot will analyze the server's activity and generate the report.

#### Permissions

Ensure the bot has the following permissions:

-   **Read Message History**
-   **Send Messages**
-   **Attach Files**
-   **Embed Links**

Configuration
-------------

### Adjusting Cache Expiry

By default, cached data expires after 24 hours. To change this, modify the `CACHE_EXPIRY` value in the `ServerWrapped` class:

`CACHE_EXPIRY = timedelta(hours=24)  # Change to desired duration`

### Customizing the Number of Top Messages

You can adjust the number of messages displayed in the "Most Reacted Messages" and "Longest Messages" sections by editing the `top_n` parameter in the respective functions:

`most_reacted_messages = await self.generate_most_reacted_messages(guild, reaction_counts, top_n=10)
longest_messages = await self.generate_longest_messages(guild, messages, top_n=10)`

Known Issues and Troubleshooting
--------------------------------

-   **Rate Limiting**: If the bot processes a large server, it may hit Discord's rate limits. The bot includes automatic delay mechanisms to minimize this.
-   **Permission Errors**: Ensure the bot has access to all channels you want it to analyze.
-   **Cached Data Issues**: If cached data causes issues, delete the `server_wrapped_cache.json` file in the bot's directory to reset the cache.

Contributing
------------

Contributions are welcome! If you have suggestions for new features or find a bug, feel free to open an issue or submit a pull request.

License
-------

This project is licensed under the MIT License. See the `LICENSE` file for details.
