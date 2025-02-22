import discord
from discord.ext import commands
import asyncio
import csv
import os
from collections import Counter
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv("token.env")
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("Error: TOKEN environment variable is not set.")
    exit(1)

# Enable necessary bot intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize bot with command prefix and intents
bot = commands.Bot(command_prefix='!', intents=intents)

# Queue and cooldown management
keen_queue = {}  # {user_mention: join_timestamp}
potential_queue = set()  # Track users who are potentially keen
unkeen_cooldown = {}
spanner_tracker = []
QUEUE_LIMIT = 5
USER_TIMEOUT = 3600  # Auto-remove users after 1 hour
YOUR_CHANNEL_ID = None  # Dynamically determined at runtime

# Function to save spanner tracker data asynchronously
def save_spanner_tracker():
    with open('spanner_tracker.csv', 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['User ID', 'Mention'])
        for user_id, mention in spanner_tracker:
            writer.writerow([user_id, mention])

# Function to load spanner tracker data
def load_spanner_tracker():
    global spanner_tracker
    if os.path.exists('spanner_tracker.csv'):
        try:
            with open('spanner_tracker.csv', 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                next(reader)  # Skip header
                spanner_tracker = [(int(row[0]), row[1]) for row in reader]
        except Exception as e:
            print(f"Error loading spanner tracker: {e}")

# Function to automatically remove inactive users from the queue
async def check_queue_timeouts():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired_users = [user for user, join_time in keen_queue.items() if now - join_time > USER_TIMEOUT]
        
        for user in expired_users:
            del keen_queue[user]
            channel = bot.get_channel(YOUR_CHANNEL_ID)
            if channel:
                await channel.send(f"{user} removed from the queue due to timeout.")

@bot.event
async def on_ready():
    global YOUR_CHANNEL_ID
    print(f'Logged in as {bot.user}')
    load_spanner_tracker()
    
    if not YOUR_CHANNEL_ID:
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if "bot" in channel.name.lower():
                    YOUR_CHANNEL_ID = channel.id
                    break
    
    try:
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        print(f"Synced commands for {len(bot.guilds)} guilds")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    bot.loop.create_task(check_queue_timeouts())

@bot.event
async def on_disconnect():
    print("Bot disconnected! Attempting to reconnect...")

@bot.event
async def on_resumed():
    print("Bot reconnected successfully!")

async def ready_check(interaction: discord.Interaction):
    tag_list = " ".join(keen_queue.keys())
    message = await interaction.channel.send(f"{tag_list} ALL ABOARD THE KEEN TRAIN! React with ✅ if you're ready in the next 10 minutes or face spannering! :wrench:")
    await message.add_reaction("✅")
    
    reacted_users = set()
    
    def check(reaction, user):
        return reaction.emoji == "✅" and user.mention in keen_queue and reaction.message.id == message.id

    try:
        while len(reacted_users) < len(keen_queue):
            reaction, user = await bot.wait_for('reaction_add', timeout=600.0, check=check)
            reacted_users.add(user.mention)
        await interaction.channel.send("Everyone is ready! Have a spanner-free time!")
        keen_queue.clear()
    except asyncio.TimeoutError:
        unreacted_users = [user for user in keen_queue.keys() if user not in reacted_users]
        for user_mention in unreacted_users:
            user_id = int(user_mention.strip('<@!>'))
            spanner_tracker.append((user_id, user_mention))
            save_spanner_tracker()
            await interaction.channel.send(f"{user_mention} spannered by not readying up in time! :wrench:")
        keen_queue.clear()

@bot.tree.command(name="keen", description="Join the queue")
async def keen(interaction: discord.Interaction):
    user = interaction.user.mention
    if user in keen_queue:
        await interaction.response.send_message(f"{user}, you're already in the queue!", ephemeral=True)
    else:
        keen_queue[user] = time.time()
        position = len(keen_queue)
        await interaction.response.send_message(f"{user} has joined the queue at position {position}/{QUEUE_LIMIT}.", ephemeral=False)
        if len(keen_queue) >= QUEUE_LIMIT:
            await ready_check(interaction)
        elif len(keen_queue) > QUEUE_LIMIT // 2:  # More than half full
            await notify_potentials(interaction)

@bot.tree.command(name="unkeen", description="Leave the queue")
async def unkeen(interaction: discord.Interaction):
    user = interaction.user.mention
    user_id = interaction.user.id
    
    if user_id in unkeen_cooldown:
        remaining = unkeen_cooldown[user_id] - time.time()
        if remaining > 0:
            minutes, seconds = divmod(remaining, 60)
            await interaction.response.send_message(f"You're on cooldown! Try again in {int(minutes)}m {int(seconds)}s.", ephemeral=True)
            return
    
    if user in keen_queue:
        del keen_queue[user]
        await interaction.response.send_message(f"{user} has been removed from the queue.", ephemeral=True)
        await interaction.channel.send(f"{user} is spannering :wrench:")
        unkeen_cooldown[user_id] = time.time() + 300
        spanner_tracker.append((user_id, user))
        save_spanner_tracker()
    else:
        await interaction.response.send_message(f"{user}, you're not in the queue!", ephemeral=True)

@bot.tree.command(name="keeners", description="Show the current queue")
async def keeners(interaction: discord.Interaction):
    if keen_queue:
        # Include the user's position in the queue
        queue_list = "\n".join(f"{i+1}. {user}" for i, (user, _) in enumerate(keen_queue.items()))
        await interaction.response.send_message(f"Current queue:\n{queue_list}", ephemeral=True)
    else:
        await interaction.response.send_message("The queue is currently empty.", ephemeral=True)

@bot.tree.command(name="spanners", description="Show the list of spannerers and their counts :wrench:")
async def spanners(interaction: discord.Interaction):
    if not spanner_tracker:
        await interaction.response.send_message("No spanners have been recorded yet.", ephemeral=True)
        return

    user_mentions = [mention for _, mention in spanner_tracker]
    spanner_counts = Counter(user_mentions)

    spanner_list = "\n".join(f"{mention}: {count} 🔧" for mention, count in spanner_counts.items())
    await interaction.response.send_message(f"Spanner Tracker:\n{spanner_list}", ephemeral=True)

@bot.tree.command(name="cleartracker", description="Clear the spanner tracker (Admin only)")
async def cleartracker(interaction: discord.Interaction):
    # Check if the user has administrator permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don't have permission to use this command! Only admins can clear the spanner tracker.", ephemeral=True)
        return

    global spanner_tracker
    spanner_tracker = []
    save_spanner_tracker()
    await interaction.response.send_message("The spanner tracker has been cleared! Everyone gets a fresh start!", ephemeral=True)

@bot.tree.command(name="spannerhelp", description="Learn how the bot works and what spanners are!")
async def spannerhelp(interaction: discord.Interaction):
    help_message = """
    **Welcome to SpannerBot 🔧** 

Here's how it works:
- Use `/keen` to join the queue. When the queue is full, a ready check will start.
- During the ready check, you have **10 minutes** to react with ✅. If you don't, you'll be marked as a **spanner**! 🔧
- Use `/unkeen` to leave the queue, but beware: you'll also be marked as a spanner and put on a 5-minute cooldown.
- Use `/spanners` to see who's been spannered and how many times.
- Use `/cleartracker` to wipe the spanner slate clean (admin only).
- Use `/keeners` to see who's currently in the queue.
    """
    await interaction.response.send_message(help_message, ephemeral=True)

@bot.tree.command(name="p", description="Indicate you're potentially keen")
async def potentially_keen(interaction: discord.Interaction):
    user = interaction.user.mention
    if user in potential_queue:
        potential_queue.remove(user)
        await interaction.response.send_message(f"{user}, you're no longer potentially keen.", ephemeral=True)
    else:
        potential_queue.add(user)
        await interaction.response.send_message(f"{user}, you're now potentially keen! You'll be tagged if the queue is more than half full.", ephemeral=False)

async def notify_potentials(interaction: discord.Interaction):
    if potential_queue:
        tag_list = " ".join(potential_queue)
        await interaction.channel.send(f"Hey {tag_list}, the queue is more than half full! Use `/keen` to join if you're ready! 🚂")

bot.run(TOKEN)
