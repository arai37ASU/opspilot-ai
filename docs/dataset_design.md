# OpsPilot AI - Synthetic Dataset Design

## 1. Purpose

OpsPilot AI needs service-request data with enough realistic structure to support SQL analysis, exploratory analysis, and an SLA breach prediction model. Real ticket data is rarely public and usually contains personal information, so the project uses a synthetic dataset.

The goal is not random data. The dataset simulates the process that produces tickets: requests arrive over time, are routed to teams with limited capacity, wait in queues, and are resolved. SLA breaches are not sampled directly. A ticket breaches when its simulated resolution time exceeds its SLA target. This keeps the relationships in the data indirect and noisy, which is closer to how real operational data behaves.

## 2. Simulated Organization

The data represents the central IT service desk of a mid-sized university with roughly 15,000 students and 3,000 faculty and staff.

- Time range: 2024-01-01 to 2025-12-31 (two academic years)
- Target volume: about 50,000 tickets (about 70 per day on average)
- Target overall breach rate: roughly 12-20%, as an outcome of the simulation rather than a hard-coded value

The university setting was chosen because it produces natural, explainable patterns: semester-start surges, quiet summers, low weekend volume, and classroom equipment that has to work before a lecture starts.

## 3. Tables

### 3.1 `tickets`

One row per ticket.

| Column | Postgres type | pandas dtype | Description |
|---|---|---|---|
| `ticket_id` | TEXT | string | Unique identifier, `TKT-000001` onward, in creation order |
| `created_at` | TIMESTAMP | datetime64 | Submission time, campus local time |
| `channel` | TEXT | category | `portal`, `email`, `phone`, `chat`, `walk_in` |
| `requester_type` | TEXT | category | `student`, `faculty`, `staff` |
| `department` | TEXT | category | Requester's unit (section 4.1) |
| `category` | TEXT | category | Top-level issue type (section 4.2) |
| `subcategory` | TEXT | category | Specific issue type (section 4.2) |
| `ticket_type` | TEXT | category | `incident` or `service_request`, determined by subcategory |
| `priority` | TEXT | ordered category | `P1` critical, `P2` high, `P3` medium, `P4` low |
| `assigned_team` | TEXT | category | Team the ticket was first routed to |
| `description` | TEXT | string | Free-text problem description as written at submission |
| `sla_hours` | NUMERIC(6,1) | float | Resolution target from the SLA policy |
| `sla_due_at` | TIMESTAMP | datetime64 | `created_at + sla_hours` |
| `status` | TEXT | category | `resolved`, `open`, `in_progress`, `cancelled` at the snapshot date |
| `resolved_at` | TIMESTAMP, nullable | datetime64 | Resolution time; NULL unless resolved |
| `resolution_hours` | NUMERIC(8,2), nullable | float | Hours from creation to resolution; NULL unless resolved |
| `resolved_by_team` | TEXT, nullable | category | Team that resolved the ticket; differs from `assigned_team` after reassignment |
| `reassignment_count` | SMALLINT | Int64 | Number of times the ticket was rerouted (0-3) |
| `reopened` | BOOLEAN | boolean | Whether the ticket was reopened after its first resolution |
| `satisfaction_score` | SMALLINT, nullable | Int64 | Survey score from 1 to 5; NULL when no survey response |
| `sla_breached` | BOOLEAN, nullable | boolean | `resolution_hours > sla_hours`; NULL unless resolved |

### 3.2 `teams`

| team | agents | Responsibilities |
|---|---|---|
| Service Desk | 6 | Password resets, how-to questions, general support, first-line triage |
| Identity & Access | 4 | MFA, permissions, account provisioning |
| Desktop Support | 8 | Hardware, OS issues, software installation |
| Enterprise Applications | 6 | Application errors, email and calendar, licensing |
| Network Operations | 3 | Wi-Fi, VPN and wired connections, outages |
| Security Operations | 2 | Phishing, malware, suspicious logins, data exposure |
| Classroom Technology | 3 | Projectors, lecture capture, room audio |

Headcounts are sized roughly to steady demand. Security Operations and Classroom Technology are small because their pressure arrives in spikes (phishing campaigns, semester starts) rather than every day.

