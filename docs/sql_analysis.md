# OpsPilot AI - SQL Analysis Findings

## About this analysis

This document answers the business questions in [dataset_design.md](dataset_design.md) section 10.1 using the SQL in [sql/analysis/](../sql/analysis/). Every number comes from a saved result in [reports/sql/](../reports/sql/), named `<query file>__<query name>.csv`, and each section lists its sources.

The data is the synthetic service-desk dataset (seed 42): 50,295 tickets from January 2024 to December 2025, as a snapshot at the end of 2025-12-31. Because the data is simulated, these findings show what the analysis method can recover; they are not facts about a real organization. Several patterns (workload effects, the Desktop Support staffing cut, the four major incidents) were built into the generator. The point of the analysis is that it finds them using only the ticket data, as it would have to with real data.

To reproduce:

```bash
python -m opspilot.data_generation.generate --seed 42
python -m opspilot.db.load
python -m opspilot.db.analysis
```

Breach rates are over resolved tickets (49,242 of 50,295). Times are medians unless stated, because resolution times are right-skewed.

## Summary

- **15.7% of resolved tickets breached their SLA.** P2 tickets are the most exposed at 37.1%.
- **Busier queues breach more, independent of priority.** For P3 tickets the breach rate rises from 6.9% when the team has under one open ticket per agent to 27.5% at six or more.
- **Weekday after-hours arrivals are 16.5% of tickets but 32.2% of breaches.** A P2 ticket arriving after hours breaches 71.0% of the time, against 28.5% during staffed hours.
- **Network Operations has the highest breach rate (25.2%) and the highest load per agent (4.53 tickets per working day).**
- **Hardware failures breach 44.6% of the time,** far above Desktop Support's other incidents (18.6%), likely because they wait in the same queue as long-running device and software requests.
- **A misrouted first assignment adds 4.5 hours to the median resolution time and 8.2 points to the breach rate.**
- **Semester starts raise Classroom Technology's breach rate from 14.5% to 27.5%.**
- **Spike detection found all four major incidents** without using any incident labels.
- **Halving Desktop Support for April-June 2025 raised its breach rate by 9.8 points** compared with the same quarter a year earlier.

## 1. SLA compliance

Sources: `01_sla_compliance__overall`, `__by_priority`, `__by_team`, `__by_category`, `__monthly_trend`

7,732 of 49,242 resolved tickets breached (15.7%).

| Priority | Resolved | Breach rate |
|---|---|---|
| P1 | 967 | 20.2% |
| P2 | 8,011 | 37.1% |
| P3 | 25,496 | 16.8% |
| P4 | 14,768 | 2.0% |

P2 is worse than P1. P1 tickets have on-call cover outside staffed hours, while P2 tickets have an 8-hour target but wait for the desk to open. Section 3 shows this directly.

| Team | Agents | Resolved | Breach rate |
|---|---|---|---|
| Network Operations | 3 | 6,832 | 25.2% |
| Enterprise Applications | 6 | 8,511 | 24.3% |
| Desktop Support | 8 | 9,371 | 19.0% |
| Classroom Technology | 3 | 2,644 | 17.0% |
| Security Operations | 2 | 2,533 | 14.6% |
| Identity & Access | 4 | 7,787 | 12.7% |
| Service Desk | 6 | 11,564 | 3.1% |

Service Desk's low rate reflects its work rather than unusual efficiency: password resets and how-to questions are quick and have long service-request targets.

By category, Hardware (25.8%) and Network (25.2%) breach most; General Support (5.2%) and Account & Access (7.9%) least.

Monthly breach rates follow the academic year: highest in January and September (17.8% in January 2024, 18.2% in September 2024) and lowest in June and July (10.7% in June 2024, 11.7% in July 2025). There is no sustained upward or downward trend across the two years.

## 2. Workload

Sources: `02_team_workload__tickets_per_agent`, `__breach_by_backlog`

