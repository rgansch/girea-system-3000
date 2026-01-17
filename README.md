# Girea System 3000

This is a custom component for Home Assistant to integrate the Gira System 3000 devices via espHome bluetooth proxy or other bluetooth adapters.

Currently just the shutter "Jal+Schaltuhr" and climate "Thermostat" controller are implemented and tested.

> [!NOTE]
> Code was generated with Gemini 2.5 Flash support.

### Installation:

#### HACS

- Ensure that HACS is installed
- Add this repository as a custom repository
- Search for and install the "Girea System 3000" integration
- Restart Home Assistant

#### Manual installation

- Download the latest release
- Unpack the release and copy the custom_components/danfoss_ally directory into the 
  custom_components directory of your Home Assistant installation
- Restart Home Assistant

## Setup

### Automatic setup:
- Bring the Gira device into pairing mode
- Open the Gira integration in HA, the Gira device will show up automatically
- Add device, MAC address and name are filled automatically (name can be changed)

### Manual setup:
- If automatic discovery does not work, you can manually add the device with its MAC address
- Getting the MAC address can be tricky, some methods:
  - Use the homeassistant BLE integration and observe RSSI while getting the BLE antenna very close to the Gira device
  - Use a PC with nRF scanner hardware and wireshark to search for devices with Gira manufacturing data
- Click "Add device" in  the Gira integration and enter the MAC address and a name

### Additional Sensor entities in HA:
- To create custom displays (e.g. graphs) with the sensor data from the Gira devices, see template_editor.md on How-To create sensor entities in HA.

## Known issues

- There is still a little delay between pushing the button in the home assistant ui and actual start of the shutter movement. Delay is shorter the better the BLE connection. Using external antennas can improve it a lot.
- Thermostat integration does not provide the current heating status. Might be hard to implement (not part of BLE advertisments, would require establishing a BLE connection every x seconds for active polling)
