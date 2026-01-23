"""Bluetti BT switches."""

from __future__ import annotations
import asyncio
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from bluetti_bt_lib import build_device, BluettiDevice, DeviceWriter, DeviceWriterConfig, FieldName
from bluetti_bt_lib.fields import SelectField

from .types import FullDeviceConfig, get_category
from . import device_info as dev_info, get_unique_id
from .const import DATA_COORDINATOR, DATA_LOCK, DOMAIN
from .coordinator import PollingCoordinator
from .utils import mac_loggable, unique_id_logable


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Setup select entities."""

    config = FullDeviceConfig.from_dict(entry.data)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    lock = hass.data[DOMAIN][entry.entry_id][DATA_LOCK]

    logger = logging.getLogger(
        f"{__name__}.{mac_loggable(config.address).replace(':', '_')}"
    )

    if config is None or not isinstance(coordinator, PollingCoordinator):
        logger.error("No coordinator found")
        return None

    # Generate device info
    logger.info("Creating selects for device with address %s", config.address)
    device_info = dev_info(entry)

    # Add switches
    bluetti_device = build_device(config.name)

    switches_to_add = []
    switch_fields = bluetti_device.get_select_fields()
    for field in switch_fields:
        category = get_category(FieldName(field.name))

        switches_to_add.append(
            BluettiSelect(
                bluetti_device,
                config.address,
                coordinator,
                device_info,
                field,
                lock,
                use_encryption=config.use_encryption,
                category=category,
                logger=logger,
            )
        )

    async_add_entities(switches_to_add)


class BluettiSelect(CoordinatorEntity, SelectEntity):
    """Bluetti universal switch."""

    def __init__(
        self,
        bluetti_device: BluettiDevice,
        address: str,
        coordinator: PollingCoordinator,
        device_info: DeviceInfo,
        field: SelectField,
        lock: asyncio.Lock,
        use_encryption: bool = False,
        category: EntityCategory | None = None,
        logger: logging.Logger = logging.getLogger(),
    ):
        """Init entity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._logger = logger

        e_name = f"{device_info.get('name')} {field.name}"
        self._bluetti_device = bluetti_device
        self._address = address
        self._field = field
        self._response_key = field.name
        self._unavailable_counter = 5
        self._lock = lock
        self._use_encryption = use_encryption
        self._attr_options = [e.name for e in field.e]

        self._attr_has_entity_name = True
        self._attr_device_info = device_info
        self._attr_translation_key = field.name
        self._attr_available = False
        self._attr_unique_id = get_unique_id(e_name)
        self._attr_entity_category = category
        self._write_in_progress = False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._attr_available

    def _set_available(self):
        """Set switch as available."""
        self._attr_available = True
        self._unavailable_counter = 0
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()

    def _set_unavailable(self, cause: str = "Unknown"):
        """Mark select data as stale but keep showing last value."""
        self._unavailable_counter += 1

        self._attr_extra_state_attributes = {
            "unavailable_counter": self._unavailable_counter,
            "unavailable_cause": cause,
            "data_stale": True,
        }

        # Don't mark as unavailable - retain last known value
        # Entity will show last value with stale indicator in attributes

        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        # Don't update state from coordinator while write is in progress
        # This prevents the select from reverting to old state while command is being sent
        if self._write_in_progress:
            self._logger.debug(
                "Write in progress for %s, skipping coordinator update",
                unique_id_logable(self._attr_unique_id)
            )
            return

        if self.coordinator.data is None:
            self._logger.debug(
                "Data from coordinator is None",
            )
            self._set_unavailable("Data is None")
            return

        self._logger.debug(
            "Updating state of %s", unique_id_logable(self._attr_unique_id)
        )
        if not isinstance(self.coordinator.data, dict):
            self._logger.debug(
                "Invalid data from coordinator (select.%s)",
                unique_id_logable(self._attr_unique_id),
            )
            self._set_unavailable("Invalid data")
            return

        response_data = self.coordinator.data.get(self._response_key)
        if response_data is None:
            self._set_unavailable("No data")
            return

        if not isinstance(response_data, self._field.e):
            self._logger.warning(
                "Invalid response data type from coordinator (select.%s): %s",
                unique_id_logable(self._attr_unique_id),
                response_data,
            )
            self._set_unavailable("Invalid data type")
            return

        self._set_available()
        self.current_option = response_data.name
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        """Set the entity to value."""
        self._logger.debug(
            "Set %s on %s to %s",
            self._response_key,
            mac_loggable(self._address),
            option,
        )
        # Optimistically set state immediately
        self.current_option = option
        self._write_in_progress = True
        self.async_write_ha_state()

        await self.write_to_device(option)

    async def write_to_device(self, state: str):
        """Write to device."""

        try:
            # Check if we can reuse coordinator's connection
            shared_client = None
            shared_encryption = None

            if (
                hasattr(self.coordinator, 'reader') and
                self.coordinator.reader.client is not None and
                self.coordinator.reader.client.is_connected and
                self.coordinator.reader.encryption is not None and
                self.coordinator.reader.encryption.is_ready_for_commands
            ):
                shared_client = self.coordinator.reader.client
                shared_encryption = self.coordinator.reader.encryption
                self._logger.debug("Reusing coordinator's connection")
                timeout = 10
            else:
                self._logger.debug("Coordinator connection not available, creating new connection")
                timeout = 45

            writer_config = DeviceWriterConfig(
                timeout=timeout, use_encryption=self._use_encryption
            )

            writer = DeviceWriter(
                self._address,
                self._bluetti_device,
                config=writer_config,
                lock=self._lock,
                future_builder_method=self.coordinator.hass.loop.create_future,
                shared_client=shared_client,
                shared_encryption=shared_encryption,
            )

            # Send command
            await writer.write(self._field.name, state)

            # Give device time to process the write command
            await asyncio.sleep(3)

        except TimeoutError:
            self._logger.error("Timed out for device %s", mac_loggable(self._address))
            return None
        finally:
            # Always clear write lock and allow coordinator updates
            self._write_in_progress = False

        # Force immediate refresh to get updated sensor values
        # This happens after write completes (or times out)
        # Coordinator update will now be allowed through
        await self.coordinator.async_refresh()
