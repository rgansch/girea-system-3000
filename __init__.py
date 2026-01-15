"""The Girea System 3000 (Gira Reverse Engineered) integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER
from .gira_ble import (
    GiraCoverBLEClient, 
    GiraCoverPassiveBluetoothDataUpdateCoordinator,
    GiraClimateBLEClient,
    GiraClimatePassiveBluetoothDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["cover", "climate"] 

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > 1:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 1:

        new_data = {**config_entry.data}
        if config_entry.minor_version == 1:
            new_data["devicetype"] = "Jal+Schaltuhr"

        hass.config_entries.async_update_entry(config_entry, data=new_data, minor_version=2, version=1)

    _LOGGER.debug("Migration to configuration version %s.%s successful", config_entry.version, config_entry.minor_version)

    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Girea System 3000 from a config entry."""
    address = config_entry.data["address"]
    name = config_entry.data.get("name", f"Gira Shutter {address[-5:].replace(':', '')}")
    devicetype = config_entry.data["devicetype"]

    if devicetype == "Jal+Schaltuhr":
        # Create the coordinator that will listen for broadcasts
        coordinator = GiraCoverPassiveBluetoothDataUpdateCoordinator(
            hass,
            address=address,
            name=name,
        )
        # Create the client that will send commands
        client = GiraCoverBLEClient(hass, address, name)
    elif devicetype == "Thermostat":
        # Create the coordinator that will listen for broadcasts
        coordinator = GiraClimatePassiveBluetoothDataUpdateCoordinator(
            hass,
            address=address,
            name=name,
        )
        # Create the client that will send commands
        client = GiraClimateBLEClient(hass, address, name)
    else:
        raise Exception("Unknown device type: " + devicetype)

    # Store both client and coordinator
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    # Forward the setup to the  platform.
    # The coordinator will automatically start listening when the entity subscribes to it.
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Only start the coordinator after all platforms have had a chance to subscribe.
    config_entry.async_on_unload(coordinator.async_start())
    # Note: async_start() returns a function that can be awaited, not a coroutine itself.
    # The async_on_unload() method handles this correctly.

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # The coordinator handles its own cleanup of the bluetooth callback.
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)
    
    return unload_ok