| Team | Agents | Tickets per agent per working day |
|---|---|---|
| Network Operations | 3 | 4.53 |
| Identity & Access | 4 | 3.87 |
| Service Desk | 6 | 3.76 |
| Security Operations | 2 | 2.78 |
| Enterprise Applications | 6 | 2.77 |
| Desktop Support | 8 | 2.30 |
| Classroom Technology | 3 | 1.94 |

This divides all tickets routed to a team by its headcount and the number of working days, so it compares teams rather than describing a shift.

Backlog at arrival is the number of the assigned team's tickets that had already arrived and were still unresolved when a ticket came in, divided by the team's headcount.

| Open tickets per agent at arrival | Resolved | Breach rate | P3 only |
|---|---|---|---|
| 0-1 | 6,260 | 9.2% | 6.9% |
| 1-2 | 11,869 | 12.3% | 12.5% |
| 2-4 | 22,539 | 16.5% | 18.0% |
| 4-6 | 6,392 | 22.1% | 25.2% |
| 6+ | 2,182 | 26.3% | 27.5% |

The rate rises steadily in every bucket. The P3 column holds priority fixed, which rules out the explanation that busy periods simply have more urgent tickets. It does not rule out other differences between busy and quiet periods, such as time of day; the model in a later phase can separate these effects.

## 3. After-hours arrivals

Sources: `03_after_hours__by_arrival_window`, `__by_priority_and_window`

Weekday staffed hours are 08:00-18:00; weekends and holidays have reduced staffing.

| Arrival window | Share of tickets | Breach rate | Share of breaches |
|---|---|---|---|
| Weekday, staffed hours | 75.1% | 11.8% | 56.5% |
| Weekday, after hours | 16.5% | 30.7% | 32.2% |
| Weekend or holiday | 8.4% | 21.1% | 11.3% |

| Priority | Weekday staffed | Weekday after hours | Weekend or holiday |
|---|---|---|---|
| P1 | 19.1% | 21.2% | 27.7% |
| P2 | 28.5% | 71.0% | 48.3% |
| P3 | 12.1% | 34.3% | 23.6% |
| P4 | 1.7% | 3.1% | 2.5% |

The P2 difference between after-hours and staffed arrivals is 42.5 points (95% confidence interval 39.8 to 45.2). An 8-hour target that starts at 19:00 has mostly run out by the time the desk opens.

P1 barely changes after hours on weekdays, which is consistent with on-call cover removing the wait for opening time. It does rise at weekends (27.7%), when on-call staff start immediately but the rest of the queue runs at reduced capacity.

## 4. Academic calendar

Sources: `04_seasonality__by_academic_period`, `__team_breach_by_period`

| Period | Days | Tickets per day | Breach rate |
|---|---|---|---|
| Semester start | 56 | 114.3 | 18.9% |
| Regular | 440 | 77.3 | 16.2% |
| Summer | 200 | 44.5 | 12.2% |
| Winter break | 35 | 28.6 | 9.8% |

| Team | Regular | Semester start | Change |
|---|---|---|---|
| Classroom Technology | 14.5% | 27.5% | +13.0 |
| Identity & Access | 12.3% | 19.4% | +7.1 |
| Enterprise Applications | 24.9% | 29.5% | +4.6 |
| Network Operations | 26.5% | 30.4% | +3.9 |
| Desktop Support | 19.9% | 21.6% | +1.7 |
| Service Desk | 3.4% | 3.1% | -0.3 |
| Security Operations | 15.2% | 12.3% | -2.9 |

Classroom Technology's increase is clearly real (95% interval +8.9 to +17.0 points). Security Operations' apparent decrease is not distinguishable from zero (interval -7.3 to +1.5); it has only 252 resolved tickets in semester-start weeks.

## 5. Misrouting

Sources: `05_misrouting_cost__misrouted_vs_correct`, `__by_owning_team`

A ticket is misrouted when its first assigned team is not the team that owns its subcategory.

| | Resolved | Median hours | Avg. reassignments | Breach rate |
|---|---|---|---|---|
| Routed correctly | 46,783 | 17.1 | 0.06 | 15.3% |
| Misrouted | 2,459 | 21.6 | 1.07 | 23.5% |

