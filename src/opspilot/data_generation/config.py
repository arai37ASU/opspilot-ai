"""Parameters for the synthetic service-desk dataset.

Everything that controls how realistic the data looks lives here, so the
generator modules contain logic only. The numbers are starting points; they
are tuned against business-level summaries (breach rate, volume by weekday,
resolution times) in docs/dataset_design.md, never against model scores.

Probability weights are listed in the same order as the matching constant
list (CATEGORIES, PRIORITIES, CHANNELS, ...).
"""

from dataclasses import dataclass
from datetime import date, datetime

DEFAULT_SEED = 42

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)  # data snapshot is taken at the end of this day
TARGET_TICKET_COUNT = 50_000  # expected volume before major-incident bursts

REQUESTER_TYPES = ["student", "faculty", "staff"]
CHANNELS = ["portal", "email", "phone", "chat", "walk_in"]
PRIORITIES = ["P1", "P2", "P3", "P4"]
TICKET_TYPES = ["incident", "service_request"]
STATUSES = ["resolved", "open", "in_progress", "cancelled"]

DEPARTMENTS = [
    "Engineering",
    "Arts & Sciences",
    "Business School",
    "Health Sciences",
    "Library",
    "Finance",
    "Human Resources",
    "Admissions",
    "Student Services",
    "Research Office",
]

CATEGORIES = [
    "Software",
    "Hardware",
    "Account & Access",
    "Network",
    "Security",
    "Classroom & AV",
    "Licensing",
    "General Support",
]


# --- Teams and SLA policy -------------------------------------------------

# Sized roughly to steady demand. Security Operations and Classroom
# Technology are small because their pressure comes in spikes (phishing
# campaigns, semester starts) rather than every day.
TEAM_AGENTS = {
    "Service Desk": 6,
    "Identity & Access": 4,
    "Desktop Support": 8,
    "Enterprise Applications": 6,
    "Network Operations": 3,
    "Security Operations": 2,
    "Classroom Technology": 3,
}


@dataclass(frozen=True)
class StaffingChange:
    team: str
    start: date
    end: date
    agents: int


# Half of Desktop Support is out for a quarter. This creates drift that a
# random train/test split would hide.
STAFFING_CHANGES = [
    StaffingChange("Desktop Support", date(2025, 4, 1), date(2025, 6, 30), agents=4),
]

SLA_HOURS = {
    ("incident", "P1"): 4,
    ("incident", "P2"): 8,
    ("incident", "P3"): 24,
    ("incident", "P4"): 72,
    ("service_request", "P2"): 24,
    ("service_request", "P3"): 72,
    ("service_request", "P4"): 120,
}


# --- Requesters ------------------------------------------------------------

REQUESTER_TYPE_WEIGHTS = [0.45, 0.20, 0.35]

# Students only appear in academic units; administrative offices are staff.
DEPARTMENT_WEIGHTS = {
    "student": [0.30, 0.35, 0.18, 0.12, 0.05, 0.00, 0.00, 0.00, 0.00, 0.00],
    "faculty": [0.25, 0.35, 0.15, 0.15, 0.03, 0.00, 0.00, 0.00, 0.00, 0.07],
    "staff": [0.08, 0.10, 0.06, 0.08, 0.08, 0.14, 0.10, 0.12, 0.16, 0.08],
}

# Category depends on who is asking, not on department. Any department effect
# in the final data comes through this mix (deliberate confounding).
CATEGORY_WEIGHTS = {
    "student": [0.12, 0.08, 0.35, 0.20, 0.04, 0.00, 0.05, 0.16],
    "faculty": [0.18, 0.12, 0.15, 0.10, 0.05, 0.25, 0.07, 0.08],
    "staff": [0.26, 0.16, 0.17, 0.09, 0.07, 0.02, 0.10, 0.13],
}

