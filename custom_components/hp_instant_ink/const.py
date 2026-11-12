"""Constants for the HP Instant Ink integration."""

from datetime import timedelta

DOMAIN = "hp_instant_ink"

CONF_PLAN_PAGES = "plan_pages"
CONF_ROLLOVER_MAX = "rollover_max"
CONF_BILLING_DAY = "billing_day"
CONF_OVERAGE_BLOCK_SIZE = "overage_block_size"
CONF_OVERAGE_BLOCK_PRICE = "overage_block_price"
CONF_CARRY_OVERAGE_LEFTOVER = "carry_overage_leftover"
CONF_INITIAL_PRINTED = "initial_printed"
CONF_INITIAL_ROLLOVER = "initial_rollover"
CONF_MODEL = "model"
CONF_SERIAL = "serial"

DEFAULT_PLAN_PAGES = 50
DEFAULT_ROLLOVER_MAX = 150
DEFAULT_OVERAGE_BLOCK_SIZE = 10
DEFAULT_OVERAGE_BLOCK_PRICE = 1.5

UPDATE_INTERVAL = timedelta(minutes=5)
HISTORY_ATTRIBUTE_LIMIT = 24

SERVICE_ADJUST = "adjust"
ATTR_PRINTED_PAGES = "printed_pages"
ATTR_ROLLOVER_PAGES = "rollover_pages"
ATTR_PERIOD_START = "period_start"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