Misrouting adds 8.2 points to the breach rate (95% interval 6.5 to 9.9). About 5% of tickets are misrouted for every owning team (4.7% to 5.6%), but the cost differs: misrouted Security Operations tickets breach at 31.1% against 13.7% when routed correctly, and Classroom Technology's double from 16.2% to 32.3%. Teams with short targets lose proportionally more to a few hours of rerouting.

## 6. Resolution times and reopening

Sources: `06_resolution_times__by_subcategory`, `__reopen_effect`

Highest breach rates by subcategory:

| Subcategory | Median hours | 90th percentile | Mean hours | Breach rate |
|---|---|---|---|---|
| device_failure | 20.9 | 43.0 | 24.1 | 44.6% |
| application_error | 19.2 | 40.7 | 22.1 | 35.2% |
| network_outage | 5.3 | 20.0 | 8.8 | 30.0% |
| vpn_wired_issue | 17.2 | 35.6 | 19.8 | 27.1% |
| slow_network | 20.2 | 40.4 | 23.2 | 25.7% |

In every subcategory the mean is above the median, sometimes by a lot (network_outage: 8.8 against 5.3), which is why medians are used throughout.

Hardware device failures stand out. Desktop Support's other incidents breach at 18.6%; device failures breach at 44.6% (95% interval for the difference +23.3 to +28.7 points). Desktop Support also handles new device requests (median 53.3 hours) and software installs (27.5 hours). Long-running requests stay open for days and fill the same queue that urgent hardware incidents wait in.

| | Resolved | Median hours | 90th percentile | Breach rate |
|---|---|---|---|---|
| Not reopened | 46,143 | 16.5 | 41.1 | 14.0% |
| Reopened | 3,099 | 31.6 | 64.4 | 41.3% |

Reopened tickets take almost twice as long and breach about three times as often. Reopening is only known after resolution, so it explains breaches after the fact but cannot be used to predict them.

## 7. Satisfaction

Sources: `07_satisfaction__response_rate_by_breach`, `__score_distribution`, `__by_outcome`, `__by_category`

13,912 resolved tickets have a survey response (28.3%).

| Breached | Reopened | Responses | Mean score | Scored 1-2 |
|---|---|---|---|---|
| No | No | 11,296 | 4.28 | 1.9% |
| No | Yes | 459 | 3.10 | 28.5% |
| Yes | No | 1,729 | 2.85 | 38.7% |
| Yes | Yes | 428 | 2.01 | 78.7% |

Breaching and reopening each lower satisfaction, and together they are much worse than either alone. By category, Licensing scores lowest (3.23, with 27.6% of responses at 1-2) and Security next (3.70).

Response rates are almost identical for breached (27.9%) and on-time (28.3%) tickets, so breaches are not over- or under-represented among respondents. That does not show the survey is unbiased. The generator makes people with very good or very bad experiences more likely to respond, and that kind of bias cannot be measured from the responses alone, because the scores of people who did not respond are never observed. Survey averages describe respondents.

## 8. Issue spikes

Source: `08_recurring_issue_spikes__daily_spikes`

A day is flagged for a subcategory when it has at least four times that subcategory's median daily count and at least 15 tickets above it. The query uses only ticket data.

24 subcategory-days were flagged. Nineteen are password-reset and MFA surges in semester-start weeks. The other five are:

| Day | Subcategory | Tickets | Typical day | Busiest 2 hours |
|---|---|---|---|---|
| 2024-02-13 | wifi_connectivity | 52 | 4 | 34 |
| 2024-09-04 | lecture_capture | 33 | 1 | 15 |
| 2025-03-18 | phishing_report | 37 | 1 | 9 |
| 2025-03-19 | phishing_report | 30 | 1 | 12 |
| 2025-10-07 | network_outage | 40 | 0 | 25 |

These are the four major incidents in the generator (the phishing campaign runs across two days). The lecture-capture failure happened during semester start, so the academic period alone would not have separated it from the seasonal surges; its subcategory and concentration did. The 19 password-reset and MFA days are real spikes but are seasonal, not incidents.

