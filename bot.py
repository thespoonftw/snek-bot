import os
import json
import discord
import datetime
from dotenv import load_dotenv
from discord.ext import tasks

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CATEGORY_ID = os.getenv("NEW_CHANNEL_CATEGORY_ID")
USER_ROLE_ID = os.getenv("USER_ROLE_ID")
GUILD_ID = os.getenv("GUILD_ID")
LISTINGS_MESSAGE = os.getenv("LISTINGS_MESSAGE")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.reactions = True
DATABASE_JSON = "database.json"
DATABASE = {}

JOIN_MSG_KEY = "join_messsages"
LEAVE_MSG_KEY = "leave_messages"
LIST_MSG_KEY = "list_messages"
LISTINGS_CHANNEL_ID_KEY = "listings_channel_id"
LISTINGS_MESSAGE_ID_KEY = "listings_message_id"

client = discord.Client(intents=INTENTS)

@client.event
async def on_ready():

    print(f'{client.user} has connected to Discord!')

    listings_message = await get_listings_message()

    if (listings_message.content != LISTINGS_MESSAGE):
        await listings_message.edit(content=LISTINGS_MESSAGE)

    hourly_task.start()
    

@client.event
async def on_disconnect():

    print('Bot is shutting down.')
    save_database()


@tasks.loop(hours=1)
async def hourly_task():

    await client.wait_until_ready()

    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"Hourly task executed at {current_time}")
    save_database()
    

@client.event
async def on_message(message):

    # Ignore messages from the bot itself
    if message.author == client.user:
        return
    
    await read_command(message)

    listing_channel = await get_listings_channel()

    # Delete messages in the list channel
    if message.channel == listing_channel:
        await message.delete()

        
@client.event
async def on_raw_reaction_add(payload):

    # Ignore reactions from the bot itself
    if payload.member == client.user:
        return
        
    is_joining = payload.emoji.name == "✅"
    is_leaving = payload.emoji.name == "❌"
        
    if not is_joining and not is_leaving:
        return
        
    guild = client.get_guild(payload.guild_id)        
    channel = guild.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)

    # Ignore reactions to messages not made by the bot
    if message.author != client.user:
        return
    
    target_channel_id = None

    if is_leaving:
        target_channel_id = get_channel_id(LEAVE_MSG_KEY, message.id)

    if is_joining:
        target_channel_id = get_channel_id(JOIN_MSG_KEY, message.id)

    if target_channel_id is None:
        target_channel_id = get_channel_id(LIST_MSG_KEY, message.id)

    if target_channel_id == None:
        return
        
    target_channel = guild.get_channel(target_channel_id)    
    permissions = target_channel.permissions_for(payload.member)
    can_read_messages = permissions.read_messages
    
    if is_joining == can_read_messages:
        return
        
    if is_leaving:
        await target_channel.send(f"**{payload.member.display_name}** left.")
        
    overwrite = discord.PermissionOverwrite(read_messages=is_joining)
    await target_channel.set_permissions(payload.member, overwrite=overwrite)
    
    if is_joining:
        await target_channel.send(f"**{payload.member.display_name}** joined.") 
    

async def read_command(message):

    # Ignore commands from users without the role
    role = discord.utils.get(message.guild.roles, id=int(USER_ROLE_ID))
    if not role in message.author.roles:
        return
        
    args = message.content.split()
    
    # Empty message
    if len(args) == 0:
        return
    
    cmd = args[0]
    listings_channel = await get_listings_channel()

    if cmd == '$create':        
        if (message.channel == listings_channel):
            await create_listed_channel(message)
        else:
            await create_private_channel(message)

    if cmd == '$list':
        if (message.channel == listings_channel):
            return # dont list the listings channel
        else:
            await list_channel(message)


async def create_private_channel(message):

    args = message.content.split()
    
    if len(args) < 2:
        await message.channel.send("ERROR: Must provide channel name.")
        return
    
    name = args[1]
    topic = ' '.join(args[2:])
    new_channel = await create_channel(name, topic)
    await create_join_message(message.channel, new_channel)
    await create_leave_message(new_channel)


