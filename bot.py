import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import os
from queue_manager import QueueManager
import bot_commands
import time
from collections import Counter
from discord import app_commands  # Import app_commands
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv("token.env")
TOKEN = os.getenv("TOKEN")
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))  # Load private channel ID from .env

if not TOKEN:
    logging.error("Error: TOKEN environment variable is not set.")
    exit(1)

# Enable necessary bot intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize bot with command prefix and intents
bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize QueueManager
queue_manager = QueueManager()

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user}')
    queue_manager.load_spanner_tracker()
    
    # Dynamically set YOUR_CHANNEL_ID
    await queue_manager.set_channel_id(bot)
    
    # Sync commands
    try:
        await bot.tree.sync()
        logging.info("Commands synced globally.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
    
    # Start the timeout checker
    bot.loop.create_task(queue_manager.check_queue_timeouts(bot))

@bot.tree.command(name="keen", description="Join the queue, optionally with a delay in minutes (up to 6 hours)")
@app_commands.describe(minutes="Optional: Delay in minutes before asking if you're still keen (1-360).")
async def keen(interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 360] = None):
    user = interaction.user.mention
    user_id = interaction.user.id

    # Check if the user is already in the queue
    if user in queue_manager.keen_queue:
        await interaction.response.send_message(f"{user}, you're already in the queue!", ephemeral=True)
        return

    # Handle conditional keen (with minutes)
    if minutes is not None:
        # Add the user to the conditional queue
        queue_manager.conditional_queue[user] = time.time() + (minutes * 60)
        logging.info(f"Added {user} to conditional queue. Will check back in {minutes} minutes.")
        await interaction.response.send_message(f"{user}, you'll be asked if you're keen in {minutes} minutes.", ephemeral=False)

        # Schedule the conditional check
        await asyncio.sleep(minutes * 60)

        # Check if the user is still in the conditional queue (they might have left manually)
        if user in queue_manager.conditional_queue:
            logging.info(f"Checking if {user} is still keen...")
            # Send the message to the private channel and get the message object
            message = await queue_manager.send_message_to_channel(bot, queue_manager.YOUR_CHANNEL_ID, f"{user}, are you still keen? React with ✅ to join the queue or ❌ to decline.")
            
            if message:  # Ensure the message was sent successfully
                await message.add_reaction("✅")
                await message.add_reaction("❌")

                def check(reaction, user):
                    return (
                        reaction.emoji in ["✅", "❌"]  # Correct emoji
                        and user.mention in queue_manager.conditional_queue  # Correct user
                        and reaction.message.id == message.id  # Correct message
                    )

                try:
                    # Wait for the user's reaction with a 5-minute timeout
                    reaction, _ = await bot.wait_for('reaction_add', timeout=300.0, check=check)
                    if reaction.emoji == "✅":
                        # Add the user to the queue
                        await bot_commands.make_keen(interaction, queue_manager)
                        await interaction.followup.send(f"{user} is still keen and has been added to the queue!", ephemeral=False)
                    else:
                        # Mark the user as a spanner
                        queue_manager.spanner_tracker.append((user_id, user))
                        queue_manager.save_spanner_tracker()
                        await interaction.followup.send(f"{user} declined and has been marked as a spanner! :wrench:", ephemeral=False)
                except asyncio.TimeoutError:
                    # Mark the user as a spanner if they don't respond within 5 minutes
                    queue_manager.spanner_tracker.append((user_id, user))
                    queue_manager.save_spanner_tracker()
                    await interaction.followup.send(f"{user} spannered by not responding in time! :wrench:", ephemeral=False)
                finally:
                    # Remove the user from the conditional queue
                    del queue_manager.conditional_queue[user]
            else:
                logging.error(f"Failed to send message to channel {queue_manager.YOUR_CHANNEL_ID}.")
    else:
        # Regular keen behavior (no delay)
        await bot_commands.make_keen(interaction, queue_manager)