### 3.3 `sla_policies`

Resolution targets in hours.

| ticket_type | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| incident | 4 | 8 | 24 | 72 |
| service_request | - | 24 | 72 | 120 |

Service requests cannot be P1. Any service request that would be generated as P1 is set to P2.

### 3.4 `subcategories`

The service catalogue: one row per subcategory with its `category`, `ticket_type`, and `owning_team`. In PostgreSQL a composite foreign key from `tickets` enforces that every ticket's category and type match its subcategory. Generator parameters such as work-time medians are not included; they are the simulation's answer key, not data a real service desk would have.

### 3.5 `calendar_days`

A date dimension with one row per day: `day`, `day_of_week` (ISO, 1 = Monday), `is_weekend`, `is_holiday`, and `academic_period` (`regular`, `semester_start`, `summer`, `winter_break`). It lets SQL analysis compare periods without hard-coding dates.

SLA policies and team capacity are kept separate from tickets because ITSM tools treat them as configuration, and the separation gives the SQL phase meaningful joins. The generated `tickets` file also includes `sla_hours` directly so the data is easy to use in pandas.

## 4. Allowed Values

### 4.1 Departments

Engineering, Arts & Sciences, Business School, Health Sciences, Library, Finance, Human Resources, Admissions, Student Services, Research Office.

### 4.2 Categories and subcategories

I = incident, R = service request.

| Category | Subcategories |
|---|---|
| Software | application_error (I), software_install (R), os_update_issue (I), email_calendar (I) |
| Hardware | device_failure (I), printer_issue (I), peripheral_issue (I), new_device_request (R) |
| Account & Access | password_reset (R), mfa_issue (I), permission_request (R), account_provisioning (R) |
| Network | wifi_connectivity (I), vpn_wired_issue (I), slow_network (I), network_outage (I) |
| Security | phishing_report (I), malware_infection (I), suspicious_login (I), data_exposure (I) |
| Classroom & AV | projector_display (I), lecture_capture (I), room_audio (I) |
| Licensing | new_license (R), license_renewal (R), activation_failure (I) |
| General Support | how_to_question (R), equipment_loan (R), other (I) |

## 5. Generation Mechanism

### 5.1 Resolution time

Resolution time is built from two parts: queue wait and work time.

- **Work time** is drawn from a log-normal distribution with a median set per subcategory. Durations are positive and right-skewed, so a normal distribution would be inappropriate. Example medians: password_reset 0.5 hours, wifi_connectivity 2.5 hours, application_error 6 hours, device_failure 8 hours, new_device_request 30 hours. Work time runs on the calendar clock once a ticket is picked up; only the start is gated by staffed hours.
- **Priority** scales work time. P1 tickets are worked faster and P4 tickets slower.
- **Queue wait** increases with the assigned team's open backlog relative to its headcount.
- **Staffed hours.** Non-P1 tickets created outside staffed hours wait until the next staffed period. P1 tickets have on-call coverage.
- **Reassignment** adds delay for each reroute.
- **Reopening** adds a second work period to the total.

### 5.2 Factors that drive SLA breaches

Breaches are a consequence of the mechanism above, not a separate formula:

1. How tight `sla_hours` is relative to the typical work time for the subcategory
2. The assigned team's backlog when the ticket arrives
3. After-hours and weekend arrival
4. Reassignment (post-creation information)
5. Reopening (post-creation information)
6. Semester-start pressure on Classroom Technology and Identity & Access
7. A staffing reduction in Desktop Support (8 to 4 agents) from April to June 2025

Every ticket also receives random variation, so tickets with identical attributes can have different outcomes.

### 5.3 Major incidents

About four major incidents over two years, such as a campus Wi-Fi outage, generate a burst of related tickets within a short window. They create backlog surges and recurring-issue clusters that later analysis and anomaly detection should be able to find.

## 6. Intended Relationships

