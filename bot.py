import os
import json
import discord
import datetime
from dotenv import load_dotenv
from discord.ext import tasks

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.reactions = True
DATABASE_JSON = "database.json"
DATABASE = {}

client = discord.Client(intents=INTENTS)

@client.event
async def on_ready():

    print(f'{client.user} has connected to Discord!')

    read_database()

    for channel_id in get_listing_channel_ids():

        message = await get_info_message(channel_id)
        channel = get_channel(channel_id)
        message_content = get_info_message_content(channel_id)

        if message is None:
            message = await channel.send("New channel")
            save_info_message(channel_id, message.id)

        await message.edit(content=message_content)
    

@client.event
async def on_disconnect():

    print('Bot is shutting down.')
    

@client.event
async def on_message(message):

    # Ignore messages from the bot itself
    if message.author == client.user:
        return

    # get first arguement
    args = message.content.split()
    if len(args) == 0:
        return
    cmd = args[0]

    is_in_listings = message.channel.id in get_listing_channel_ids()
    is_in_listeds = message.channel.id in get_listed_channel_ids()
    
    if is_in_listings:

        await message.delete()

        if not get_listing_role(message.channel.id) in message.author.roles:
            return

        if cmd == '$create':
            await cmd_create_and_list(message)

    elif is_in_listeds:

        if not get_listing_role_for_listed(message.channel.id) in message.author.roles:
            return

        if cmd == '$rename':
            await cmd_update_name(message)

        elif cmd == '$desc':
            await cmd_update_description(message)

        elif cmd == '$role':
            await cmd_update_role(message)

    else:
        
        listing_channel_id = get_listing_channel_id_for_command(cmd) 

        if listing_channel_id is None:
            return
        
        role = get_listing_role(listing_channel_id)
        if not role in message.author.roles:
            return

        await cmd_list_channel(listing_channel_id, message.channel)



@client.event
async def on_raw_reaction_add(payload):

    # Ignore reactions from the bot itself
    if payload.member == client.user:
        return
        
    # Only valid emojis
    is_joining = payload.emoji.name == "✅"
    is_leaving = payload.emoji.name == "❌"
    if not is_joining and not is_leaving:
        return
    
    # Ignore reactions non-bot messages
    message = await get_message(payload.channel_id, payload.message_id)
    if message.author != client.user:
        return
    
    # Reaction to join message
    join_listed_channel = get_listed_channel_for_join_message(message.id)
    if not join_listed_channel is None:
        if is_joining:
            await add_user_to_channel(payload.member, join_listed_channel)
        if is_leaving:
            await remove_user_from_channel(payload.member, join_listed_channel)

    # Reaction to leave message
    leave_listed_channel = get_listed_channel_for_leave_message(message.id)
    if is_leaving and not leave_listed_channel is None:
        await remove_user_from_channel(payload.member, leave_listed_channel)


async def cmd_create_and_list(message):

    # get name
    args = message.content.split()
    if len(args) < 2:
        return
    listed_channel_name = "-".join(args[1:])

    listing_id = message.channel.id
    guild = get_guild()
    category = get_category(listing_id)
    overwrites = { guild.default_role: discord.PermissionOverwrite(read_messages=False) }
    listed_channel = await guild.create_text_channel(name=listed_channel_name, overwrites=overwrites, category=category, topic="No description yet")

    await cmd_list_channel(message.channel.id, listed_channel)
    await add_user_to_channel(message.author, listed_channel)


async def cmd_list_channel(listing_channel_id, listed_channel):

    listing_channel = get_channel(listing_channel_id)
    topic = listed_channel.topic
    if topic is None or len(topic) == 0:
        topic = "No description yet"
        await listed_channel.edit(topic=topic)

    join_message = await listing_channel.send(f"**{listed_channel.name}**: {topic}")
    await join_message.add_reaction("✅")
    await join_message.add_reaction("❌")

    leave_message = await listed_channel.send(f"Welcome to **{listed_channel.name}**. \n React ❌ to leave.")
    await leave_message.pin()
    await leave_message.add_reaction("❌")

    save_listed_channel(listed_channel.id, listed_channel.name, listing_channel.id, join_message.id, leave_message.id)


