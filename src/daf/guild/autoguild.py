"""
Automatic GUILD generation.
"""
from typing import Any, Union, List, Optional, Dict
from typeguard import typechecked
from datetime import timedelta, datetime
from copy import deepcopy

from ..message import BaseChannelMessage
from ..logging.tracing import TraceLEVELS, trace
from ..misc import async_util, instance_track, doc, attributes
from ..events import *

import _discord as discord
import asyncio

from .. import web
from .. import logging
from .guilduser import GUILD

import re


GUILD_JOIN_INTERVAL = timedelta(seconds=45)
GUILD_MAX_AMOUNT = 100

@instance_track.track_id
@doc.doc_category("Auto objects", path="guild")
class AutoGUILD:
    """

    .. versionchanged:: v3.3.0

        - Restored original way AutoGUILD
          works (as a GUILD generator)

    .. versionchanged:: v3.0.0

        - Now works like GUILD and USER.
        - Removed ``created_at`` property.


    Represents multiple guilds (servers) based on a text pattern.
    AutoGUILD generates :class:`daf.guild.GUILD` objects for each matched pattern.

    Parameters
    --------------
    include_pattern: str
        Regex pattern to use for searching guild names that are to be included.
        This is also checked before joining a new guild if ``auto_guild`` is given.

        For example you can do write ``.*`` to match ALL guilds you are joined into or specify
        (parts of) guild names separated with ``|`` like so: "name1|name2|name3|name4"

    exclude_pattern: Optional[str] = None
        Regex pattern to use for searching guild names that are
        **NOT** to be excluded.

        .. note::
            If both include_pattern and exclude_pattern yield a match,
            the guild will be excluded from match.

    remove_after: Optional[Union[timedelta, datetime]] = None
        When to remove this object from the shilling list.
    logging: Optional[bool] = False
        Set to True if you want the guilds generated to log
        sent messages.
    auto_join: Optional[web.GuildDISCOVERY] = None
        .. versionadded:: v2.5

        Optional :class:`~daf.web.GuildDISCOVERY` object which will automatically discover
        and join guilds though the browser.
        This will open a Google Chrome session.
    """
    __slots__ = (
        "include_pattern",
        "exclude_pattern",
        "_remove_after",
        "logging",
        "update_semaphore",
        "parent",
        "auto_join",
        "guild_query_iter",
        "guild_join_count",
        "_messages",
        "removal_buffer_length",
        "_removal_timer_handle",
        "_guild_join_timer_handle",
        "_invite_join_count",
        "_cache",
        "_event_ctrl",
        "_gen_guilds"
    )

    @typechecked
    def __init__(
        self,
        include_pattern: str,
        exclude_pattern: Optional[str] = None,
        remove_after: Optional[Union[timedelta, datetime]] = None,
        messages: Optional[List[BaseChannelMessage]] = None,
        logging: Optional[bool] = False,
        auto_join: Optional[web.GuildDISCOVERY] = None,
        invite_track: Optional[List[str]] = None,
        removal_buffer_length: int = 50
    ) -> None:
        if messages is None:
            messages = []

        if invite_track is None:
            invite_track = []

        # Remove spaces around OR
        self.include_pattern = re.sub(r"\s*\|\s*", '|', include_pattern) if include_pattern else None
        self.exclude_pattern = re.sub(r"\s*\|\s*", '|', exclude_pattern) if exclude_pattern else None
        self._remove_after = remove_after
        self._messages: List[BaseChannelMessage] = []
        self.logging = logging
        self.auto_join = auto_join
        self.parent = None
        self.guild_query_iter = None
        self.guild_join_count = 0
        self.removal_buffer_length = removal_buffer_length
        self._removal_timer_handle: asyncio.Task = None
        self._guild_join_timer_handle: asyncio.Task = None
        self._cache = []
        self._gen_guilds: List[GUILD] = []
        self._event_ctrl: EventController = None

        for message in messages:
            self.add_message(message)

        self._invite_join_count = {invite.split("/")[-1]: 0 for invite in invite_track}
        attributes.write_non_exist(self, "update_semaphore", asyncio.Semaphore(1))

    def __repr__(self) -> str:
        return f"AutoGUILD(include_pattern='{self.include_pattern}', exclude_pattern='{self.exclude_pattern})'"

    @property
    def messages(self) -> List[BaseChannelMessage]:
        """
        .. versionadded:: 3.0

        Returns all the (template) message objects.
        """
        return self._messages[:]

    @property
    def guilds(self) -> List[discord.Guild]:
        "Returns cached :class:`discord.Guild` objects."
        return self._cache
    
    @property
    def remove_after(self) -> Union[datetime, None]:
        "Returns the timestamp at which AutoGUILD will be removed or None if it will never be removed."
        return self._remove_after

    def _get_guilds(self):
        "Returns all the guilds that match the include_pattern and not exclude_pattern"
        client: discord.Client = self.parent.client
        guilds = [
            g for g in client.guilds
            if self._check_name_match(g.name)
        ]
        self._cache = guilds
        return guilds

    # API
    @typechecked
    def add_message(self, message: BaseChannelMessage) -> asyncio.Future:
        """
        Adds a message to the message list.

        .. warning::
            To use this method, the guild must already be added to the
            framework's shilling list (or initialized).

        |ASYNC_API|

        Parameters
        --------------
        message: BaseChannelMessage
            Message object to add.

        Returns
        --------
        Awaitable
            An awaitable object which can be used to await for execution to finish.
            To wait for the execution to finish, use ``await`` like so: ``await method_name()``.

        Raises
        --------------
        TypeError
            Raised when the message is not of type the guild allows.
        Other
            Raised from message.initialize() method.
        """
        self._messages.append(message)
        message._update_tracked_id(False)  # Don't allow remote operations, but still track
        return asyncio.gather(*(g.add_message(deepcopy(message)) for g in self._gen_guilds))
    

    @typechecked
    def remove_message(self, message: BaseChannelMessage) -> asyncio.Future:
        """
        Remove a ``message`` from the advertising list.

        |ASYNC_API|

        Parameters
        --------------
        message: BaseChannelMessage
            Message object to remove.

        Returns
        --------
        Awaitable
            An awaitable object which can be used to await for execution to finish.
            To wait for the execution to finish, use ``await`` like so: ``await method_name()``.
        """
        self._messages.remove(message)
        futures = []
        for g in self._gen_guilds:
            # Get the copied message index, all deep copied messages compare True, if they
            # were copied from the same source message.
            idx = g._messages.index(message)
            if idx == -1:
                continue

            futures.append(g.remove_message(g._messages[idx]))

        return asyncio.gather(*futures)

    def update(self, init_options = None, **kwargs) -> asyncio.Future:
        """
        Updates the object with new initialization parameters.

        |ASYNC_API|

        Returns
        --------
        Awaitable
            An awaitable object which can be used to await for execution to finish.
            To wait for the execution to finish, use ``await`` like so: ``await method_name()``.

        .. WARNING::
            After calling this method the entire object is reset
            (this includes it's GUILD objects in cache).
        """
        return self._event_ctrl.emit(EventID.server_update, self, init_options, **kwargs)

    # Non public methods
    def _reset_auto_join_timer(self):
        "Resets the periodic auto guild join timer."
        self._guild_join_timer_handle = async_util.call_at(
            self._event_ctrl.emit,
            GUILD_JOIN_INTERVAL,
            EventID.auto_guild_start_join,
            self
        )

    def _check_name_match(self, name: str) -> bool:
        return (
            name is not None and
            re.search(self.include_pattern, name) is not None and
            (self.exclude_pattern is None or re.search(self.exclude_pattern, name) is None)
        )

    @async_util.except_return
    async def initialize(self, parent: Any, event_ctrl: EventController):
        """
        Initializes the object.
        """
        client: discord.Client = parent.client
        self._event_ctrl = event_ctrl
        self.parent = parent
        if self.auto_join is not None:
            if (res := await self.auto_join.initialize(self)) is not None:
                raise res

            self.guild_query_iter = self.auto_join._query_request()

        if self._remove_after is not None:
            if isinstance(self._remove_after, timedelta):
                self._remove_after = datetime.now().astimezone() + self._remove_after
            else:
                self._remove_after = datetime.now().astimezone()

            self._removal_timer_handle = (
                async_util.call_at(
                    event_ctrl.emit,
                    self._remove_after,
                    EventID.server_removed,
                    self
                )
            )

        if len(self._invite_join_count):  # Skip invite query from Discord
            try:
                invites = await self._get_invites()
                invites = {invite.id: invite.uses for invite in invites}
                counts = self._invite_join_count
                for invite in list(counts.keys()):
                    try:
                        counts[invite] = invites[invite]
                    except KeyError:
                        del counts[invite]
                        trace(
                            f"Invite link {invite} not found in {self}. It will not be tracked!",
                            TraceLEVELS.ERROR
                        )

                    self._event_ctrl.add_listener(
                        EventID.discord_member_join,
                        self._on_member_join,
                        predicate=lambda memb: self._check_name_match(memb.guild.name)
                    )
                    self._event_ctrl.add_listener(
                        EventID.discord_invite_delete,
                        self._on_invite_delete,
                        predicate=lambda inv: self._check_name_match(inv.guild.name)
                    )
            except discord.HTTPException as exc:
                trace(f"Could not query invite links in {self}", TraceLEVELS.ERROR, exc)

        if self.auto_join is not None:
            self._reset_auto_join_timer()
            event_ctrl.add_listener(EventID.auto_guild_start_join, self._join_guilds, lambda ag: ag is self)

        self._event_ctrl.add_listener(
            EventID.discord_guild_join,
            self._on_guild_join,
            predicate=lambda guild: self._check_name_match(guild.name)
        )
        self._event_ctrl.add_listener(
            EventID.discord_guild_remove,
            self._on_guild_remove,
        )

        event_ctrl.add_listener(EventID.server_update, self._on_update, lambda server, *args, **kwargs: server is self)

        for guild in self._get_guilds():
            await self._make_new_guild(guild)

    def _generate_guild_log_context(self, guild: discord.Guild):
        return {
                "name": guild.name,
                "id": guild.id,
                "type": "GUILD"
        }

    def _generate_invite_log_context(self, member: discord.Member, invite_id: str) -> dict:
        return {
            "id": invite_id,
            "member": {
                "id": member.id,
                "name": member.name
            }
        }

    def _filter_message_context(self, guild: discord.Guild, message_ctx: dict) -> Dict:
        message_ctx = message_ctx.copy()
        message_ctx["channels"] = message_ctx["channels"].copy()

        channel_ctx = message_ctx["channels"]
        guild_channels = set(x.id for x in guild.channels)
        channel_ctx["successful"] = [x for x in channel_ctx["successful"] if x["id"] in guild_channels]
        channel_ctx["failed"] = [x for x in channel_ctx["failed"] if x["id"] in guild_channels]

        return message_ctx if channel_ctx["successful"] or channel_ctx["failed"] else None

    async def _make_new_guild(self, guild: discord.Guild):
        new_guild = GUILD(guild, deepcopy(self._messages), self.logging, removal_buffer_length=0)
        if (await new_guild.initialize(self.parent, self._event_ctrl)) is not None:  # not None == exc returned
            return

        self._gen_guilds.append(new_guild)

    async def _get_invites(self) -> List[discord.Invite]:
        client: discord.Client = self.parent.client
        invites = []
        for guild in self._get_guilds():
            try:
                perms = guild.get_member(client.user.id).guild_permissions
                if perms.manage_guild:
                    invites.extend(await guild.invites())
            except discord.HTTPException as exc:
                trace(f"Error reading invite links for guild {guild.name}!", TraceLEVELS.ERROR, exc)

        return invites        

    async def _on_update(self, _, init_options, **kwargs):
        await self._close()
        try:
            # Update the guild
            if "invite_track" not in kwargs:
                kwargs["invite_track"] = self.invite_track

            kwargs["messages"] = kwargs.pop("messages", self._messages)
            if init_options is None:
                init_options = {"parent": self.parent, "event_ctrl": self._event_ctrl}

            await async_util.update_obj_param(self, init_options=init_options, **kwargs)
        except Exception:
            await self.initialize(self.parent, self._event_ctrl)
            raise
    
    @async_util.with_semaphore("update_semaphore")
    async def _join_guilds(self, _):
        """
        Coroutine that joins new guilds thru the web layer.
        """
        # Join Guilds
        discovery = self.auto_join
        selenium: web.SeleniumCLIENT = self.parent.selenium
        client: discord.Client = self.parent.client
        if (
            self.guild_query_iter is None or  # No auto_join provided or iterated though all guilds
            self.guild_join_count == discovery.limit or
            len(client.guilds) == GUILD_MAX_AMOUNT
        ):
            self._event_ctrl.remove_listener(EventID.auto_guild_start_join, self._join_guilds)
            return

        async def get_next_guild():
            try:
                # Get next result from top.gg
                yielded: web.QueryResult = await self.guild_query_iter.__anext__()
                if (
                    re.search(self.include_pattern, yielded.name) is None or
                    (
                        self.exclude_pattern is not None and
                        re.search(self.exclude_pattern, yielded.name) is not None
                    )
                ):
                    return None

                return yielded
            except StopAsyncIteration:
                trace(f"Iterated though all found guilds -> stopping guild join in {self}.", TraceLEVELS.NORMAL)
                self.guild_query_iter = None
            except Exception as exc:
                trace(f"Could not query top.gg, stopping auto join.", TraceLEVELS.ERROR, exc)
                self.guild_query_iter = None

        
        while True:
            if (yielded := await get_next_guild()) is None:
                return

            if client.get_guild(yielded.id) is not None:
                self.guild_join_count += 1  # Guilds we are already joined also count
                continue

            try:
                invite_url = await selenium.fetch_invite_link(yielded.url)
                if invite_url is None:
                    raise RuntimeError("Fetching invite link failed")

                await selenium.random_server_click()
                await selenium.join_guild(invite_url)
                await asyncio.sleep(1)
                if client.get_guild(yielded.id) is None:
                    raise RuntimeError(
                        "No error detected in browser,"
                        "but the guild can not be seen by the API wrapper."
                    )
                
                self.guild_join_count += 1  # Increase only on success
            except Exception as exc:
                trace(
                    f"Joining guild raised an error. (Guild '{yielded.name}')",
                    TraceLEVELS.ERROR,
                    exc
                )

            break

        self._reset_auto_join_timer()

    async def _on_member_join(self, member: discord.Member):        
        counts = self._invite_join_count
        invites = await self._get_invites()
        invites = {invite.id: invite.uses for invite in invites}
        for id_, last_uses in counts.items():
            uses = invites[id_]
            if last_uses != uses:
                trace(f"User {member.name} joined to {member.guild.name} with invite {id_}", TraceLEVELS.DEBUG)
                counts[id_] = uses
                invite_ctx = self._generate_invite_log_context(member, id_)
                await logging.save_log(self._generate_guild_log_context(member.guild), None, None, invite_ctx)
                return

    async def _on_invite_delete(self, invite: discord.Invite):
        if invite.id in self._invite_join_count:
            del self._invite_join_count[invite.id]
            guild = invite.guild
            trace(
                f"Invite link ID {invite.id} deleted from {guild.name} (ID: {guild.id} - {self})",
                TraceLEVELS.DEBUG
            )

    async def _on_guild_join(self, guild: discord.Guild):
        await self._make_new_guild(guild)

    async def _on_guild_remove(self, guild: discord.Guild):
        for g in self._gen_guilds:
            if g.apiobject == guild:
                await g._close()
                self._gen_guilds.remove(g)
                break

    @async_util.with_semaphore("update_semaphore")
    async def _close(self):
        """
        Closes any lower-level async objects.
        """
        if self._event_ctrl is None:  # Not initialized or already closed
            return

        self._event_ctrl.remove_listener(EventID.auto_guild_start_join, self._join_guilds)
        self._event_ctrl.remove_listener(EventID.server_update, self._on_update)

        # Remove PyCord API wrapper event handlers.
        self._event_ctrl.remove_listener(EventID.discord_member_join, self._on_member_join)
        self._event_ctrl.remove_listener(EventID.discord_invite_delete, self._on_invite_delete)

        if self._removal_timer_handle is not None and not self._removal_timer_handle.cancelled():
            self._removal_timer_handle.cancel()
            await asyncio.gather(self._removal_timer_handle, return_exceptions=True)
        
        if self._guild_join_timer_handle is not None and not self._guild_join_timer_handle.cancelled():
            self._guild_join_timer_handle.cancel()
            await asyncio.gather(self._guild_join_timer_handle, return_exceptions=True)

        if self.auto_join is not None:
            await self.auto_join._close()

        for guild in self._gen_guilds:
            await guild._close()