| Relationship | Rationale |
|---|---|
| Weekday volume peaks around 9-11am and 1-3pm; weekend volume is low | Office-hours behavior |
| Account & Access and Classroom & AV volume rises in the first weeks of each semester; summer is quiet | Academic calendar |
| Students submit more Account & Access tickets, faculty more Classroom & AV, staff more Software and Licensing | Different users have different needs |
| Engineering and Arts & Sciences generate the most volume; Human Resources and Research Office the least | Department size |
| Security incidents and network outages skew toward P1 and P2; how-to questions skew toward P4 | Business impact |
| Phone and walk-in tickets skew toward higher priority | Urgent issues prompt direct contact |
| Small teams breach more often under load | Capacity constraints |
| About 5% of tickets are first routed to the wrong team | Triage error |
| Very fast resolutions are slightly more likely to be reopened | Rushed fixes |
| Satisfaction falls with breaches, reopening, and long waits; Security and Licensing score lower on average | Customer experience |
| Survey responses are more likely from very unhappy or very happy requesters | Non-response bias |
| Most descriptions are informative; about 10% are vague | Real free text is inconsistent |
| Unresolved tickets cluster near the end of the date range | Right-censoring |

## 7. Relationships Deliberately Not Created

- No single feature determines the outcome. For example, P1 tickets do not always breach and Security tickets do not always breach.
- Department has no direct effect on breach risk. It affects the mix of categories and teams, and that mix affects risk. Any apparent department effect is confounding.
- Descriptions do not contain outcome information such as "escalated" or "still broken after three days".
- Satisfaction is generated after resolution and does not influence resolution time.
- Ticket IDs and row order carry no signal beyond creation time.
- Duration fields are never drawn from normal distributions.
- Generator parameters are tuned toward a realistic breach rate and realistic noise, not toward any target model score.

## 8. Feature Availability and Leakage

### 8.1 Known at creation versus known later

| Known at creation (usable as model features) | Known only after creation (not usable as features) |
|---|---|
| `created_at` and fields derived from it | `resolved_at`, `resolution_hours` |
| `channel`, `requester_type`, `department` | `status` |
| `category`, `subcategory`, `ticket_type`, `priority` | `resolved_by_team`, `reassignment_count` |
| `assigned_team` | `reopened` |
| `description` | `satisfaction_score` |
| `sla_hours`, `sla_due_at` | `sla_breached` (model target) |
| Team backlog at creation time, computed from other tickets | |

`assigned_team` records the initial routing and `resolved_by_team` records the final team. Storing only one team column would leak the eventual resolver for misrouted tickets.

### 8.2 Leakage controls for the SLA model

1. Use only fields from the left column of section 8.1 as features.
2. Split train and test by time (about 18 months for training and 6 for testing), not randomly. A random split mixes tickets from the same backlog surge across both sets and hides the 2025 staffing drift.
3. Historical features, such as a team's recent breach rate, use only tickets that were resolved before the current ticket was created. Tickets created earlier but resolved later had unknown outcomes at that point.
4. Fit encoders, scalers, and text vectorizers on training data only, inside a scikit-learn `Pipeline`.
5. Exclude tickets created in the final 14 days of the date range from modeling, because many have no outcome yet. Dropping only the open tickets would bias the data toward fast resolutions.

## 9. Candidate Engineered Features

- **Time:** hour of day, day of week, weekend flag, after-hours flag, hours until the next staffed period, week of semester, holiday flag
- **Workload:** team open backlog at creation, backlog per agent, team tickets in the previous 24 hours
- **Similar-ticket frequency:** tickets in the same subcategory in the previous 2 and 24 hours
- **Historical performance:** team's rolling 30-day breach rate and subcategory median resolution time, computed with the restriction in section 8.2
- **SLA tightness:** `sla_hours` divided by the historical median resolution time for the subcategory
- **Text:** description length, keyword indicators, TF-IDF

These features are implemented in the `ticket_features` materialized view ([sql/features/ticket_features.sql](../sql/features/ticket_features.sql)), which the loader rebuilds on every load. A time-travel test rewinds the database to an earlier cutoff, rebuilds the view, and requires identical features for every ticket created before the cutoff, which fails if any feature uses information from after a ticket's creation. One known approximation remains: cancelled tickets are excluded from the open backlog because their cancellation time is not recorded.

