from enum import Enum

SLOPE_THRESHOLD_FLAG = 14.0
SLOPE_THRESHOLD_SUSCEPTIBLE = 16.0


class SlopeStatus(str, Enum):
    SAFE = "SAFE"
    FLAG = "FLAG FOR REVIEW"
    SUSCEPTIBLE = "SUSCEPTIBLE"


class DepositionalStatus(str, Enum):
    SAFE = "SAFE (Beyond Runout)"
    PRONE = "PRONE (Within Runout Zone)"


class OverallStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED SAFE"
    REVIEW = "MANUAL REVIEW REQUIRED"
