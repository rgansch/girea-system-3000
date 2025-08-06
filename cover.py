"""Platform for the Girea System 3000 cover integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, LOGGER
from .gira_ble import GiraBLEClient



async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Girea System 3000 cover from a config entry."""
    gira_client: GiraBLEClient = hass.data[DOMAIN][config_entry.entry_id]

    # Add the Gira shutter as a Home Assistant Cover entity
    async_add_entities([GireaSystem3000Cover(gira_client, config_entry)])


class GireaSystem3000Cover(CoverEntity):
    """Representation of a Gira System 3000 Cover."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
    _attr_available = True
    _attr_is_closed = None  # Add this to satisfy CoverEntity requirements
    _attr_assumed_state = True


    def __init__(self, gira_client: GiraBLEClient, config_entry: ConfigEntry) -> None:
        """Initialize the cover."""
        self._gira_client = gira_client
        self._attr_unique_id = config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=gira_client.name,
        )
        self._is_opening = None
        self._is_closing = None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            await self._gira_client.send_up_command()
            self._is_opening = True
            self._is_closing = False
            self.async_write_ha_state()
            self._attr_available = True
        except UpdateFailed:
            self._attr_available = False
            self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        try:
            await self._gira_client.send_down_command()
            self._is_opening = False
            self._is_closing = True
            self.async_write_ha_state()
            self._attr_available = True
        except UpdateFailed:
            self._attr_available = False
            self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        try:
            await self._gira_client.send_stop_command()
            self._is_opening = False
            self._is_closing = False
            self.async_write_ha_state()
            self._attr_available = True
        except UpdateFailed:
            self._attr_available = False
            self.async_write_ha_state()

    @property
    def is_opening(self) -> bool | None:
        """Return if the cover is opening or not."""
        return self._is_opening

    @property
    def is_closing(self) -> bool | None:
        """Return if the cover is closing or not."""
        return self._is_closing

    @property
    def current_cover_position(self) -> int | None:
        """This device does not report its position, so we return a static value or None."""
        return None