## 10. Questions the Dataset Should Support

### 10.1 Business questions

- What is SLA compliance overall and by team, category, and priority, and how is it trending?
- Which teams are under-staffed for their volume, and during which periods?
- What share of breaches come from after-hours or weekend arrivals?
- How much do semester starts increase breaches, and for which teams?
- Which subcategories have the longest resolution times and highest reopen rates?
- How much delay does misrouting add?
- What drives low satisfaction, and how does survey non-response affect the result?
- Which recurring issues point to root causes worth fixing?

### 10.2 Machine learning questions

- Using only creation-time information, how likely is a ticket to breach its SLA?
- Do Random Forest or XGBoost improve on a Logistic Regression baseline enough to justify the added complexity?
- Which features drive predicted risk, globally and for individual tickets?
- What decision threshold fits a team that can only escalate a limited number of tickets per day?
- Are predicted probabilities well enough calibrated to present as risk percentages?
- How much does performance change on the later test period?
- Later extensions: resolution-time regression, category prediction from descriptions, clustering of recurring issues, and anomaly detection on ticket volume.

## 11. Known Limitations and Simplifications

- The data is synthetic. Analysis demonstrates methods and reasoning, not facts about a real organization.
- SLAs are measured in calendar hours. Many real tools pause SLA clocks outside business hours.
- Staffing is modeled per team as a headcount, not per individual agent or shift.
- Descriptions are generated from templates and are less varied than real user text.
- First-response SLAs, ticket priority changes, and agent-level assignment are not modeled.
- The clean dataset is the ground truth. A separate export with injected data-quality problems (inconsistent casing, duplicates, invalid timestamps) is planned for the data-cleaning phase.

## 12. Reproducibility

The generator uses a fixed random seed, so the same code and seed always produce the same dataset. The generator code is version-controlled; the generated files in `data/` are not.

```bash
python -m opspilot.data_generation.generate --seed 42 --output-dir data/raw
```

This writes `tickets.csv`, `teams.csv`, `sla_policies.csv`, `subcategories.csv`, and `calendar_days.csv` and prints a summary of the checks below.

## 13. Calibration Results (seed 42)

Parameters in `config.py` were tuned against these business-level summaries, not against any model result. Values were also checked on seeds 1, 2, and 3, where they stayed within about half a percentage point.

| Check | Result |
|---|---|
| Tickets | 50,295 (49,242 resolved, 1,008 cancelled, 45 open or in progress) |
| Volume per day | 88.6 on weekdays, 19.0 on weekends |
| SLA breach rate (resolved tickets) | 15.7% |
| Breach rate by priority | P1 20.2%, P2 37.1%, P3 16.8%, P4 2.0% |
| Breach rate by team | Service Desk 3.1% to Network Operations 25.2% |
| Desktop Support, Apr-Jun 2024 vs 2025 | 15.0% vs 24.8% |
| Classroom Technology, semester start vs other days | 27.5% vs 14.1% |
| Security Operations on the phishing-campaign day | 38.5% (14.6% overall) |
| Resolution hours | median 17.3, 90th percentile 43.4 |
| Reopen rate | 6.3% |
| Survey response rate and mean score | 28.3%, 3.99 |

Tuning changes from the first draft of the configuration:

- The first run produced an 11.8% breach rate, below the target band. The queue wait cap was raised from 16 to 24 hours.
- Desktop Support's backlog was inflated by long-running device and software requests, which pushed device_failure incidents to about 45% breached. Team headcounts were rebalanced toward steady demand, and the device_failure median was lowered from 10 to 8 hours.
- The original Desktop Support staffing cut (6 to 4 agents) changed breach rates by only 0 to 4 points depending on the seed. It was strengthened to a cut from 8 to 4 agents.

device_failure remains the subcategory with the highest breach rate (about 43%). This is intentional: hardware incidents share a queue with long-running service requests, which is a realistic finding the analysis phase should surface.

Only 45 tickets are unresolved at the snapshot, because volume is low during winter break and most tickets resolve within two days. Right-censoring is still handled explicitly in the modeling phase, but its practical effect on this dataset is small.
