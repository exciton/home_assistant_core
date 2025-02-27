"""The pi_hole component."""
from __future__ import annotations

import logging

from hole import Hole
from hole.exceptions import HoleError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_LOCATION,
    CONF_NAME,
    CONF_SSL,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_STATISTICS_ONLY,
    DATA_KEY_API,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    MIN_TIME_BETWEEN_UPDATES,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.removed(DOMAIN, raise_if_present=False)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pi-hole entry."""
    name = entry.data[CONF_NAME]
    host = entry.data[CONF_HOST]
    use_tls = entry.data[CONF_SSL]
    verify_tls = entry.data[CONF_VERIFY_SSL]
    location = entry.data[CONF_LOCATION]
    api_key = entry.data.get(CONF_API_KEY)

    # remove obsolet CONF_STATISTICS_ONLY from entry.data
    if CONF_STATISTICS_ONLY in entry.data:
        entry_data = entry.data.copy()
        entry_data.pop(CONF_STATISTICS_ONLY)
        hass.config_entries.async_update_entry(entry, data=entry_data)

    # start reauth to force api key is present
    if CONF_API_KEY not in entry.data:
        raise ConfigEntryAuthFailed

    _LOGGER.debug("Setting up %s integration with host %s", DOMAIN, host)

    session = async_get_clientsession(hass, verify_tls)
    api = Hole(
        host,
        session,
        location=location,
        tls=use_tls,
        api_token=api_key,
    )

    async def async_update_data() -> None:
        """Fetch data from API endpoint."""
        try:
            await api.get_data()
            await api.get_versions()
        except HoleError as err:
            raise UpdateFailed(f"Failed to communicate with API: {err}") from err
        if not isinstance(api.data, dict):
            raise ConfigEntryAuthFailed

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=name,
        update_method=async_update_data,
        update_interval=MIN_TIME_BETWEEN_UPDATES,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_KEY_API: api,
        DATA_KEY_COORDINATOR: coordinator,
    }

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Pi-hole entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class PiHoleEntity(CoordinatorEntity):
    """Representation of a Pi-hole entity."""

    def __init__(
        self,
        api: Hole,
        coordinator: DataUpdateCoordinator,
        name: str,
        server_unique_id: str,
    ) -> None:
        """Initialize a Pi-hole entity."""
        super().__init__(coordinator)
        self.api = api
        self._name = name
        self._server_unique_id = server_unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information of the entity."""
        if self.api.tls:
            config_url = f"https://{self.api.host}/{self.api.location}"
        else:
            config_url = f"http://{self.api.host}/{self.api.location}"

        return DeviceInfo(
            identifiers={(DOMAIN, self._server_unique_id)},
            name=self._name,
            manufacturer="Pi-hole",
            configuration_url=config_url,
        )
