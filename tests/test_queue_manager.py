import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_dir)
from queue_manager import QueueManager

class TestQueueManager(unittest.TestCase):
    def setUp(self):
        self.bot = MagicMock()
        self.queue_manager = QueueManager()

    async def test_set_channel_id(self):
        guild = MagicMock()
        channel = MagicMock()
        channel.name = "bot-channel"
        channel.id = 12345
        guild.text_channels = [channel]
        self.bot.guilds = [guild]

        await self.queue_manager.set_channel_id(self.bot)
        self.assertEqual(self.queue_manager.YOUR_CHANNEL_ID, 12345)

if __name__ == "__main__":
    unittest.main()