CHANNEL_WEIGHTS = {
    "student": [0.40, 0.10, 0.08, 0.27, 0.15],
    "faculty": [0.25, 0.30, 0.25, 0.08, 0.12],
    "staff": [0.40, 0.25, 0.18, 0.12, 0.05],
}

# People pick up the phone or walk in when something is urgent, so these
# channels scale up the P1 and P2 weights before renormalising.
CHANNEL_URGENCY_BOOST = {"phone": 1.6, "walk_in": 1.3}


# --- Subcategories -----------------------------------------------------------


@dataclass(frozen=True)
class Subcategory:
    category: str
    ticket_type: str
    team: str
    weight: float  # relative frequency within its category
    median_work_hours: float  # typical hands-on time at P3 with no queue
    priority_weights: tuple[float, float, float, float]  # P1, P2, P3, P4


SUBCATEGORIES = {
    # Software
    "application_error": Subcategory("Software", "incident", "Enterprise Applications", 0.30, 6.0, (0.03, 0.17, 0.55, 0.25)),
    "software_install": Subcategory("Software", "service_request", "Desktop Support", 0.30, 10.0, (0.00, 0.05, 0.50, 0.45)),
    "os_update_issue": Subcategory("Software", "incident", "Desktop Support", 0.15, 5.0, (0.01, 0.09, 0.55, 0.35)),
    "email_calendar": Subcategory("Software", "incident", "Enterprise Applications", 0.25, 3.0, (0.02, 0.18, 0.55, 0.25)),
    # Hardware
    "device_failure": Subcategory("Hardware", "incident", "Desktop Support", 0.30, 8.0, (0.02, 0.20, 0.58, 0.20)),
    "printer_issue": Subcategory("Hardware", "incident", "Desktop Support", 0.30, 4.0, (0.00, 0.08, 0.52, 0.40)),
    "peripheral_issue": Subcategory("Hardware", "incident", "Desktop Support", 0.20, 3.0, (0.00, 0.05, 0.50, 0.45)),
    "new_device_request": Subcategory("Hardware", "service_request", "Desktop Support", 0.20, 30.0, (0.00, 0.05, 0.45, 0.50)),
    # Account & Access
    "password_reset": Subcategory("Account & Access", "service_request", "Service Desk", 0.40, 0.5, (0.00, 0.15, 0.60, 0.25)),
    "mfa_issue": Subcategory("Account & Access", "incident", "Identity & Access", 0.25, 1.5, (0.02, 0.25, 0.55, 0.18)),
    "permission_request": Subcategory("Account & Access", "service_request", "Identity & Access", 0.20, 8.0, (0.00, 0.10, 0.55, 0.35)),
    "account_provisioning": Subcategory("Account & Access", "service_request", "Identity & Access", 0.15, 12.0, (0.00, 0.15, 0.60, 0.25)),
    # Network
    "wifi_connectivity": Subcategory("Network", "incident", "Network Operations", 0.50, 2.5, (0.02, 0.18, 0.60, 0.20)),
    "vpn_wired_issue": Subcategory("Network", "incident", "Network Operations", 0.25, 4.0, (0.02, 0.15, 0.58, 0.25)),
    "slow_network": Subcategory("Network", "incident", "Network Operations", 0.20, 5.0, (0.01, 0.09, 0.55, 0.35)),
    "network_outage": Subcategory("Network", "incident", "Network Operations", 0.05, 2.0, (0.35, 0.45, 0.18, 0.02)),
    # Security
    "phishing_report": Subcategory("Security", "incident", "Security Operations", 0.50, 1.0, (0.05, 0.35, 0.50, 0.10)),
    "malware_infection": Subcategory("Security", "incident", "Security Operations", 0.15, 3.0, (0.20, 0.50, 0.27, 0.03)),
    "suspicious_login": Subcategory("Security", "incident", "Security Operations", 0.30, 1.5, (0.15, 0.45, 0.35, 0.05)),
    "data_exposure": Subcategory("Security", "incident", "Security Operations", 0.05, 4.0, (0.45, 0.40, 0.13, 0.02)),
    # Classroom & AV
    "projector_display": Subcategory("Classroom & AV", "incident", "Classroom Technology", 0.45, 1.5, (0.05, 0.35, 0.45, 0.15)),
    "lecture_capture": Subcategory("Classroom & AV", "incident", "Classroom Technology", 0.30, 5.0, (0.02, 0.20, 0.55, 0.23)),
    "room_audio": Subcategory("Classroom & AV", "incident", "Classroom Technology", 0.25, 2.0, (0.04, 0.30, 0.50, 0.16)),
    # Licensing
    "new_license": Subcategory("Licensing", "service_request", "Enterprise Applications", 0.45, 20.0, (0.00, 0.05, 0.50, 0.45)),
    "license_renewal": Subcategory("Licensing", "service_request", "Enterprise Applications", 0.25, 30.0, (0.00, 0.10, 0.55, 0.35)),
    "activation_failure": Subcategory("Licensing", "incident", "Enterprise Applications", 0.30, 3.0, (0.01, 0.14, 0.55, 0.30)),
    # General Support
    "how_to_question": Subcategory("General Support", "service_request", "Service Desk", 0.50, 1.0, (0.00, 0.02, 0.38, 0.60)),
    "equipment_loan": Subcategory("General Support", "service_request", "Service Desk", 0.25, 6.0, (0.00, 0.05, 0.45, 0.50)),
    "other": Subcategory("General Support", "incident", "Service Desk", 0.25, 5.0, (0.01, 0.09, 0.50, 0.40)),
}


