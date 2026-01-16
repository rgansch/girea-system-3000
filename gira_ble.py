"""Bluetooth LE communication for Gira System 3000 devices."""
import asyncio
import logging
import time
from typing import Any, cast, Optional

from bleak import BleakClient, BleakError, BLEDevice
from bleak_retry_connector import establish_connection

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, LOGGER

# --- Constants to throttle updates ----
# BLE advertisments are sent very often resulting in a flood of data
# To reduce the spam in HA (esp. data logger) a throttling is built in
# For cover: new values and every x seconds
# For thermostat target temp: new values and every x seconds
# For thermostat current value: average of x seconds
UPDATE_INTERVALL = 60

# --- Constants for Gira Broadcast Parsing ---
GIRA_MANUFACTURER_ID = 1412

# Define the correct GATT Characteristic UUID.
GIRA_COMMAND_CHARACTERISTIC_UUID = "97696341-f77a-43ae-8c35-09f0c5245308"


##### COVER ######

# --- Constants for Gira Command Generation ---
# Basic command structure prefix
COVER_COMMAND_PREFIX = bytearray.fromhex("F6032001")

# Suffix constant often preceding the actual value
COVER_COMMAND_SUFFIX = bytearray.fromhex("1001")

# Property IDs for different command types
COVER_PROPERTY_ID_MOVE = 0xFF # For Up/Down commands
COVER_PROPERTY_ID_STOP = 0xFD # For Stop command
COVER_PROPERTY_ID_STEP = 0xFE # For Step Up/Down commands
COVER_PROPERTY_ID_SET_POSITION = 0xFC # For Absolute Position (Percentage)

# Values for commands
COVER_VALUE_UP = 0x00
COVER_VALUE_DOWN = 0x01
COVER_VALUE_STOP = 0x00 # Stop command uses 0x00 as its value

# The correct, full prefix for a position broadcast
COVER_BROADCAST_PREFIX = bytearray.fromhex("F7032001F61001")