async def cmd_update_name(message):

    args = message.content.split()
    if len(args) < 2:
        return
    new_name = "-".join(args[1:])

    save_listed_name(message.channel.id, new_name)
    await message.channel.edit(name=new_name)
    await update_join_description(message.channel.id)
    await update_leave_description(message.channel.id)
    await message.channel.send("Channel name updated.")


async def cmd_update_description(message):

    args = message.content.split()
    if len(args) < 2:
        return
    topic = " ".join(args[1:])
    
    await message.channel.edit(topic=topic)
    await update_join_description(message.channel.id)
    await message.channel.send("Description updated.")


async def cmd_update_role(message):

    if len(message.role_mentions) < 1:
        return
    
    role = message.role_mentions[0]

    print(f'Found: {len(message.channel.overwrites.items())}')

    for target, overwrite in message.channel.overwrites.items():
        if not isinstance(target, discord.Role) and overwrite.view_channel:
            member = await get_member(target.id)
            await member.add_roles(role)
            await message.channel.set_permissions(member, overwrite=None)

    await message.channel.set_permissions(role, read_messages=True)

    save_listed_role(message.channel.id, role.id)
    await update_join_description(message.channel.id)
    await message.channel.send(f"Set role to {role.mention}.")


async def add_user_to_channel(user, channel):

    role = get_listed_role(channel.id)
    if role is None:
        overwrite = discord.PermissionOverwrite(read_messages=True)
        await channel.set_permissions(user, overwrite=overwrite)
    else:
        await user.add_roles(role)

    await channel.send(f"**{user.display_name}** joined.") 


async def remove_user_from_channel(user, channel):

    await channel.send(f"**{user.display_name}** left.") 

    role = get_listed_role(channel.id)
    if role is None:
        overwrite = discord.PermissionOverwrite(read_messages=False)
        await channel.set_permissions(user, overwrite=overwrite)
    else:
        await user.remove_roles(role)


async def update_join_description(listed_channel_id):
    join_message = await get_join_message(listed_channel_id)
    listed_channel = get_channel(listed_channel_id)
    role = get_listed_role(listed_channel_id)

    if role is None:
        description = f"**{listed_channel.name}**: {listed_channel.topic}"
    else:
        description = f"**{listed_channel.name}**: {role.mention} {listed_channel.topic}"
    
    await join_message.edit(content=description)


async def update_leave_description(listed_channel_id):
    leave_message = await get_leave_message(listed_channel_id)
    listed_channel = get_channel(listed_channel_id)
    await leave_message.edit(content=f"Welcome to **{listed_channel.name}**. \n React ❌ to leave.")


def get_listing_channels_dict():
   return DATABASE.get("listing_channels", {})

def get_listed_channels_dict():
   return DATABASE.get("listed_channels", {})

def get_listing_channel_ids():
    return [int(key) for key in get_listing_channels_dict().keys()]

def get_listed_channel_ids():
    return [int(key) for key in get_listed_channels_dict().keys()]

def get_listing_info(channel_id):
    return get_listing_channels_dict()[str(channel_id)]

def get_listed_info(channel_id):
    return get_listed_channels_dict()[str(channel_id)]

def get_listing_info_for_listed(listed_channel_id):
    return get_listing_info(get_listed_info(listed_channel_id).get("listing_channel_id"))

def get_info_message_content(channel_id):
    channel_info = get_listing_info(channel_id)
    channel_name = channel_info.get("name")
    channel_command = channel_info.get("create_command")
    return create_info_message(channel_name, channel_command)

def get_listing_role(channel_id):
    role_id = get_listing_info(channel_id).get("role_id")
    return get_role(role_id)