# --- Arrival patterns --------------------------------------------------------

# Relative ticket volume by hour of day, 00:00 to 23:00.
HOUR_WEIGHTS = [
    0.2, 0.1, 0.1, 0.1, 0.1, 0.2, 0.4, 1.0,
    2.5, 4.0, 4.5, 4.0, 3.0, 3.5, 4.0, 3.5,
    3.0, 2.0, 1.4, 1.1, 1.0, 0.9, 0.6, 0.4,
]

# Monday to Sunday.
WEEKDAY_WEIGHTS = [1.15, 1.10, 1.05, 1.00, 0.85, 0.25, 0.20]


@dataclass(frozen=True)
class CalendarPeriod:
    name: str
    start: date
    end: date  # inclusive
    volume_multiplier: float
    category_multipliers: dict[str, float]


_SEMESTER_START_MIX = {"Account & Access": 1.8, "Classroom & AV": 2.0}
_SUMMER_MIX = {"Classroom & AV": 0.3}

# Periods must not overlap. Days outside every period use a multiplier of 1.
CALENDAR_PERIODS = [
    CalendarPeriod("winter_break", date(2024, 1, 1), date(2024, 1, 7), 0.4, {}),
    CalendarPeriod("semester_start", date(2024, 1, 16), date(2024, 1, 29), 1.5, _SEMESTER_START_MIX),
    CalendarPeriod("summer", date(2024, 5, 11), date(2024, 8, 18), 0.6, _SUMMER_MIX),
    CalendarPeriod("semester_start", date(2024, 8, 26), date(2024, 9, 8), 1.6, _SEMESTER_START_MIX),
    CalendarPeriod("winter_break", date(2024, 12, 21), date(2025, 1, 5), 0.4, {}),
    CalendarPeriod("semester_start", date(2025, 1, 13), date(2025, 1, 26), 1.5, _SEMESTER_START_MIX),
    CalendarPeriod("summer", date(2025, 5, 10), date(2025, 8, 17), 0.6, _SUMMER_MIX),
    CalendarPeriod("semester_start", date(2025, 8, 25), date(2025, 9, 7), 1.6, _SEMESTER_START_MIX),
    CalendarPeriod("winter_break", date(2025, 12, 20), date(2025, 12, 31), 0.4, {}),
]

