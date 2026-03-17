"""Constants for the Joulzen integration."""

DOMAIN = "joulzen"

# Config flow keys
CONF_MQTT_TOPIC = "mqtt_topic"
CONF_PUBLISH_INTERVAL = "publish_interval"
CONF_SENSOR_MAPPING = "sensor_mapping"
CONF_HOUSEHOLD_JSON = "household_json"

# Defaults
DEFAULT_MQTT_TOPIC = "jouli"
DEFAULT_PUBLISH_INTERVAL = 5

# Data keys
DATA_COORDINATOR = "coordinator"
