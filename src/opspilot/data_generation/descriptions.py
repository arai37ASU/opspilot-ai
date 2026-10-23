"""Free-text descriptions written as a requester would at submission time.

Descriptions are built from per-subcategory templates, filled with realistic
details, and then roughened (greetings, sign-offs, lowercase, vague messages)
so that text features are useful but not a perfect copy of the category.

Templates must only describe the problem as first reported. Anything that
hints at what happened later (escalations, repeated failures, waiting time)
would leak the outcome into a creation-time feature.
"""

import numpy as np
import pandas as pd

from opspilot.data_generation import config

TEMPLATES = {
    # Software
    "application_error": [
        "{app} keeps crashing whenever I open it.",
        "I get an error ({error_code}) when I try to save in {app}.",
        "{app} freezes right after I log in.",
        "{app} is showing a blank page since this morning.",
    ],
    "software_install": [
        "Can you install {software} on my {device}?",
        "I need {software} installed for {course}.",
        "Requesting {software} on my work computer.",
    ],
    "os_update_issue": [
        "My {device} got stuck during an update and won't finish.",
        "After the latest {os} update my computer is really slow.",
        "Update failed with error {error_code}.",
    ],
    "email_calendar": [
        "Outlook isn't syncing my calendar.",
        "I'm not receiving any emails since yesterday.",
        "The shared mailbox disappeared from Outlook.",
        "Meeting invites are showing the wrong time.",
    ],
    # Hardware
    "device_failure": [
        "My {device} won't turn on.",
        "The screen on my {device} is flickering and going black.",
        "My {device} keeps shutting down randomly.",
        "Spilled water on my {device} and now it doesn't boot.",
    ],
    "printer_issue": [
        "The printer in {building} is jammed.",
        "Can't print to the printer on the {floor} floor of {building}.",
        "Printer says offline even though it's turned on.",
    ],
    "peripheral_issue": [
        "My {peripheral} stopped working.",
        "My {peripheral} isn't recognized when I plug it in.",
        "Second monitor not detected through the docking station.",
    ],
    "new_device_request": [
        "Requesting a new {device} for a new hire starting next month.",
        "My {device} is over five years old, can I get a replacement?",
        "Need a {device} for a new staff member.",
    ],
    # Account & Access
    "password_reset": [
        "I forgot my password and can't log in.",
        "Locked out of my account after too many attempts.",
        "Need my password reset please.",
        "My password expired and the reset link isn't working.",
    ],
    "mfa_issue": [
        "Got a new phone and can't get MFA codes anymore.",
        "MFA push notifications aren't coming through.",
        "The authenticator app gives codes that don't work.",
    ],
    "permission_request": [
        "Need access to the {shared_drive} shared drive.",
        "Please give me edit access in {app} for my role.",
        "Requesting access to the {shared_drive} folder for a project.",
    ],
    "account_provisioning": [
        "New employee needs an account set up before their start date.",
        "Requesting an account for a visiting researcher.",
        "Please create a guest account for a contractor.",
    ],
    # Network
    "wifi_connectivity": [
        "Wi-Fi keeps dropping in {building}.",
        "Can't connect to campus Wi-Fi on my {device}.",
        "No Wi-Fi signal in {building} room {room}.",
        "Wi-Fi connects but there's no internet.",
    ],
    "vpn_wired_issue": [
        "VPN won't connect from home.",
        "The ethernet port in my office in {building} isn't working.",
        "VPN disconnects every few minutes.",
    ],
    "slow_network": [
        "Internet is really slow in {building}.",
        "Downloads take forever on the {building} network.",
        "Video calls keep lagging on the campus network.",
    ],
    "network_outage": [
        "No network at all in {building}.",
        "The whole floor in {building} lost internet.",
        "Nothing is connecting in {building}, wired or wireless.",
    ],
    # Security
    "phishing_report": [
        "Got a suspicious email asking me to verify my account.",
        "Reporting a phishing email pretending to be from payroll.",
        "Email with a strange link saying my mailbox is full.",
    ],
    "malware_infection": [
        "Antivirus flagged a virus on my {device}.",
        "Pop-ups everywhere and my browser homepage changed.",
        "I think I opened a bad attachment and now my files look weird.",
    ],
    "suspicious_login": [
        "Got an alert about a login from another country.",
        "Someone signed into my account and it wasn't me.",
        "Receiving MFA requests I didn't start.",
    ],
    "data_exposure": [
        "Accidentally sent a spreadsheet with student data to the wrong person.",
        "A shared folder with personal information is open to the public.",
        "Lost a USB drive that had confidential files on it.",
    ],
    # Classroom & AV
    "projector_display": [
        "Projector in {building} room {room} won't turn on.",
        "My laptop won't display on the projector in room {room}.",
        "Projector image is blurry in {building} room {room}.",
    ],
    "lecture_capture": [
        "Lecture capture didn't record my {course} class.",
        "The recording for {course} has no audio.",
        "Lecture capture in room {room} shows an error.",
    ],
    "room_audio": [
        "Microphone in {building} room {room} isn't working.",
        "No sound from the room speakers in room {room}.",
        "Wireless mic keeps cutting out during class.",
    ],
    # Licensing
    "new_license": [
        "Need a license for {software}.",
        "Requesting a {software} license for a research project.",
        "Our team needs three more {software} seats.",
    ],
    "license_renewal": [
        "{software} license expires at the end of the month, please renew.",
        "Renewal needed for our department's {software} license.",
        "Getting a warning that our {software} subscription is ending.",
    ],
    "activation_failure": [
        "{software} says my license is invalid.",
        "Can't activate {software}, error {error_code}.",
        "{software} keeps asking me to sign in to activate.",
    ],
    # General Support
    "how_to_question": [
        "How do I set up email on my phone?",
        "How do I share a folder with someone outside the university?",
        "Where do I find the VPN client?",
        "How do I connect to the printer from my laptop?",
    ],
    "equipment_loan": [
        "Can I borrow a laptop for a conference next week?",
        "Need to borrow a projector for an event in {building}.",
        "Requesting a loaner {device} while mine is being repaired.",
    ],
    "other": [
        "Not sure who to ask, my desk phone isn't working.",
        "Question about IT services for my department.",
        "Something is wrong with the display board in {building}.",
    ],
}