class GiraCoverPassiveBluetoothDataUpdateCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """Coordinator for receiving passive BLE broadcasts from Gira shutters."""

    def __init__(self, hass: HomeAssistant, address: str, name: str):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            address=address,
            mode=bluetooth.BluetoothScanningMode.PASSIVE,
            connectable=False,
        )
        self._device_name = name  # Store name separately since 'name' property is read-only
        self._last_position = None
        self._last_position_update = 0
        LOGGER.debug("Created coordinator instance for %s (%s)", name, address)

    def _async_handle_unavailable(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Handle the device going unavailable."""
        LOGGER.debug("Handle unavailable for %s (%s)", self._device_name, self.address)
        self.last_update_success = False
        self.async_update_listeners()

    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> Optional[dict]:
        # Check if this event is for our device
        if service_info.device.address.upper() != self.address.upper():
            return None

        manufacturer_data = service_info.manufacturer_data.get(GIRA_MANUFACTURER_ID)
        if not manufacturer_data:
            return None

        # Check if the COVER_BROADCAST_PREFIX is anywhere within the manufacturer_data
        try:
            # Find the starting index of the broadcast prefix
            prefix_index = manufacturer_data.find(COVER_BROADCAST_PREFIX)
        except (ValueError, AttributeError) as e:
            return None

        # Ensure we have enough bytes after the prefix to read the position
        if prefix_index == -1:
            return None
            
        if len(manufacturer_data) < prefix_index + len(COVER_BROADCAST_PREFIX) + 1:
            LOGGER.debug("Not enough data after broadcast prefix")
            return None

        # Extract the position byte, which is 1 byte after the prefix
        position_byte = manufacturer_data[prefix_index + len(COVER_BROADCAST_PREFIX)]
        ha_position = round(100 * (255 - position_byte) / 255)

        LOGGER.info(
            "Gira broadcast received from %s. Raw data: %s, Position byte: %s, HA Position: %s%%",
            self._device_name,
            manufacturer_data.hex(),
            position_byte,
            ha_position,
        )
        
        self.data = {"position": ha_position}

        # Only update on new value or if UPDATE_INTERVALL seconds passed
        if (ha_position != self._last_position) or \
           ((time.time() - self._last_position_update) > UPDATE_INTERVALL):
           self._last_position_update = time.time()
           self._last_position = ha_position
           self.async_update_listeners()

def _generate_command(property_id: int, value: int) -> bytearray:
    """Generates the full command byte array from its parts."""
    return (
        COVER_COMMAND_PREFIX
        + property_id.to_bytes(1, 'big')
        + COVER_COMMAND_SUFFIX
        + value.to_bytes(1, 'big')
    )

def generate_position_command(percentage: int) -> bytearray:
    """Generates the command for setting absolute blinds position."""
    if not 0 <= percentage <= 100:
        raise ValueError("Percentage must be between 0 and 100.")
    per_to_byte = (100 - percentage) * 255 // 100
    return _generate_command(COVER_PROPERTY_ID_SET_POSITION, per_to_byte)

class GiraCoverBLEClient:
    """Manages the Bluetooth LE connection and command sending for a Gira device."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize the client."""
        self.hass = hass
        self.address = address
        self.name = name
        self._client: BleakClient | None = None
        self._is_connecting = asyncio.Lock()

    async def send_command(self, command: bytearray) -> None:
        """
        Connect to the device, send a command, and then disconnect.
        This is a single-shot, connect-on-demand method.
        """
        async with self._is_connecting:
            if self._client and self._client.is_connected:
                LOGGER.debug("Client already connected, sending command directly.")
                try:
                    # Log the command before sending it
                    LOGGER.debug("Sending command: %s", command.hex())
                    # Changed response to False
                    await self._client.write_gatt_char(GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=False)
                    return
                except (BleakError, asyncio.TimeoutError) as e:
                    LOGGER.warning("Failed to send command to connected device: %s", e)
                    # Fall through to attempt a reconnect
                    await self._client.disconnect()
                    self._client = None
            
            LOGGER.debug("Attempting to connect to %s (%s) to send command.", self.name, self.address)
            
            device = bluetooth.async_ble_device_from_address(self.hass, self.address)
            if not device:
                LOGGER.error("Device %s (%s) not found in Home Assistant's Bluetooth devices.", self.name, self.address)
                raise UpdateFailed(f"Device {self.name} not found.")

            client = None
            try:
                client = await establish_connection(
                    BleakClient, 
                    device, 
                    self.name,
                    pair=True,
                    timeout=10,
                    max_attempts=3
                )
                self._client = client
                LOGGER.info("Successfully connected to %s (%s) and sending command.", self.name, self.address)

                # Log the command before sending it
                LOGGER.debug("Sending command: %s", command.hex())

                # Send the command, reponse=True is crucial
                await client.write_gatt_char(GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=True)

                LOGGER.info("Command sent successfully to %s.", self.name)
            except (BleakError, asyncio.TimeoutError) as e:
                LOGGER.error("Failed to connect or send command to %s (%s): %s", self.name, self.address, e)
                raise UpdateFailed(f"Failed to connect and send command to {self.name}: {e}") from e
            finally:
                if client and client.is_connected:
                    LOGGER.info("Disconnecting from %s (%s) after sending command.", self.name, self.address)
                    await client.disconnect()
                self._client = None

    async def send_up_command(self) -> None:
        """Send the command to raise the shutter."""
        await self.send_command(_generate_command(COVER_PROPERTY_ID_MOVE, COVER_VALUE_UP))

    async def send_down_command(self) -> None:
        """Send the command to lower the shutter."""
        await self.send_command(_generate_command(COVER_PROPERTY_ID_MOVE, COVER_VALUE_DOWN))

    async def send_stop_command(self) -> None:
        """Send the command to stop the shutter."""
        await self.send_command(_generate_command(COVER_PROPERTY_ID_STOP, COVER_VALUE_STOP))

    async def send_step_up_command(self) -> None:
        """Send the command to step the shutter up."""
        await self.send_command(_generate_command(COVER_PROPERTY_ID_STEP, COVER_VALUE_UP))

    async def send_step_down_command(self) -> None:
        """Send the command to step the shutter down."""
        await self.send_command(_generate_command(COVER_PROPERTY_ID_STEP, COVER_VALUE_DOWN))

    async def set_absolute_position(self, percentage: int) -> None:
        """Set the absolute position of the blinds (0-100%)."""
        command = generate_position_command(percentage)
        await self.send_command(command)


##### CLIMATE ######

# Basic command structure prefix
CLIMATE_COMMAND_PREFIX = bytearray.fromhex("F6006501F51001")

# Broadcast structure prefix
#CLIMATE_BROADCAST_TARGET_PREFIX = bytearray.fromhex("F7006501F51001") # Also other prefix variations in log, check for more data in that frame TODO
CLIMATE_BROADCAST_TARGET_PREFIX = bytearray.fromhex("F7006501")
CLIMATE_BROADCAST_TARGET_SUFFIX= bytearray.fromhex("1001")
CLIMATE_BROADCAST_CURRENT_PREFIX = bytearray.fromhex("F7014101")
CLIMATE_BROADCAST_CURRENT_SUFFIX= bytearray.fromhex("1001")

class GiraClimatePassiveBluetoothDataUpdateCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """Coordinator for receiving passive BLE broadcasts from Gira thermostats."""

    def __init__(self, hass: HomeAssistant, address: str, name: str):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            address=address,
            mode=bluetooth.BluetoothScanningMode.PASSIVE,
            connectable=False,
        )
        self._device_name = name  # Store name separately since 'name' property is read-only
        self._current_temperature_avg = None
        self._current_temperature_avg_update = 0
        self._last_current_temperature_update = 0
        self._last_target_temperature = None
        self._last_target_temperature_update = 0
        LOGGER.debug("Created coordinator instance for %s (%s)", name, address)

    def _async_handle_unavailable(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Handle the device going unavailable."""
        LOGGER.debug("Handle unavailable for %s (%s)", self._device_name, self.address)
        self.last_update_success = False
        self.async_update_listeners()

    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> Optional[dict]:
        # Check if this event is for our device
        if service_info.device.address.upper() != self.address.upper():
            return None

        manufacturer_data = service_info.manufacturer_data.get(GIRA_MANUFACTURER_ID)
        if not manufacturer_data:
            return None

        # Check if the CLIMATE_BROADCAST_PREFIX is anywhere within the manufacturer_data
        try:
            # Find the starting index of the broadcast prefix
            prefix_index_current = manufacturer_data.find(CLIMATE_BROADCAST_CURRENT_PREFIX)
            prefix_index_target = manufacturer_data.find(CLIMATE_BROADCAST_TARGET_PREFIX)
        except (ValueError, AttributeError) as e:
            return None

        # Received current temperature frame
        if prefix_index_current >= 0:
        # Ensure we have enough bytes after the prefix to read the temperature
            if len(manufacturer_data) != (prefix_index_current + len(CLIMATE_BROADCAST_CURRENT_PREFIX) 
                                          +1 + len(CLIMATE_BROADCAST_CURRENT_SUFFIX) + 2):
                LOGGER.debug("Data frame length not plausible")
                return None

            # Extract the temperature byte and some unknown data byte
            unknown_byte = manufacturer_data[prefix_index_current + 
                                             len(CLIMATE_BROADCAST_CURRENT_PREFIX)]
            temperature_bytes = manufacturer_data[prefix_index_current + 
                                                  len(CLIMATE_BROADCAST_CURRENT_PREFIX) +
                                                  1 +
                                                  len(CLIMATE_BROADCAST_CURRENT_SUFFIX)
                                                  : ]
            current_temperature = byte_to_temperature(temperature_bytes)

            LOGGER.info(
                "Gira broadcast received from %s. Raw data: %s, Unknown byte: %s, Temperature byte: %s, Current temperature: %s degree",
                self._device_name,
                manufacturer_data.hex(),
                hex(unknown_byte),
                temperature_bytes.hex(),
                current_temperature
            )

            self.data = {"current_temperature": current_temperature}

        # Received target temperature frame
        if prefix_index_target >= 0:
            # Ensure we have enough bytes after the prefix to read the temperature
            if len(manufacturer_data) != (prefix_index_target + len(CLIMATE_BROADCAST_TARGET_PREFIX) 
                                          +1 + len(CLIMATE_BROADCAST_TARGET_SUFFIX) + 2):
                LOGGER.debug("Data frame length not plausible")
                return None

            # Extract the temperature byte and some unknown data byte
            unknown_byte = manufacturer_data[prefix_index_target + 
                                             len(CLIMATE_BROADCAST_TARGET_PREFIX)]
            temperature_bytes = manufacturer_data[prefix_index_target + 
                                                  len(CLIMATE_BROADCAST_TARGET_PREFIX) +
                                                  1 +
                                                  len(CLIMATE_BROADCAST_TARGET_SUFFIX)
                                                  : ]
            target_temperature = byte_to_temperature(temperature_bytes)

            LOGGER.info(
                "Gira broadcast received from %s. Raw data: %s, Unknown byte: %s, Temperature byte: %s, Target temperature: %s degree",
                self._device_name,
                manufacturer_data.hex(),
                hex(unknown_byte),
                temperature_bytes.hex(),
                target_temperature
            )   

        # Update listeners, with throttling
        if prefix_index_current >= 0:
            # Init of averaging and update current after first received current temperature
            if self._last_current_temperature_update == 0:                
                self._current_temperature_avg = 0
                self._current_temperature_avg_update = time.time()

                self._last_current_temperature_update = time.time()
                self.data = {"current_temperature": current_temperature}
                self.async_update_listeners()
            # Accumulate weighted sum (time) of received current temperature
            else:
                self._current_temperature_avg = self._current_temperature_avg + \
                    current_temperature * (time.time() - self._current_temperature_avg_update)
                self._current_temperature_avg_update = time.time()
        
                # Send average after update intervall and reinit the average
                if ((time.time() - self._last_current_temperature_update) > UPDATE_INTERVALL):
                    current_temperature_avg = self._current_temperature_avg / (time.time() - self._last_current_temperature_update)
                    self._current_temperature_avg = 0
                    self._current_temperature_avg_update = time.time()
                    
                    self._last_current_temperature_update = time.time()
                    self.data = {"current_temperature": current_temperature_avg}
                    self.async_update_listeners()

        if prefix_index_target >= 0:
            if (target_temperature != self._last_target_temperature) or \
                ((time.time() - self._last_target_temperature_update) > UPDATE_INTERVALL):
                self._last_target_temperature_update = time.time()
                self._last_target_temperature = target_temperature

                self.data = {"target_temperature": target_temperature}
                self.async_update_listeners()


# Temperature to/from byte conversion
# <20.48° straightforward 0.01 conversion factor (0.01° per bit)
# >=20.48° changes to 0.02 conversion factor (0.02° per bit) and for some reason adds a flat 1024
# i.e. range from 0x07FF to 0xC00 is unused
def byte_to_temperature(temp_bytes: bytearray) -> int:
    temp_raw = int.from_bytes(temp_bytes, byteorder='big', signed=False)

    if temp_raw <= 2048:
        temperature = temp_raw / 100.0
    else:
        temperature = (temp_raw - 1024 - 2048)*0.02 + 20.48

    return temperature

def temperature_to_byte(temperature: float) -> bytearray:
    if temperature < 20.48:
        temp_raw = int(temperature*100 + 0.5)
    else:
        temp_raw = int((temperature - 20.48)/0.02 + 0.5) + 2048 + 1024

    return temp_raw.to_bytes(2, 'big')

class GiraClimateBLEClient:
    """Manages the Bluetooth LE connection and command sending for a Gira device."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize the client."""
        self.hass = hass
        self.address = address
        self.name = name
        self._client: BleakClient | None = None
        self._is_connecting = asyncio.Lock()

    async def send_command(self, command: bytearray) -> None:
        """
        Connect to the device, send a command, and then disconnect.
        This is a single-shot, connect-on-demand method.
        """
        async with self._is_connecting:
            if self._client and self._client.is_connected:
                LOGGER.debug("Client already connected, sending command directly.")
                try:
                    # Log the command before sending it
                    LOGGER.debug("Sending command: %s", command.hex())
                    # Changed response to False
                    await self._client.write_gatt_char(GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=False)
                    return
                except (BleakError, asyncio.TimeoutError) as e:
                    LOGGER.warning("Failed to send command to connected device: %s", e)
                    # Fall through to attempt a reconnect
                    await self._client.disconnect()
                    self._client = None
            
            LOGGER.debug("Attempting to connect to %s (%s) to send command.", self.name, self.address)
            
            device = bluetooth.async_ble_device_from_address(self.hass, self.address)
            if not device:
                LOGGER.error("Device %s (%s) not found in Home Assistant's Bluetooth devices.", self.name, self.address)
                raise UpdateFailed(f"Device {self.name} not found.")

            client = None
            try:
                client = await establish_connection(
                    BleakClient, 
                    device, 
                    self.name,
                    pair=True,
                    timeout=10,
                    max_attempts=3
                )
                self._client = client
                LOGGER.info("Successfully connected to %s (%s) and sending command.", self.name, self.address)

                # Log the command before sending it
                LOGGER.debug("Sending command: %s", command.hex())

                # Send the command, reponse=True is crucial
                await client.write_gatt_char(GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=True)

                LOGGER.info("Command sent successfully to %s.", self.name)
            except (BleakError, asyncio.TimeoutError) as e:
                LOGGER.error("Failed to connect or send command to %s (%s): %s", self.name, self.address, e)
                raise UpdateFailed(f"Failed to connect and send command to {self.name}: {e}") from e
            finally:
                if client and client.is_connected:
                    LOGGER.info("Disconnecting from %s (%s) after sending command.", self.name, self.address)
                    await client.disconnect()
                self._client = None

    async def send_temperature_command(self, temperature: float) -> None:
        """Send the command to raise the shutter."""
        if (temperature < 10) or (temperature > 30):
            LOGGER.debug("Temperature to send exceeds allowed value range: %s", temperature)
            return
        command = temperature_to_byte(temperature)
        await self.send_command(CLIMATE_COMMAND_PREFIX + command)
