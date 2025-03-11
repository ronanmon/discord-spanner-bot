import discord
import time
import asyncio
from queue_manager import QueueManager

async def make_keen(interaction: discord.Interaction, queue_manager: QueueManager):
    user = interaction.user.mention
    if user in queue_manager.keen_queue:
        await interaction.response.send_message(f"{user}, you're already in the queue!", ephemeral=True)
    else:
        if user in queue_manager.potential_queue:
            queue_manager.potential_queue.remove(user)
        queue_manager.keen_queue[user] = time.time()
        position = len(queue_manager.keen_queue)
        await interaction.response.send_message(f"{user} has joined the queue at position {position}/{queue_manager.QUEUE_LIMIT}.", ephemeral=False)
        if len(queue_manager.keen_queue) >= queue_manager.QUEUE_LIMIT:
            if queue_manager.YOUR_CHANNEL_ID is None:
                print("YOUR_CHANNEL_ID not set. Cannot start ready check.")
                return
            await ready_check(interaction, queue_manager)
        elif len(queue_manager.keen_queue) > queue_manager.QUEUE_LIMIT // 2:  # More than half full
            await notify_potentials(interaction, queue_manager)

async def ready_check(interaction: discord.Interaction, queue_manager: QueueManager):
    queue_manager.ready_check_active = True
    if queue_manager.YOUR_CHANNEL_ID is None:
        print("YOUR_CHANNEL_ID not set. Cannot start ready check.")
        return
    
    tag_list = " ".join(queue_manager.keen_queue.keys())
    message = await interaction.channel.send(f"{tag_list} ALL ABOARD THE KEEN TRAIN! React with ✅ if you're ready in the next 10 minutes or face spannering! :wrench:")
    await message.add_reaction("✅")

    reacted_users = set()

    def check(reaction, user):
        return reaction.emoji == "✅" and user.mention in queue_manager.keen_queue and reaction.message.id == message.id

    try:
        while len(reacted_users) < len(queue_manager.keen_queue):
            reaction, user = await interaction.client.wait_for('reaction_add', timeout=600.0, check=check)
            reacted_users.add(user.mention)
        await interaction.channel.send("Everyone is ready! Have a spanner-free time!")
        queue_manager.keen_queue.clear()
    except asyncio.TimeoutError:
        unreacted_users = [user for user in queue_manager.keen_queue.keys() if user not in reacted_users]
        for user_mention in unreacted_users:
            user_id = int(user_mention.strip('<@!>'))
            queue_manager.spanner_tracker.append((user_id, user_mention))
            queue_manager.save_spanner_tracker()
            await interaction.channel.send(f"{user_mention} spannered by not readying up in time! :wrench:")
        # Re-add users who reacted to the queue
        for user in reacted_users:
            queue_manager.keen_queue[user] = time.time()
        await interaction.channel.send("Users who readied up have been re-added to the queue.")
    finally:
        queue_manager.ready_check_active = False

async def notify_potentials(interaction: discord.Interaction, queue_manager: QueueManager):
    if queue_manager.potential_queue:
        if queue_manager.YOUR_CHANNEL_ID is None:
            print("YOUR_CHANNEL_ID not set. Cannot notify potential keens.")
            return
        tag_list = " ".join(queue_manager.potential_queue)
        await queue_manager.send_message_to_channel(interaction.client, queue_manager.YOUR_CHANNEL_ID, f"Hey {tag_list}, the queue is more than half full! Use `/keen` to join if you're ready! 🚂")