import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import aiohttp
import networkx as nx
import matplotlib.pyplot as plt
from io import BytesIO
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image, ImageDraw
from matplotlib.font_manager import FontProperties
import matplotlib.patches as mpatches
import os
from database import DatabaseManager

class ConnectionChart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="addconnection", description="Add a connection between yourself and another user")
    @app_commands.describe(connection="Type of connection")
    @app_commands.choices(connection=[
        app_commands.Choice(name="Sibling", value="sibling"),
        app_commands.Choice(name="Friend", value="friend"),
        app_commands.Choice(name="Roommate", value="roommate"),
        app_commands.Choice(name="Partner", value="partner"),
        app_commands.Choice(name="Acquaintance", value="acquaintance"),
        app_commands.Choice(name="Cousin", value="cousin")
    ])
    async def addconnection(self, interaction: discord.Interaction, user: discord.Member, connection: app_commands.Choice[str]):
        invoking_user = interaction.user
        if invoking_user.id == user.id:
            await interaction.response.send_message("You cannot create a connection with yourself.", ephemeral=True)
            return

        conn_type = connection.value.lower().strip()

        # Insert connection in database
        async with await DatabaseManager.get_connection() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO connections (user1_id, user2_id, connection) VALUES (?, ?, ?);",
                (invoking_user.id, user.id, conn_type)
            )
            await conn.commit()

        await interaction.response.send_message(
            f"Added connection: {invoking_user.display_name} — {connection.value} — {user.display_name}",
            ephemeral=True
        )

    @app_commands.command(name="removeconnection", description="Remove a connection involving yourself and another user")
    @app_commands.describe(connection="Type of connection")
    @app_commands.choices(connection=[
        app_commands.Choice(name="Sibling", value="sibling"),
        app_commands.Choice(name="Friend", value="friend"),
        app_commands.Choice(name="Roommate", value="roommate"),
        app_commands.Choice(name="Partner", value="partner"),
        app_commands.Choice(name="Acquaintance", value="acquaintance"),
        app_commands.Choice(name="Cousin", value="cousin")
    ])
    async def removeconnection(self, interaction: discord.Interaction, user: discord.Member, connection: app_commands.Choice[str]):
        invoking_user = interaction.user
        conn_type = connection.value.lower().strip()

        async with await DatabaseManager.get_connection() as conn:
            # Check row count before deleting
            async with conn.execute(
                "SELECT COUNT(*) FROM connections WHERE ((user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)) AND connection = ?;",
                (invoking_user.id, user.id, user.id, invoking_user.id, conn_type)
            ) as cursor:
                row = await cursor.fetchone()
                initial_count = row[0] if row else 0

            if initial_count > 0:
                await conn.execute(
                    "DELETE FROM connections WHERE ((user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)) AND connection = ?;",
                    (invoking_user.id, user.id, user.id, invoking_user.id, conn_type)
                )
                await conn.commit()
                await interaction.response.send_message(
                    f"Removed connection: {invoking_user.display_name} — {connection.value} — {user.display_name}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("No matching connection found.", ephemeral=True)

    @app_commands.command(name="connectionchart", description="Display the user connection chart with avatars")
    async def connectionchart(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Fetch connections from SQLite
        async with await DatabaseManager.get_connection() as conn:
            async with conn.execute("SELECT user1_id, user2_id, connection FROM connections;") as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await interaction.followup.send("No connections have been added to the database yet! Use `/addconnection` first.")
            return

        connections = [{"user1": r[0], "user2": r[1], "connection": r[2]} for r in rows]

        # Build the graph
        G = nx.Graph()
        for conn in connections:
            G.add_node(conn["user1"])
            G.add_node(conn["user2"])
            G.add_edge(conn["user1"], conn["user2"], connection=conn["connection"])

        guild = interaction.guild
        labels = {}
        for node in G.nodes:
            member = guild.get_member(node)
            labels[node] = member.display_name if member else f"User({node})"

        # Concurrent Async Avatar Fetching via aiohttp
        async def fetch_avatar(session, member):
            avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
            if "?" in avatar_url:
                avatar_url += "&size=256"
            else:
                avatar_url += "?size=256"
            try:
                async with session.get(avatar_url, timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except Exception as e:
                print(f"[ConnectionChart] Error fetching avatar for {member.display_name}: {e}")
            return None

        node_avatars = {}
        async with aiohttp.ClientSession() as session:
            tasks = []
            node_list = list(G.nodes)
            for node in node_list:
                member = guild.get_member(node)
                if member:
                    tasks.append(fetch_avatar(session, member))
                else:
                    tasks.append(asyncio.sleep(0, result=None)) # Dummy task
            
            avatar_results = await asyncio.gather(*tasks)
            
            for idx, node in enumerate(node_list):
                if avatar_results[idx]:
                    node_avatars[node] = avatar_results[idx]

        # Use Kamada-Kawai layout
        pos = nx.kamada_kawai_layout(G)

        # Offload CPU-Bound Drawing & Rendering to a Background Thread
        try:
            buf = await asyncio.to_thread(
                self._draw_chart, 
                G, pos, labels, node_avatars, guild.name
            )
            file = discord.File(fp=buf, filename="connection_chart.png")
            await interaction.followup.send("Here's the connection chart:", file=file)
        except Exception as e:
            print(f"[ConnectionChart] Error generating connection chart: {e}")
            await interaction.followup.send("An error occurred while rendering the connection chart image.")

    def _draw_chart(self, G, pos, labels, node_avatars, guild_name):
        """Thread-safe drawing function running entirely in an asyncio background thread."""
        conn_colors = {
            "sibling": "#3B82F6",       # Modern blue
            "friend": "#10B981",        # Modern emerald green
            "roommate": "#F59E0B",      # Modern orange
            "partner": "#EF4444",       # Modern soft red
            "acquaintance": "#6B7280",  # Modern gray
            "cousin": "#06B6D4"         # Modern cyan
        }

        edge_colors = []
        for (_, _, data) in G.edges(data=True):
            color = conn_colors.get(data.get("connection", "").lower(), "#6B7280")
            edge_colors.append(color)

        fig, ax = plt.subplots(figsize=(16, 12), facecolor='none')
        ax.set_facecolor('none')

        # Draw curved edges with elegant styling
        nx.draw_networkx_edges(
            G, pos, 
            edge_color=edge_colors, 
            width=6, 
            ax=ax,
            arrows=True, 
            arrowstyle='-', 
            connectionstyle='arc3, rad=0.15',
            alpha=0.8
        )

        nx.draw_networkx_nodes(G, pos, node_color='none', ax=ax)

        # Load font
        font = FontProperties(fname="arial.ttf", size=10)

        # Draw avatars with PIL circular frames and glowing rings
        for node, (x, y) in pos.items():
            avatar_data = node_avatars.get(node)
            if avatar_data:
                try:
                    avatar_img = Image.open(BytesIO(avatar_data)).convert("RGBA")
                    size = (64, 64)
                    avatar_img = avatar_img.resize(size, Image.Resampling.LANCZOS)
                    
                    # Create circular mask
                    mask = Image.new("L", size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, size[0], size[1]), fill=255)
                    
                    # Create circular avatar
                    circle_avatar = Image.new("RGBA", size, (0, 0, 0, 0))
                    circle_avatar.paste(avatar_img, (0, 0), mask)

                    # Draw a border circle around avatar
                    border_img = Image.new("RGBA", (size[0]+6, size[1]+6), (0, 0, 0, 0))
                    b_draw = ImageDraw.Draw(border_img)
                    b_draw.ellipse((0, 0, size[0]+5, size[1]+5), fill=None, outline="#4B5563", width=3) # Slate gray border
                    border_img.paste(circle_avatar, (3, 3), circle_avatar)

                    imagebox = OffsetImage(border_img, zoom=1)
                    ab = AnnotationBbox(imagebox, (x, y), frameon=False)
                    ax.add_artist(ab)
                except Exception as e:
                    print(f"[ConnectionChart] Error styling avatar for node {node}: {e}")

            # Draw labels with glowing round bounds below the avatar
            ax.text(
                x, y - 0.12, labels[node],
                fontproperties=font,
                fontsize=11,
                ha='center', va='top',
                color='white',
                bbox=dict(facecolor='#111827', edgecolor='#374151', alpha=0.9, boxstyle='round,pad=0.3', lw=1.5)
            )

        # Build elegant legend
        patches = [mpatches.Patch(color=color, label=key.capitalize()) for key, color in conn_colors.items()]
        legend = ax.legend(
            handles=patches, 
            loc="upper center", 
            bbox_to_anchor=(0.5, -0.05), 
            ncol=3, 
            frameon=False, 
            prop=font
        )
        for text in legend.get_texts():
            text.set_color("white")

        plt.title(f"{guild_name} Connection Chart", fontsize=16, color='white', pad=25, fontproperties=font)
        plt.axis('off')
        
        buf = BytesIO()
        plt.savefig(buf, format='png', transparent=True, bbox_inches='tight', dpi=180)
        buf.seek(0)
        plt.close(fig)
        return buf

async def setup(bot):
    await bot.add_cog(ConnectionChart(bot))
