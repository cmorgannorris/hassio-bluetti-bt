# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom integration that enables local Bluetooth communication with Bluetti power stations. It uses the `bluetti-bt-lib` library (currently v0.1.6) to handle device communication protocols.

**Domain:** `bluetti_bt`
**Integration Type:** Device integration (local polling)
**Communication:** Bluetooth Low Energy (BLE)

## Development Commands

### Testing
```bash
# Run all unit tests
python3 -m unittest discover -s tests -p "*.py"

# Run tests in Docker
./test.sh
```

### Code Formatting
```bash
# Format code with black (Python 3.10 target)
./format.sh
```

### Local Development
```bash
# Deploy to local Home Assistant instance (requires Docker)
./deploy.sh
```

This copies the integration to `/var/ha_config/custom_components/` and runs Home Assistant in Docker.

## Architecture

### Core Components

**Entry Point (`__init__.py`)**
- `async_setup_entry()`: Initializes integration for a config entry
- Creates `PollingCoordinator` for periodic device data reading (default: every 20 seconds)
- Creates per-integration data storage at `hass.data[DOMAIN][entry.entry_id]`
- Contains coordinator and asyncio lock for thread-safe BLE access
- Forwards setup to platforms: sensor, switch, binary_sensor, select

**Configuration Flow (`config_flow.py`)**
- Two-step discovery process:
  1. `async_step_bluetooth()`: Auto-discovers devices via BLE (patterns in manifest.json)
  2. `async_step_user()`: User confirms device and creates config entry
- `OptionsFlowHandler`: Allows adjusting polling_interval, polling_timeout, max_retries after setup
- Uses `recognize_device()` from bluetti-bt-lib to identify device type and encryption status

**Coordinator (`coordinator.py`)**
- `PollingCoordinator` extends `DataUpdateCoordinator`
- `_async_update_data()`: Polls device via `DeviceReader.read()` from bluetti-bt-lib
- Returns dictionary: `{field_name: value, ...}`
- Verifies device is connectable before reading

**Entity Platforms**
All platforms follow similar patterns:
- Get coordinator from `hass.data[DOMAIN][entry.entry_id]`
- Get device object via `build_device(config.name)` from bluetti-bt-lib
- Query device for available fields (e.g., `get_sensor_fields()`)
- Create entities for each field
- Entities extend `CoordinatorEntity` for auto-updates

### Entity Types

**Sensors (`sensor.py`)**
- Regular numeric sensors (power, voltage, current, SOC, etc.)
- Pack sensors: Creates separate device info for each battery pack
- Cell voltage sensors: Individual sensor per cell from list data
- On encrypted devices: Includes select fields as read-only sensors

**Switches (`switch.py`)**
- Only on non-encrypted devices
- Writable boolean fields from `get_switch_fields()`
- `write_to_device()`: Establishes BLE connection, uses `DeviceWriter.write()`, waits 5 seconds, refreshes

**Binary Sensors (`binary_sensor.py`)**
- Boolean status fields from `get_bool_fields()`
- On encrypted devices: Also includes switch fields as read-only

**Selects (`select.py`)**
- Only on non-encrypted devices
- Multi-option controls from `get_select_fields()`
- Uses same `write_to_device()` pattern as switches

### Configuration Types (`types/`)

**Three-layer configuration system:**
1. `InitialDeviceConfig`: Set at discovery (address, name, dev_type, use_encryption)
2. `OptionalDeviceConfig`: User adjustable (polling_interval, polling_timeout, max_retries)
3. `FullDeviceConfig`: Combined runtime config

**Field Mappings:**
- `FieldDeviceClass`: Maps field names to Home Assistant device classes (VOLTAGE, CURRENT, POWER, etc.)
- `FieldStateClass`: Maps to state classes (MEASUREMENT, TOTAL_INCREASING)
- `FieldCategory`: Maps to entity categories (DIAGNOSTIC, CONFIG)

### Bluetooth Communication

**Reading Flow:**
1. Coordinator runs `_async_update_data()` on schedule
2. Verifies device is connectable
3. `DeviceReader.read()` fetches all sensor values
4. Returns data dictionary
5. All entities receive `_handle_coordinator_update()` callback

**Writing Flow:**
1. User triggers entity action (switch on/off, select option)
2. `write_to_device()` establishes BLE connection via Bleak
3. `DeviceWriter.write()` sends command
4. Waits 5 seconds for device to process
5. Requests coordinator refresh to get new state

**Lock Management:**
- Asyncio lock prevents concurrent BLE access
- Lock passed to both `DeviceReader` and `DeviceWriter`

### Device Encryption

Devices can require encryption for control commands:
- Encrypted devices: All controls are read-only (exposed as sensors/binary_sensors)
- Non-encrypted devices: Full read/write access to switches and selects
- Encryption status determined at discovery via `recognize_device()`

## Key Files

- `custom_components/bluetti_bt/__init__.py` - Integration entry point and setup
- `custom_components/bluetti_bt/config_flow.py` - Discovery and configuration UI
- `custom_components/bluetti_bt/coordinator.py` - Polling logic and data reading
- `custom_components/bluetti_bt/sensor.py` - Numeric sensor entities
- `custom_components/bluetti_bt/switch.py` - Boolean control entities
- `custom_components/bluetti_bt/binary_sensor.py` - Boolean status entities
- `custom_components/bluetti_bt/select.py` - Multi-option control entities
- `custom_components/bluetti_bt/types/` - Configuration classes and field mappings
- `custom_components/bluetti_bt/manifest.json` - Integration metadata and BLE patterns

## Important Patterns

**Adding Support for New Fields:**
1. Fields are defined in `bluetti-bt-lib` (external dependency)
2. This integration dynamically queries available fields from device object at runtime
3. Field mappings in `types/` directory map field names to Home Assistant classes
4. Add new mappings to `FieldDeviceClass`, `FieldStateClass`, or `FieldCategory` as needed

**Entity Availability:**
- Entities track unavailable counter
- Marked unavailable after 5 consecutive missed coordinator updates
- Reset when valid data received

**Device Info:**
- Main device identifier: `(DOMAIN, mac_address)`
- Battery pack devices: `(DOMAIN, f"{address}_pack_{num}")`
- Manufacturer: "Bluetti"
- Model: Device type from config

**Privacy:**
- MAC addresses obfuscated in logs: `XX:XX:XX:XX:XX:LAST_BYTE`
- Uses utility functions from `utils.py`

## Dependencies

**External Library:**
- `bluetti-bt-lib==0.1.6` - Handles BLE protocol specifics
- Key classes: `DeviceReader`, `DeviceWriter`, `FieldName` enum
- Functions: `build_device()`, `recognize_device()`, `get_unit()`

**Home Assistant:**
- Requires `bluetooth_adapters` integration
- Uses Home Assistant's Bluetooth component for device presence checks
- Follows standard platform setup (sensor, switch, binary_sensor, select)

## CI/CD

GitHub Actions workflows:
- `.github/workflows/test.yml` - Runs unit tests on every push
- `.github/workflows/hassfest_validation.yml` - Home Assistant validation
- `.github/workflows/HACS.yml` - HACS validation