# Short messages that say nothing about the issue type. Real queues are full
# of these, and they keep text features from being a stand-in for category.
VAGUE_DESCRIPTIONS = [
    "Not working, please help.",
    "I have an issue, please call me.",
    "Computer problem.",
    "Need help.",
    "Something is broken.",
    "Please contact me about a problem.",
    "It stopped working.",
]

FILL_VALUES = {
    "app": ["Canvas", "Banner", "Workday", "Excel", "Zoom", "Teams", "Slate"],
    "software": ["MATLAB", "SPSS", "Adobe Creative Cloud", "Tableau", "AutoCAD", "Stata", "NVivo"],
    "device": ["laptop", "desktop", "MacBook", "Surface", "work computer"],
    "peripheral": ["keyboard", "mouse", "monitor", "headset", "webcam", "docking station"],
    "os": ["Windows 11", "macOS"],
    "error_code": ["0x80070005", "0x800F081F", "500", "AUTH-401", "E1027", "-36"],
    "course": ["BIO 201", "CS 150", "ECON 101", "MATH 221", "PSY 110", "CHEM 120", "NURS 305"],
    "building": [
        "Hartley Hall", "Science Center", "Main Library", "Business Annex",
        "Engineering Building", "Health Sciences Pavilion", "Student Union", "Admin Building",
    ],
    "floor": ["first", "second", "third", "fourth"],
    "room": ["101", "114", "203", "220", "310", "B12", "Auditorium"],
    "shared_drive": ["Finance", "Admissions", "Research", "Department", "HR Records"],
}

GREETINGS = ["Hi,", "Hello,", "Hi IT team,", "Good morning,"]
CLOSINGS = ["Thanks.", "Thank you!", "Thanks in advance."]
URGENCY_PHRASES = [
    "This is urgent.",
    "Please treat this as urgent.",
    "Need this sorted as soon as possible.",
    "This is blocking my work.",
]


def pick(options: list[str], draw: float) -> str:
    """Choose an option using a uniform draw in [0, 1)."""
    return options[int(draw * len(options))]


def generate_descriptions(tickets: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    """One description per ticket, using subcategory, priority, and incident membership."""
    n = len(tickets)
    # Object arrays, because fixed-width numpy strings would silently truncate
    # a longer value assigned into them.
    fills = {
        key: rng.choice(np.array(values, dtype=object), size=n)
        for key, values in FILL_VALUES.items()
    }

    # Tickets from the same major incident usually come from the same place,
    # which is what makes them look like a cluster later.
    for incident_id in tickets["major_incident_id"].dropna().unique():
        rows = (tickets["major_incident_id"] == incident_id).to_numpy(dtype=bool, na_value=False)
        fills["building"][rows] = rng.choice(FILL_VALUES["building"])

    template_draws = rng.random(n)
    is_vague = rng.random(n) < config.DESCRIPTION_VAGUE_RATE
    urgency_rate = tickets["priority"].map(config.URGENCY_PHRASE_RATE).to_numpy(dtype=float)
    has_urgency = rng.random(n) < urgency_rate
    has_greeting = rng.random(n) < config.DESCRIPTION_GREETING_RATE
    has_closing = rng.random(n) < config.DESCRIPTION_CLOSING_RATE
    is_lowercase = rng.random(n) < config.DESCRIPTION_LOWERCASE_RATE
    phrase_draws = rng.random((n, 3))  # greeting, urgency phrase, closing

    descriptions = []
    for i, subcategory in enumerate(tickets["subcategory"]):
        if is_vague[i]:
            body = pick(VAGUE_DESCRIPTIONS, template_draws[i])
        else:
            template = pick(TEMPLATES[subcategory], template_draws[i])
            body = template.format(**{key: values[i] for key, values in fills.items()})

        parts = []
        if has_greeting[i]:
            parts.append(pick(GREETINGS, phrase_draws[i, 0]))
        parts.append(body)
        if has_urgency[i]:
            parts.append(pick(URGENCY_PHRASES, phrase_draws[i, 1]))
        if has_closing[i]:
            parts.append(pick(CLOSINGS, phrase_draws[i, 2]))

        text = " ".join(parts)
        descriptions.append(text.lower() if is_lowercase[i] else text)

    return pd.Series(descriptions, index=tickets.index, name="description")
