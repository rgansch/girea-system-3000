"""Platform for the Girea System 3000 Thermostat integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER
from .gira_ble import GiraClimateBLEClient, GiraClimatePassiveBluetoothDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Girea System 3000 thermostat from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: GiraClimatePassiveBluetoothDataUpdateCoordinator = data["coordinator"]
    client: GiraClimateBLEClient = data["client"]

    if config_entry.data["devicetype"] == "Thermostat":
        # Add the Gira Thermostat as a Home Assistant Thermostat entity
        thermostat_entity = GireaSystem3000Climate(coordinator, client, config_entry)
        async_add_entities([thermostat_entity])
        LOGGER.info("Coordinator setup complete for %s", config_entry.title)

class GireaSystem3000Climate(
    CoordinatorEntity[GiraClimatePassiveBluetoothDataUpdateCoordinator], ClimateEntity
):
    """Representation of a Gira System 3000 Thermostat (Climate entity in HA)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
          ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_hvac_modes = [
        HVACMode.OFF, 
        HVACMode.HEAT
    ]
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_translation_key = "climate"
    _attr_name = None
    _attr_min_temperature = 10
    _attr_max_temperature = 30

    def __init__(
        self,
        coordinator: GiraClimatePassiveBluetoothDataUpdateCoordinator,
        client: GiraClimateBLEClient,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the climate."""
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=client.name,
            connections={(config_entry.entry_id, client.address)},
        )

        self._attr_current_temperature = None  # Initialize the state to None
        self._attr_target_temperature = None

        self._attr_hvac_mode = HVACMode.OFF # Dummy values, needs to be updated with BLE data
        self._attr_hvac_action = HVACMode.OFF

        LOGGER.debug("Created climate entity for %s", client.name)

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        # A passive bluetooth device is always available as long as it's running
        return True

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode."""
        return self._attr_hvac_mode

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC modes."""
        return self._attr_hvac_modes

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        return self._attr_hvac_action

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return self._attr_min_temperature

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return self._attr_max_temperature

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._attr_current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._attr_target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        try:
            await self._client.send_temperature_command(kwargs[ATTR_TEMPERATURE])
        except UpdateFailed:
            self._attr_available = False
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            target_temperature = self.coordinator.data.get("target_temperature")
            current_temperature = self.coordinator.data.get("current_temperature")
            # Only update the state if a new temperature is available
            if target_temperature is not None:
                self._attr_target_temperature = target_temperature
                LOGGER.debug(
                    "Climate entity received update. New target temperature: %s",
                    target_temperature,
                )
            if current_temperature is not None:
                self._attr_current_temperature = current_temperature
                LOGGER.debug(
                    "Climate entity received update. New target temperature: %s",
                    current_temperature,
                )
        self.async_write_ha_state()
