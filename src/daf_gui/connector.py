"""
Module contains definitions related to different connection
clients.
"""
from typing import List, Optional, Literal

from daf.logging.tracing import TraceLEVELS, trace

from .convert import *
from .utilities import *

from aiohttp import ClientSession, BasicAuth
from aiohttp import web

import daf


__all__ = (
    "AbstractConnectionCLIENT",
    "LocalConnectionCLIENT",
    "RemoteConnectionCLIENT",
    "get_connection",
)


class GLOBALS:
    connection: "AbstractConnectionCLIENT" = None


class AbstractConnectionCLIENT:
    """
    Interface for connection clients.
    """
    async def initialize(self, *args, **kwargs):
        """
        Method for initializing DAF.

        Parameters
        ------------
        args
            Custom number of positional arguments.
        kwargs:
            Custom number of keyword arguments.
        """
        raise NotImplementedError

    async def shutdown(self):
        """
        Method calls DAF's shutdown core function.
        """
        raise NotImplementedError

    async def add_account(self, obj: daf.client.ACCOUNT):
        """
        Adds and initializes a new account into DAF.

        Parameters
        --------------
        account: daf.client.ACCOUNT
            The account to add.
        """
        raise NotImplementedError

    async def remove_account(self, account: daf.client.ACCOUNT):
        """
        Logs out and removes account from DAF.

        Paramterers
        ----------------
        account: daf.client.ACCOUNT
            The account to remove from DAF.
        """
        raise NotImplementedError

    async def get_accounts(self) -> List[daf.client.ACCOUNT]:
        """
        Retrieves a list of all accounts in DAF.
        """
        raise NotImplementedError

    async def get_logger(self) -> daf.logging.LoggerBASE:
        """
        Returns the logger object used in DAF.
        """
        raise NotImplementedError

    async def refresh(self, object_: object) -> object:
        """
        Returns updated state of the object.

        Parameters
        ------------
        object_: object
            The object that we want to refresh.
        """
        raise NotImplementedError

    async def execute_method(self, object_: object, method_name: str, **kwargs):
        """
        Executes a method inside object and returns the result.

        Parameter
        -----------
        object_: object
            The object to execute the method on.
        method_name: str
            The name of the method to execute.
        args: Any
            Custom number of positional arguments to pass to the method.
        kwargs: Any
            Custom number of keyword arguments to pass to the method.
        """
        raise NotImplementedError


class LocalConnectionCLIENT(AbstractConnectionCLIENT):
    """
    Client used for starting and running DAF locally, on the same
    device as the graphical interface.
    """
    def __init__(self) -> None:
        self.connected = False

    async def initialize(self, *args, **kwargs):
        await daf.initialize(*args, **kwargs)
        GLOBALS.connection = self  # Set self as global connection
        self.connected = True

    async def shutdown(self):
        await daf.shutdown()
        self.connected = False

    def add_account(self, obj: daf.client.ACCOUNT):
        return daf.add_object(obj)

    def remove_account(self, account: daf.client.ACCOUNT):
        return daf.remove_object(account)

    async def get_accounts(self) -> List[daf.client.ACCOUNT]:
        return daf.get_accounts()

    async def get_logger(self) -> daf.logging.LoggerBASE:
        return daf.get_logger()

    async def refresh(self, object_: object) -> object:
        return object_  # Local connection can just use the local object

    async def execute_method(self, object_: object, method_name: str, **kwargs):
        result = getattr(object_, method_name)(**kwargs)
        if isinstance(result, Coroutine):
            result = await result

        return result


class RemoteConnectionCLIENT(AbstractConnectionCLIENT):
    """
    Client used for connecting to DAF running on a remote server though
    the HTTP protocol. The connection is based fully on request from the GUI (this client).

    Parameters
    ------------
    host: str
        The URL / IP of the host.
    port: Optional[int]
        The HTTP port of the host.
        Defaults to 80.
    username: Optional[str]
        The username to login with.
    password: Optional[str].
        The password to login with.
    verify_ssl: Optional[bool]
        Defaults to True. If True, connection will be refused when the certificate does not match the host name.
    """
    def __init__(
        self,
        host: str,
        port: int = 80,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: Optional[bool] = True
    ) -> None:
        self.session = None
        self.connected = False

        self.host = host.rstrip('/')  # Remove any slashes in the back to prevent errors with port
        self.port = port
        self.auth = None
        if username is not None:
            self.auth = BasicAuth(username, password)

        if verify_ssl is None:
            verify_ssl = False

        self.verify_ssl = verify_ssl

    async def _request(self, method: Literal["GET", "POST", "DELETE", "PATCH"], route: str, **kwargs):
        method = method.lower()
        additional_kwargs = {}
        if not self.verify_ssl:
            additional_kwargs["ssl"] = False

        trace(f"Requesting {route} with {method}.", TraceLEVELS.DEBUG)
        async with getattr(self.session, method)(route, json={"parameters": kwargs}, **additional_kwargs) as response:
            if response.status != 200:
                raise web.HTTPException(reason=response.reason)

            # All communicaiton is in JSON except binary types
            if response.content_type == "application/json":
                return await response.json()
            else:
                return await response.content.read()

    async def initialize(self, *args, **kwargs):
        try:
            self.session = ClientSession(f"{self.host}:{self.port}", auth=self.auth)
            daf.tracing.initialize(kwargs.get("debug", TraceLEVELS.NORMAL))
            trace("Pinging server.")
            await self._ping()
            GLOBALS.connection = self  # Set self as global connection
            self.connected = True
        except Exception:
            await self.session.close()
            raise

    async def shutdown(self):
        trace("Closing connection.")
        await self.session.close()
        self.connected = False

    async def add_account(self, obj: daf.client.ACCOUNT):
        trace("Logging in.")
        response = await self._request("POST", "/accounts", account=daf.convert.convert_object_to_semi_dict(obj))
        trace(response["message"])

    async def remove_account(self, account: daf.client.ACCOUNT):
        trace("Removing remote account.")
        response = await self._request("DELETE", "/accounts", account_id=account._daf_id)
        trace(response["message"])

    async def get_accounts(self) -> List[daf.client.ACCOUNT]:
        response = await self._request("GET", "/accounts")
        return daf.convert.convert_from_semi_dict(response["result"]["accounts"])

    async def get_logger(self):
        response = await self._request("GET", "/logging")
        return daf.convert.convert_from_semi_dict(response["result"]["logger"])

    async def refresh(self, object_: object):
        response = await self._request("GET", "/object", object_id=object_._daf_id)
        return daf.convert.convert_from_semi_dict(response["result"]["object"])

    async def execute_method(self, object_: object, method_name: str, **kwargs):
        kwargs = daf.convert.convert_object_to_semi_dict(kwargs)

        response = await self._request("POST", "/method", object_id=object_._daf_id, method_name=method_name, **kwargs)
        message = response.get("message")
        if message is not None:
            trace(message, TraceLEVELS.DEBUG)

        return daf.convert.convert_from_semi_dict(response["result"]["result"])

    def _ping(self):
        return self._request("GET", "/ping")


def get_connection() -> AbstractConnectionCLIENT:
    return GLOBALS.connection
