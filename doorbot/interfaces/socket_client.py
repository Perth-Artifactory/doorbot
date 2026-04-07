"""Socket client for member_portal-edge_auth daemon."""

import json
import logging
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)


class SocketClient:
    """Client for edge_auth daemon via Unix socket."""

    def __init__(self, socket_path: str):
        self.socket_path = Path(socket_path)

    async def authorize(self, card_number: str) -> dict:
        """Request authorization for a card number."""
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.socket_path))

            request = json.dumps({"card": card_number}) + "\n"
            writer.write(request.encode())
            await writer.drain()

            response_line = await reader.readline()
            writer.close()
            await writer.wait_closed()

            if not response_line:
                logger.error("Empty response from edge_auth daemon")
                return {"allowed": False}

            return json.loads(response_line.decode().strip())

        except FileNotFoundError:
            logger.error("Edge auth socket not found: %s", self.socket_path)
            return {"allowed": False}
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON from edge_auth: %s", e)
            return {"allowed": False}
        except Exception as e:
            logger.error("Socket communication error: %s", e)
            return {"allowed": False}

    async def refresh(self) -> bool:
        """Request a forced refresh of the access list cache."""
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.socket_path))

            request = json.dumps({"cmd": "refresh"}) + "\n"
            writer.write(request.encode())
            await writer.drain()

            response_line = await reader.readline()
            writer.close()
            await writer.wait_closed()

            response = json.loads(response_line.decode().strip())
            return response.get("ok", False)

        except Exception as e:
            logger.error("Refresh request failed: %s", e)
            return False

    def is_available(self) -> bool:
        """Check if the edge_auth daemon socket is available."""
        return self.socket_path.exists()
