"""Bluetti Bluetooth Integration"""

from __future__ import annotations
import asyncio
import re
import logging
from typing import List
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import ConfigEntryNotReady

from .utils import mac_loggable
from .const import (
    DATA_COORDINATOR,
    DATA_LOCK,
    DOMAIN,
    MANUFACTURER,
)
from .types import FullDeviceConfig
from .coordinator import PollingCoordinator

PLATFORMS: List[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bluetti Powerstation from a config entry."""

    config = FullDeviceConfig.from_dict(entry.data)

    if config is None:
        return False

    logger = logging.getLogger(
        f"{__name__}.{mac_loggable(config.address).replace(':', '_')}"
    )

    logger.debug("Init Bluetti BT Integration")

    if not bluetooth.async_address_present(hass, config.address):
        raise ConfigEntryNotReady("Bluetti device not present")

    # Create data structure
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # Create lock
    lock = asyncio.Lock()

    # Create coordinator for polling
    logger.debug("Creating coordinator")
    coordinator = PollingCoordinator(
        hass,
        config,
        lock,
    )

    # Try initial data fetch with retries for faster boot-time sensor availability
    max_initial_attempts = 5
    initial_retry_delay = 5  # seconds between retries
    for attempt in range(1, max_initial_attempts + 1):
        try:
            logger.info(
                "Initial data fetch attempt %d/%d for %s",
                attempt,
                max_initial_attempts,
                mac_loggable(config.address),
            )
            await coordinator.async_config_entry_first_refresh()
            logger.info("Initial data fetch successful for %s", mac_loggable(config.address))
            break  # Success, exit retry loop
        except Exception as err:
            # Device still not ready or connection failed
            if attempt < max_initial_attempts:
                logger.warning(
                    "Initial data fetch failed for %s, retrying in %ds (attempt %d/%d): %s",
                    mac_loggable(config.address),
                    initial_retry_delay,
                    attempt,
                    max_initial_attempts,
                    err,
                )
                await asyncio.sleep(initial_retry_delay)
            else:
                # All retries exhausted, give up and let normal polling handle it
                logger.warning(
                    "Initial data fetch failed after %d attempts for %s, "
                    "will retry via normal polling schedule: %s",
                    max_initial_attempts,
                    mac_loggable(config.address),
                    err,
                )
                # Don't raise - let the integration load anyway
                # Entities will become available once polling succeeds

    hass.data[DOMAIN][entry.entry_id].setdefault(DATA_COORDINATOR, coordinator)
    hass.data[DOMAIN][entry.entry_id].setdefault(DATA_LOCK, lock)

    logger.debug("Creating entities")
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    logger.debug("Setup done")

    return True


def device_info(entry: ConfigEntry):
    """Device info."""
    config = FullDeviceConfig.from_dict(entry.data)

    if config is None:
        return None

    return DeviceInfo(
        identifiers={(DOMAIN, config.address)},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model=config.dev_type,
    )


def get_unique_id(name: str, sensor_type: str | None = None):
    """Generate an unique id."""
    res = re.sub("[^A-Za-z0-9]+", "_", name).lower()
    if sensor_type is not None:
        return f"{sensor_type}.{res}"
    return res
