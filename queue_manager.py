import discord
import csv
import os
import time
from collections import Counter
import logging
import asyncio
from dotenv import load_dotenv  # Import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv("token.env")

class QueueManager:
    def __init__(self):
        self.keen_queue = {}  # {user_mention: join_timestamp}
        self.potential_queue = set()  # Track users who are potentially keen
        self.conditional_queue = {}  # {user_mention: expiry_timestamp}
        self.unkeen_cooldown = {}
        self.spanner_tracker = []
        self.QUEUE_LIMIT = 5
        self.USER_TIMEOUT = 3600  # Auto-remove users after 1 hour
        self.YOUR_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))  # Load private channel ID from .env
        self.ready_check_active = False  # Flag to track if a ready check is active

    async def set_channel_id(self, bot):
        """Dynamically set the channel ID for notifications."""
        # If YOUR_CHANNEL_ID is already set (from .env), skip dynamic setting
        if self.YOUR_CHANNEL_ID:
            logging.info(f"Using private channel ID from .env: {self.YOUR_CHANNEL_ID}")
            return
        
        # Fallback to other channels if PRIVATE_CHANNEL_ID is not set in .env
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if "bot" in channel.name.lower():
                    self.YOUR_CHANNEL_ID = channel.id
                    logging.info(f"Set YOUR_CHANNEL_ID to {self.YOUR_CHANNEL_ID} (Channel: {channel.name})")
                    return
        
        for guild in bot.guilds:
            if guild.system_channel:
                self.YOUR_CHANNEL_ID = guild.system_channel.id
                logging.info(f"Fallback: Set YOUR_CHANNEL_ID to system channel {self.YOUR_CHANNEL_ID}")
                return
        
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if isinstance(channel, discord.TextChannel):
                    self.YOUR_CHANNEL_ID = channel.id
                    logging.info(f"Fallback: Set YOUR_CHANNEL_ID to first text channel {self.YOUR_CHANNEL_ID}")
                    return
        
        logging.error("ERROR: Could not find a valid channel for YOUR_CHANNEL_ID!")

    def save_spanner_tracker(self):
        """Save the spanner tracker data to a CSV file."""
        try:
            with open('spanner_tracker.csv', 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['User ID', 'Mention'])
                for user_id, mention in self.spanner_tracker:
                    writer.writerow([user_id, mention])
        except Exception as e:
            logging.error(f"Error saving spanner tracker: {e}")

    def load_spanner_tracker(self):
        """Load the spanner tracker data from a CSV file."""
        if os.path.exists('spanner_tracker.csv'):
            try:
                with open('spanner_tracker.csv', 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    next(reader)  # Skip header
                    self.spanner_tracker = [(int(row[0]), row[1]) for row in reader]
            except Exception as e:
                logging.error(f"Error loading spanner tracker: {e}")

    async def check_queue_timeouts(self, bot):
        """Automatically remove inactive users from the queue."""
        while True:
            if self.YOUR_CHANNEL_ID is None:
                logging.info("YOUR_CHANNEL_ID not set. Retrying in 10 seconds...")
                await asyncio.sleep(10)
                continue
            
            await asyncio.sleep(60)  # Check every minute
            now = time.time()
            expired_users = [user for user, join_time in self.keen_queue.items() if now - join_time > self.USER_TIMEOUT and not self.ready_check_active]
            
            for user in expired_users:
                del self.keen_queue[user]
                await self.send_message_to_channel(bot, self.YOUR_CHANNEL_ID, f"{user} removed from the queue due to timeout. You have 10 minutes to rejoin at your original position!")
                
                # Rejoin logic
                await asyncio.sleep(600)  # 10-minute window
                if user not in self.keen_queue and len(self.keen_queue) < self.QUEUE_LIMIT:
                    self.keen_queue[user] = time.time()
                    await self.send_message_to_channel(bot, self.YOUR_CHANNEL_ID, f"{user} has rejoined the queue at their original position!")

    async def send_message_to_channel(self, bot, channel_id, message_content):
        """Helper function to send messages to a channel and return the message object."""
        channel = bot.get_channel(channel_id)
        if channel:
            try:
                message = await channel.send(message_content)
                logging.info(f"Message sent to channel {channel_id}: {message_content}")
                return message  # Return the message object
            except discord.Forbidden:
                logging.error(f"ERROR: Bot lacks permissions to send messages in channel {channel_id}!")
            except discord.HTTPException as e:
                logging.error(f"ERROR: Failed to send message in channel {channel_id}: {e}")
        else:
            logging.error(f"Channel {channel_id} not found!")
        return None  # Return None if the message couldn't be sent