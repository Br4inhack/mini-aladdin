"""
apps/dashboard/consumers.py

WebSocket consumer for real-time portfolio state updates.

The JavaScript dashboard connects to:
    ws://<host>/ws/portfolio/<portfolio_id>/

The State Engine (or any Celery task) broadcasts updates to the
'portfolio_<id>' channel group using:

    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'portfolio_{portfolio_id}',
        {'type': 'portfolio_update', 'data': state_dict}
    )
"""

import json
import logging

from channels.db import database_sync_to_async  # noqa: F401 — available for DB queries
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger('apps.dashboard')


class PortfolioConsumer(AsyncWebsocketConsumer):
    """
    Async WebSocket consumer that streams portfolio state updates to the
    dashboard UI in real time.

    Each connected browser tab joins the channel group
    ``portfolio_<portfolio_id>``. When the State Engine writes a new
    snapshot it broadcasts to that group, and this consumer forwards
    the payload to the browser as a JSON message.

    Message types sent TO the client:
        ``connection``   — sent once on connect to confirm the session.
        ``pong``         — reply to a client ``ping`` keep-alive.
        ``portfolio_update`` — full state dict from the State Engine.

    Message types received FROM the client:
        ``ping``         — keep-alive; server replies with ``pong``.
    """

    async def connect(self) -> None:
        """
        Called when a WebSocket handshake is initiated.

        Extracts ``portfolio_id`` from the URL, joins the corresponding
        channel group, accepts the connection, and sends an initial
        confirmation message.
        """
        self.portfolio_id: str = self.scope['url_route']['kwargs']['portfolio_id']
        self.group_name:   str = f'portfolio_{self.portfolio_id}'

        # Join the broadcast group for this portfolio
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # Accept the WebSocket upgrade
        await self.accept()

        logger.info(
            'PortfolioConsumer: client connected — portfolio_id=%s channel=%s',
            self.portfolio_id, self.channel_name,
        )

        # Confirm connection to the client
        await self.send(text_data=json.dumps({
            'type':         'connection',
            'status':       'connected',
            'portfolio_id': self.portfolio_id,
        }))

    async def disconnect(self, close_code: int) -> None:
        """
        Called when the WebSocket connection closes for any reason.

        Removes the channel from the broadcast group so this consumer
        no longer receives group messages.

        Args:
            close_code (int): WebSocket close code (e.g. 1000 = normal).
        """
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

        logger.info(
            'PortfolioConsumer: client disconnected — portfolio_id=%s code=%s',
            self.portfolio_id, close_code,
        )

    async def receive(self, text_data: str) -> None:
        """
        Called when a message arrives from the browser.

        Handles ``ping`` keep-alive messages. All other message types
        are silently ignored — the dashboard sends no other client
        messages in Phase 3.

        Args:
            text_data (str): Raw JSON string received from the client.
        """
        try:
            payload  = json.loads(text_data)
            msg_type = payload.get('type', '')

            if msg_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
            # All other client messages are intentionally ignored in Phase 3

        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                'PortfolioConsumer: malformed message from client: %s', exc
            )

    async def portfolio_update(self, event: dict) -> None:
        """
        Called by the channel layer when the State Engine broadcasts a
        portfolio snapshot to the ``portfolio_<id>`` group.

        Forwards ``event['data']`` directly to the connected browser as
        a JSON text frame. The dashboard JavaScript listens for this
        message type and re-renders the UI accordingly.

        Args:
            event (dict): Channel layer event dict containing:
                ``type`` — always ``'portfolio_update'``
                ``data`` — the full state dict from the State Engine.

        Example broadcast from Celery task::

            async_to_sync(channel_layer.group_send)(
                f'portfolio_{portfolio_id}',
                {'type': 'portfolio_update', 'data': state_dict}
            )
        """
        await self.send(text_data=json.dumps(event['data']))