The two-hour peak separates sudden outages (34 and 25 tickets in two hours) from seasonal surges (5 to 11), but not reliably: the phishing campaign was spread over a day and peaks at 9 to 12, inside the seasonal range. A baseline per period, or a dedicated anomaly-detection method, would separate them better.

## 9. Changes over time

Sources: `09_team_drift__quarterly_by_team`, `__largest_year_over_year_changes`

Quarters are compared with the same quarter a year earlier, so the academic calendar does not create false changes.

| Team | Quarter | Breach rate | Change vs. year before | 95% interval |
|---|---|---|---|---|
| Desktop Support | Q2 2025 | 24.8% | +9.8 | +6.4 to +13.2 |
| Security Operations | Q1 2025 | 19.0% | +6.8 | +1.6 to +11.9 |
| Network Operations | Q1 2025 | 24.2% | -6.0 | -10.0 to -2.1 |
| Security Operations | Q3 2025 | 15.7% | +5.2 | -0.4 to +10.7 |
| Enterprise Applications | Q3 2025 | 20.6% | -4.9 | -8.5 to -1.2 |

- **Desktop Support, Q2 2025** is the staffing reduction. The effect is large and clearly outside sampling noise, and the rate returns to its usual level in Q3.
- **Security Operations, Q1 2025** is the March phishing campaign. Excluding 18-20 March, the quarter's breach rate is 12.8%, the same as Q1 2024 (12.2%).
- **Network Operations, Q1 2025** looks like an improvement but is the February 2024 Wi-Fi outage making the earlier quarter worse (30.2%).
- **Security Operations' Q2 and Q3 2025 increases** (+4.0 and +5.2) have intervals that include zero. With about 270-310 resolved tickets a quarter, changes of this size cannot be distinguished from noise.
- **Enterprise Applications, Q3 2025** has an interval that excludes zero, but no known cause: the earlier quarter was simply high (25.5%). With 28 year-over-year team-quarter comparisons, about 1.4 are expected to exclude zero by chance at 95% confidence, so this is most likely one of them.

Without the intervals, the largest-changes list would suggest five separate team changes. Only one of them is a lasting operational change.

## What the data suggests

These follow from the findings above. With real data, each would need confirming against costs and constraints the dataset does not contain.

1. **Cover P2 tickets after hours.** P2 after-hours arrivals breach at 71.0%. Extending on-call cover to P2, or adding an evening shift, targets the largest single gap in the data.
2. **Review Network Operations staffing.** It has the highest breach rate and the highest load per agent, with three agents.
3. **Separate request fulfilment from incident work in Desktop Support.** Device failures breach at more than twice the rate of the team's other incidents while sharing a queue with multi-day requests.
4. **Plan semester-start capacity** for Classroom Technology and Identity & Access, whose breach rates rise 13.0 and 7.1 points in those weeks.
5. **Improve first routing.** Misrouting affects about 5% of tickets but raises their breach rate by 8.2 points, with the largest cost for Security Operations and Classroom Technology.
6. **Treat staffing changes as measurable.** The Desktop Support reduction appears clearly in the quarterly data, so the same comparison can evaluate future changes.

## Limitations

- **Synthetic data.** The relationships were designed, so the analysis demonstrates method, not real-world causes.
- **Associations, not causes.** Comparisons hold at most one factor fixed (priority in section 2). The SLA model and later analysis can account for several factors together.
- **Confidence intervals** use a normal approximation for the difference of two proportions. They are computed in [notebooks/01_eda.ipynb](../notebooks/01_eda.ipynb) (section 8) with a tested helper and saved to [reports/stats/phase3_intervals.csv](../reports/stats/phase3_intervals.csv).
- **Department** was not analyzed here. The exploratory analysis (notebook 01, section 5) shows its apparent differences are mostly explained by the mix of issues each department submits.
- **Cancelled tickets** are excluded from backlog because their cancellation time is not recorded.
- **Snapshot effects** are small: only 45 tickets were unresolved at the snapshot.
