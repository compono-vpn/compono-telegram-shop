from enum import StrEnum


class UtilKey(StrEnum):
    BUTTON = "btn"
    MESSAGE = "msg"
    UNLIMITED = "unlimited"
    SPACE = "space"
    SEPARATOR = "separator"


class ByteUnitKey(StrEnum):
    BYTE = "unit-byte"
    KILOBYTE = "unit-kilobyte"
    MEGABYTE = "unit-megabyte"
    GIGABYTE = "unit-gigabyte"
    TERABYTE = "unit-terabyte"


class TimeUnitKey(StrEnum):
    SECOND = "unit-second"
    MINUTE = "unit-minute"
    HOUR = "unit-hour"
    DAY = "unit-day"
    MONTH = "unit-month"
    YEAR = "unit-year"
