"""
The following example automatically generates the shilling list if the channel name matches
any of the allowed_strings words.

It then dynamically adds an object, and later calls .update() method to change the initialization parameters
passed at the start.
"""
from datetime import timedelta
import asyncio
import daf



# Create a list in which we will automatically add guilds
allowed_strings = {"shill", "advert", "promo"}
data_to_shill = (     # Example data set
                "Hello World", 
                daf.discord.Embed(title="Example Embed",
                         color=daf.discord.Color.blue(),
                         description="This is a test embed")
                )


async def user_task():
    client = daf.get_client()  
    for guild in client.guilds:  # Iterate thru all the guilds where the bot is in
        await daf.add_object(daf.GUILD(guild.id, logging=True))
        channels = []
        for channel in guild.text_channels: # Iterate thru all the text channels in the guild
            if any([x in channel.name for x in allowed_strings]): # Check if any of the strings in allowed_strings are in the channel name
                channels.append(channel)
        text_msg = daf.TextMESSAGE(None, timedelta(seconds=5), data_to_shill, channels, "send", timedelta(seconds=0))
        # Dynamically add a message to the list
        await daf.add_object(text_msg, guild.id)

    #########################################################################
    #   Dynamic text message modification of the shill data and send period
    #########################################################################
    await asyncio.sleep(10)
    daf.trace("Updating the TextMESSAGE object")
    # Update the object
    await text_msg.update(data="Updated Data", end_period=timedelta(seconds=60)) 

    daf.trace("Now shilling 'Updated Data' with period of 60 seconds")
    #########################################################################

############################################################################################################################################################################


############################################################################################
if __name__ == "__main__":
    daf.run(token="OOFOAFO321o3oOOAOO$Oo$o$@O4242",
           user_callback=user_task)  
    