def get_listing_role_for_listed(listed_channel_id):
    listing_info = get_listing_info_for_listed(listed_channel_id)
    role_id = listing_info.get("role_id")
    return get_role(role_id)

def get_listed_role(channel_id):
    role_id = get_listed_info(channel_id).get("role_id")
    if (role_id is None):
        return None
    return get_role(role_id)

async def get_info_message(channel_id):
    message_id = get_listing_info(channel_id).get("info_message_id")
    if (message_id is None):
        return None
    return await get_message(channel_id, message_id)

async def get_join_message(listed_channel_id):
    channel_info = get_listed_info(listed_channel_id)
    listing_channel_id = channel_info.get("listing_channel_id")
    join_message_id = channel_info.get("join_message_id")
    return await get_message(listing_channel_id, join_message_id)

async def get_leave_message(listed_channel_id):
    leave_message_id = get_listed_info(listed_channel_id).get("leave_message_id")
    return await get_message(listed_channel_id, leave_message_id)

def get_category(listing_id):
    guild = get_guild()
    category_id = get_listing_info(listing_id).get("category_id")
    return discord.utils.get(guild.categories, id=category_id)

def get_listing_channel_id_for_command(command):
    for id_str, info in get_listing_channels_dict().items():
        if info.get("create_command") == command:
            return int(id_str)
    return None

def get_listed_channel_for_join_message(message_id):
    for id_str, info in get_listed_channels_dict().items():
        if info.get("join_message_id") == message_id:
            return get_channel(int(id_str))
    return None

def get_listed_channel_for_leave_message(message_id):
    for id_str, info in get_listed_channels_dict().items():
        if info.get("leave_message_id") == message_id:
            return get_channel(int(id_str))
    return None

def get_guild():
    return client.get_guild(int(GUILD_ID))

def get_channel(channel_id):
    return get_guild().get_channel(channel_id)

async def get_member(user_id):
    return await get_guild().fetch_member(user_id)

async def get_message(channel_id, message_id):
    return await get_channel(channel_id).fetch_message(message_id)

def get_role(role_id):
    return discord.utils.get(get_guild().roles, id=role_id)
    
def save_info_message(channel_id, message_id):
    get_listing_info(channel_id)["info_message_id"] = str(message_id)
    save_database()

def save_listed_name(channel_id, new_name):
    get_listed_info(channel_id)["name"] = new_name
    save_database()

def save_listed_role(channel_id, role_id):
    get_listed_info(channel_id)["role_id"] = role_id
    save_database()

def save_listed_channel(listed_channel_id, name, listing_channel_id, join_message_id, leave_message_id):
    listed_dict = get_listed_channels_dict()
    entry = {}
    entry["name"] = name
    entry["listing_channel_id"] = listing_channel_id
    entry["join_message_id"] = join_message_id
    entry["leave_message_id"] = leave_message_id
    listed_dict[str(listed_channel_id)] = entry
    save_database()


def read_database():
    global DATABASE
    try:
        with open(DATABASE_JSON, 'r') as file:
            DATABASE = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        DATABASE = {}
        

def save_database():
    print("saving database")
    with open(DATABASE_JSON, 'w') as file:
        json.dump(DATABASE, file, indent=4)


def create_info_message(channel_name, channel_command):
    return f"""
Welcome to **{channel_name}**.\n\n React with ✅ to join a channel or ❌ to leave.

**Commands:**
- To create a new channel here for people to join write `$create X` in this channel. Where X is the name of your channel. 
- To add an existing channel here write `${channel_command}` in that channel.
- To rename an existing channel write `$rename X` in that channel. Where X is your new channel name.
- To set the description of an existing channel, write `$desc X` in that channel. Where X is your desired description.
- To apply a role to a channel write `$role @X` in that channel. Where is your role mention.

Note that your messages in this channel will be automatically deleted.
."""

client.run(TOKEN)