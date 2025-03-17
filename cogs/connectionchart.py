import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import networkx as nx
import matplotlib.pyplot as plt
from io import BytesIO
import requests
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image, ImageDraw
from matplotlib.font_manager import FontProperties
import matplotlib.patches as mpatches

class ConnectionChart(commands.Cog):
    DATA_FILE = "connection_chart.json"  # File to store connection data

    def __init__(self, bot):
        self.bot = bot
        self.connections = self.load_connections()

    def load_connections(self):
        if os.path.exists(self.DATA_FILE):
            with open(self.DATA_FILE, "r") as f:
                return json.load(f)
        return []  # Start with an empty list if no file exists

    def save_connections(self):
        with open(self.DATA_FILE, "w") as f:
            json.dump(self.connections, f)

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

        new_conn = {
            "user1": invoking_user.id,
            "user2": user.id,
            "connection": connection.value
        }
        self.connections.append(new_conn)
        self.save_connections()
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
        initial_count = len(self.connections)
        self.connections = [
            conn for conn in self.connections
            if not (
                ((conn["user1"] == invoking_user.id and conn["user2"] == user.id) or 
                 (conn["user1"] == user.id and conn["user2"] == invoking_user.id))
                and conn["connection"].lower() == connection.value.lower()
            )
        ]
        self.save_connections()
        if len(self.connections) < initial_count:
            await interaction.response.send_message(
                f"Removed connection: {invoking_user.display_name} — {connection.value} — {user.display_name}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("No matching connection found.", ephemeral=True)

    @app_commands.command(name="connectionchart", description="Display the user connection chart with avatars")
    async def connectionchart(self, interaction: discord.Interaction):
        # Defer response to allow processing time.
        await interaction.response.defer()

        # Build the graph from stored connections.
        G = nx.Graph()
        for conn in self.connections:
            G.add_node(conn["user1"])
            G.add_node(conn["user2"])
            G.add_edge(conn["user1"], conn["user2"], connection=conn["connection"])

        guild = interaction.guild
        labels = {}
        for node in G.nodes:
            member = guild.get_member(node)
            labels[node] = member.display_name if member else f"User({node})"

        # Use the Kamada-Kawai layout for positioning.
        pos = nx.kamada_kawai_layout(G)

        # Define colors for each connection type.
        conn_colors = {
            "sibling": "blue",
            "friend": "green",
            "roommate": "orange",
            "partner": "red",
            "acquaintance": "gray",
            "cousin": "teal"
        }
        # Assign edge colors based on connection type.
        edge_colors = []
        for (_, _, data) in G.edges(data=True):
            color = conn_colors.get(data.get("connection", "").lower(), "gray")
            edge_colors.append(color)

        # Create a figure with a larger size and transparent background.
        fig, ax = plt.subplots(figsize=(16, 12), facecolor='none')
        ax.set_facecolor('none')

        nx.draw_networkx_edges(
            G, pos, 
            edge_color=edge_colors, 
            width=6, 
            ax=ax,
            arrows=True, 
            arrowstyle='-', 
            connectionstyle='arc3, rad=0.5',
            alpha=0.8
        )


        # Draw nodes invisibly (we'll overlay avatars).
        nx.draw_networkx_nodes(G, pos, node_color='none', ax=ax)

        # Load custom font from arial.ttf.
        font = FontProperties(fname="arial.ttf", size=10)

        # Use the appropriate resampling filter.
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS

        # Overlay high-resolution avatars as circular images.
        for node, (x, y) in pos.items():
            member = guild.get_member(node)
            if member:
                avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                # Request a high-res version (1024x1024)
                if "?" in avatar_url:
                    avatar_url += "&size=1024"
                else:
                    avatar_url += "?size=1024"
                try:
                    response = requests.get(avatar_url)
                    img_data = BytesIO(response.content)
                    avatar_img = Image.open(img_data).convert("RGBA")
                    size = (64, 64)  # Display size for avatars
                    avatar_img = avatar_img.resize(size, resample)
                    # Create a circular mask.
                    mask = Image.new("L", size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, size[0], size[1]), fill=255)
                    avatar_img.putalpha(mask)
                    imagebox = OffsetImage(avatar_img, zoom=1)
                    ab = AnnotationBbox(imagebox, (x, y), frameon=False)
                    ax.add_artist(ab)
                except Exception as e:
                    print(f"Error fetching avatar for user {member.display_name}: {e}")

            # Add the user's display name below the avatar.
            ax.text(
                x, y - 0.12, labels[node],
                fontproperties=font,
                fontsize=10,
                ha='center', va='top',
                color='white',
                bbox=dict(facecolor='black', edgecolor='none', alpha=0.7, boxstyle='round,pad=0.2')
            )

        # Create a clean legend centered below the chart.
        patches = [mpatches.Patch(color=color, label=key.capitalize()) for key, color in conn_colors.items()]
        legend = ax.legend(handles=patches, loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=3, frameon=False, prop=font)
        for text in legend.get_texts():
            text.set_color("white")

        # Add a title based on the guild name.
        plt.title(f"{guild.name} Connection Chart", fontsize=14, color='white', pad=20, fontproperties=font)

        plt.axis('off')
        buf = BytesIO()
        plt.savefig(buf, format='png', transparent=True, bbox_inches='tight', dpi=300)
        buf.seek(0)
        plt.close(fig)
        file = discord.File(fp=buf, filename="connection_chart.png")
        await interaction.followup.send("Here's the connection chart:", file=file)

async def setup(bot):
    await bot.add_cog(ConnectionChart(bot))
