from datetime import timedelta

import os
import time
import pytest
import daf
import asyncio


# CONFIGURATION
TEST_GUILD_ID = 863071397207212052
TEST_USER_ID = 145196308985020416


@pytest.mark.asyncio
async def test_text_message_update(text_channels):
    "This tests if all the text messages succeed in their sends"
    TEXT_MESSAGE_TEST_MESSAGE = [
        ("Hello world", daf.discord.Embed(title="Hello world")),
        ("Goodbye world", daf.discord.Embed(title="Goodbye world"))
    ]

    guild = daf.GUILD(TEST_GUILD_ID)
    user = daf.USER(TEST_USER_ID)
    text_message = daf.message.TextMESSAGE(None, timedelta(seconds=5), "START", text_channels,
                                        "send", start_in=timedelta(), remove_after=None)
    direct_message = daf.message.DirectMESSAGE(None, timedelta(seconds=5), "START", "send",
                                                start_in=timedelta(0), remove_after=None)
    # Initialize objects
    await guild.initialize()
    await user.initialize()
    await guild.add_message(text_message)
    await user.add_message(direct_message)

    # TextMESSAGE send
    for data in TEXT_MESSAGE_TEST_MESSAGE:
        text, embed = data
        await text_message.update(data=data)
        result = await text_message._send()

        # Check results
        for message in text_message.sent_messages.values():
            assert text == message.content, "TextMESSAGE text does not match message content"
            assert embed.to_dict() in [e.to_dict() for e in message.embeds], "TextMESSAGE embed not in message embeds"

        assert len(result["channels"]["failed"]) == 0, "Failed to send to all channels"

        # DirectMESSAGE send
        await direct_message.update(data=data)
        result = await direct_message._send()

        # Check results
        message = direct_message.previous_message
        assert text == message.content, "DirectMESSAGE text does not match message content"
        assert embed.to_dict() in [e.to_dict() for e in message.embeds], "DirectMESSAGE embed not in message embeds"
        assert result["success_info"]["success"], "Failed to send to all channels"



@pytest.mark.asyncio
async def test_voice_message_update(voice_channels):
    "This tests if all the voice messages succeed in their sends"
    await asyncio.sleep(5) # Wait for any messages still playing
    VOICE_MESSAGE_TEST_MESSAGE = [
            (10, daf.AUDIO("https://www.youtube.com/watch?v=4vQ8If7f374")),
            (6, daf.AUDIO(os.path.join(os.path.dirname(os.path.abspath(__file__)), "testing123.mp3")))
        ]

    guild = daf.GUILD(TEST_GUILD_ID)
    voice_message = daf.message.VoiceMESSAGE(None, timedelta(seconds=20), daf.AUDIO("https://www.youtube.com/watch?v=dZLfasMPOU4"), voice_channels,
                                            volume=50, start_in=timedelta(), remove_after=None)
    await guild.initialize()
    await guild.add_message(voice_message)
    # Send
    for duration, audio in VOICE_MESSAGE_TEST_MESSAGE:
        await voice_message.update(data=audio)
        start_time = time.time()
        result = await voice_message._send()
        end_time = time.time()

        # Check results
        assert end_time - start_time >= duration * len(voice_channels), "Message was not played till the end."
        assert len(result["channels"]["failed"]) == 0, "Failed to send to all channels"