@bot.tree.command(name="unkeen", description="Leave the queue")
async def unkeen(interaction: discord.Interaction):
    user = interaction.user.mention
    user_id = interaction.user.id

    if user_id in queue_manager.unkeen_cooldown:
        remaining = queue_manager.unkeen_cooldown[user_id] - time.time()
        if remaining > 0:
            minutes, seconds = divmod(remaining, 60)
            await interaction.response.send_message(f"You're on cooldown! Try again in {int(minutes)}m {int(seconds)}s.", ephemeral=True)
            return

    if user in queue_manager.keen_queue:
        del queue_manager.keen_queue[user]
        await interaction.response.send_message(f"{user} has been removed from the queue.", ephemeral=True)
        if queue_manager.YOUR_CHANNEL_ID is not None:
            await queue_manager.send_message_to_channel(bot, queue_manager.YOUR_CHANNEL_ID, f"{user} is spannering :wrench:")
        else:
            logging.error("YOUR_CHANNEL_ID not set. Cannot send spanner message.")
        queue_manager.unkeen_cooldown[user_id] = time.time() + 300
        queue_manager.spanner_tracker.append((user_id, user))
        queue_manager.save_spanner_tracker()
    else:
        await interaction.response.send_message(f"{user}, you're not in the queue!", ephemeral=True)

@bot.tree.command(name="keeners", description="Show the current queue")
async def keeners(interaction: discord.Interaction):
    if queue_manager.keen_queue or queue_manager.potential_queue:
        queue_list = "\n".join(f"{i+1}. {user}" for i, (user, _) in enumerate(queue_manager.keen_queue.items()))
        potential_list = "\n".join(f"Potential: {user}" for user in queue_manager.potential_queue)
        await interaction.response.send_message(f"Current queue:\n{queue_list}\n\nPotential keens:\n{potential_list}", ephemeral=True)
    else:
        await interaction.response.send_message("The queue is currently empty.", ephemeral=True)

@bot.tree.command(name="spanners", description="Show the list of spannerers and their counts :wrench:")
async def spanners(interaction: discord.Interaction):
    if not queue_manager.spanner_tracker:
        await interaction.response.send_message("No spanners have been recorded yet.", ephemeral=True)
        return

    user_mentions = [mention for _, mention in queue_manager.spanner_tracker]
    spanner_counts = Counter(user_mentions)

    spanner_list = "\n".join(f"{mention}: {count} 🔧" for mention, count in spanner_counts.items())
    await interaction.response.send_message(f"Spanner Tracker:\n{spanner_list}", ephemeral=True)

@bot.tree.command(name="cleartracker", description="Clear the spanner tracker (Admin only)")
async def cleartracker(interaction: discord.Interaction):
    # Check if the user has administrator permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don't have permission to use this command! Only admins can clear the spanner tracker.", ephemeral=True)
        return

    queue_manager.spanner_tracker = []
    queue_manager.save_spanner_tracker()
    await interaction.response.send_message("The spanner tracker has been cleared! Everyone gets a fresh start!", ephemeral=True)

@bot.tree.command(name="spannerhelp", description="Learn how the bot works and what spanners are!")
async def spannerhelp(interaction: discord.Interaction):
    help_message = """
    **Welcome to SpannerBot 🔧** 

Here's how it works:
- Use `/keen` to join the queue. When the queue is full, a ready check will start.
    - Use `/keen` followed by a number to give a conditional keen.
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
    if user in queue_manager.keen_queue:
        await interaction.response.send_message(f"{user}, you're already in the queue! You can't mark yourself as potentially keen.", ephemeral=True)
    else:
        if user in queue_manager.potential_queue:
            queue_manager.potential_queue.remove(user)
            await interaction.response.send_message(f"{user}, you're no longer potentially keen.", ephemeral=True)
        else:
            queue_manager.potential_queue.add(user)
            await interaction.response.send_message(f"{user}, you're now potentially keen! You'll be tagged if the queue is more than half full.", ephemeral=False)

# Command to manually sync commands
@bot.command()
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("Commands synced globally.")

bot.run(TOKEN)