async def create_listed_channel(message):

    args = message.content.split()

    if len(args) < 3:
        return # we can't write errors in this channel
    
    name = args[1]
    topic = ' '.join(args[2:])
    new_channel = await create_channel(name, topic)    
    await create_list_message(new_channel, topic)
    await create_leave_message(new_channel)


async def list_channel(message):

    args = message.content.split()
    
    if len(args) < 2:
        await message.channel.send("ERROR: Must provide description of channel topic.")
        return
    
    await create_leave_message(message.channel)

    topic = ' '.join(args[1:])
    await create_list_message(message.channel, topic)


async def create_channel(name, topic):
    guild = client.get_guild(int(GUILD_ID))
    category = discord.utils.get(guild.categories, id=int(CATEGORY_ID))
    overwrites = { guild.default_role: discord.PermissionOverwrite(read_messages=False) }
    return await guild.create_text_channel(name=name, topic=topic, overwrites=overwrites, category=category)


async def create_join_message(message_channel, new_channel):

    join_message = await message_channel.send(f"Channel **{new_channel.name}** has been created. \n React ✅ to join!")
    await join_message.add_reaction("✅")
    save_message(JOIN_MSG_KEY, join_message.id, new_channel.id)


async def create_leave_message(channel):

    # Check if there is an existing leave message
    if (get_message_id(LEAVE_MSG_KEY, channel.id) is not None):
        return

    leave_message = await channel.send(f"Welcome to **{channel.name}**. \n React ❌ to leave.")
    await leave_message.pin()
    await leave_message.add_reaction("❌")

    save_message(LEAVE_MSG_KEY, leave_message.id, channel.id)


async def create_list_message(channel, topic):

    list_channel = await get_listings_channel() 
    existing_message_id = get_message_id(LIST_MSG_KEY, channel.id)
    await channel.edit(topic=topic)
    description = f"**{channel.name}**: {topic}"

    if (existing_message_id is None):
        list_message = await list_channel.send(description)
        await list_message.add_reaction("✅")
        await list_message.add_reaction("❌")
        save_message(LIST_MSG_KEY, list_message.id, channel.id)
    
    else:
        list_message = await list_channel.fetch_message(existing_message_id)
        await list_message.edit(content=description)
        await channel.send("Description updated.")


async def get_listings_channel():
    listings_channel_id = get_field(LISTINGS_CHANNEL_ID_KEY)
    guild = client.get_guild(int(GUILD_ID))

    if listings_channel_id is None:
        listings_channel = await guild.create_text_channel(name="channel-listings", topic="Join and Leave channels from here!")
        save_field(LISTINGS_CHANNEL_ID_KEY, listings_channel.id)
        return listings_channel
    else:
        return guild.get_channel(listings_channel_id)
    
    
async def get_listings_message():
    listings_channel = await get_listings_channel()
    listings_message_id = get_field(LISTINGS_MESSAGE_ID_KEY)
    if listings_message_id is None:
        listings_message = await listings_channel.send(LISTINGS_MESSAGE)
        save_field(LISTINGS_MESSAGE_ID_KEY, listings_message.id)
        return listings_message
    else:
        return await listings_channel.fetch_message(listings_message_id)
    

def get_message_id(message_str, channel_id):
    for message_id, match_id in DATABASE.get(str(message_str), {}).items():
        if channel_id == match_id:
            return int(message_id)
    return None


def get_channel_id(message_str, message_id):
    return DATABASE.get(message_str, {}).get(str(message_id))   


def save_message(message_str, message_id, channel_id):
    DATABASE.setdefault(message_str, {})
    DATABASE[message_str][message_id] = channel_id


def get_field(key):
    return DATABASE.get(key)


def save_field(key, value):
    DATABASE.setdefault(key, value)
    

def read_database():
    global DATABASE
    try:
        with open(DATABASE_JSON, 'r') as file:
            DATABASE = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        DATABASE = {}
        

def save_database():
    with open(DATABASE_JSON, 'w') as file:
        json.dump(DATABASE, file, indent=4)


client.run(TOKEN)