# University closures: low volume and weekend staffing.
HOLIDAYS = {
    date(2024, 5, 27),
    date(2024, 7, 4),
    date(2024, 9, 2),
    date(2024, 11, 28),
    date(2024, 11, 29),
    date(2025, 5, 26),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 27),
    date(2025, 11, 28),
}
HOLIDAY_VOLUME_MULTIPLIER = 0.3


@dataclass(frozen=True)
class MajorIncident:
    start: datetime
    duration_hours: float
    subcategory: str
    ticket_count: int


MAJOR_INCIDENTS = [
    MajorIncident(datetime(2024, 2, 13, 10, 0), 3, "wifi_connectivity", 45),
    MajorIncident(datetime(2024, 9, 4, 9, 0), 6, "lecture_capture", 30),
    MajorIncident(datetime(2025, 3, 18, 8, 30), 24, "phishing_report", 60),
    MajorIncident(datetime(2025, 10, 7, 13, 0), 4, "network_outage", 40),
]


# --- Staffing and queue behaviour ------------------------------------------------

# (start hour, end hour) when agents are working. P1 tickets bypass this
# through on-call cover.
WEEKDAY_STAFFED_HOURS = (8, 18)
WEEKEND_STAFFED_HOURS = (10, 16)
WEEKEND_CAPACITY_FACTOR = 0.4  # share of agents on weekends and holidays

PRIORITY_WORK_MULTIPLIER = {"P1": 0.3, "P2": 0.6, "P3": 1.0, "P4": 1.5}
PRIORITY_QUEUE_MULTIPLIER = {"P1": 0.1, "P2": 0.4, "P3": 1.0, "P4": 1.3}

# Log-normal spread of work time. 0.8 means a ticket at twice the median
# is common (about 1 in 5) and one at five times the median is rare.
WORK_TIME_SIGMA = 0.8

# Queue wait rises with open tickets per agent but levels off at
# MAX_QUEUE_WAIT_HOURS. A linear curve would feed back on itself during
# surges: longer waits -> bigger backlog -> longer waits.
MAX_QUEUE_WAIT_HOURS = 24.0
QUEUE_HALF_LOAD = 4.0  # tickets per agent at which wait reaches half the maximum
QUEUE_WAIT_SIGMA = 0.5

MISROUTE_RATE = 0.05
EXTRA_REASSIGNMENT_RATE = 0.03  # correctly routed tickets that still get moved
REASSIGNMENT_DELAY_MEDIAN_HOURS = 3.0

REOPEN_BASE_RATE = 0.05
REOPEN_FAST_FIX_RATE = 0.12  # applies when work time is under half the median
REOPEN_DETECTION_MEDIAN_HOURS = 12.0  # time until the requester notices
REOPEN_WORK_FRACTION = 0.6  # second fix is shorter than the first

CANCEL_RATE = 0.02


# --- Satisfaction survey -----------------------------------------------------

SURVEY_BASE_RESPONSE_RATE = 0.22
SURVEY_EXTREME_BOOST = 0.20  # extra response probability for very good or bad experiences

SATISFACTION_BASE = 4.3
SATISFACTION_BREACH_PENALTY = 1.0
SATISFACTION_REOPEN_PENALTY = 0.8
SATISFACTION_PENALTY_PER_DAY = 0.15
SATISFACTION_CATEGORY_PENALTY = {"Security": 0.4, "Licensing": 0.5}
SATISFACTION_NOISE = 0.7


# --- Descriptions --------------------------------------------------------------

DESCRIPTION_VAGUE_RATE = 0.10  # "not working, please help" with no issue detail
DESCRIPTION_GREETING_RATE = 0.30
DESCRIPTION_CLOSING_RATE = 0.30
DESCRIPTION_LOWERCASE_RATE = 0.05

# Urgency wording is known at submission, so it may correlate with priority.
# It must never describe the outcome ("still broken", "escalated").
URGENCY_PHRASE_RATE = {"P1": 0.40, "P2": 0.25, "P3": 0.05, "P4": 0.02}
