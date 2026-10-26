# Model Card: SLA Breach Risk

A model card summarizes what a model is for, how it was evaluated, and where it should not be trusted. This one follows the structure proposed by Mitchell et al. (2019), "Model Cards for Model Reporting".

## Model details

| | |
|---|---|
| Task | Estimate, when a service-desk ticket is created, the probability that it will miss its SLA resolution target |
| Model | XGBoost gradient-boosted trees (depth 3, learning rate 0.05, 500 trees), in a scikit-learn pipeline with one-hot encoding and median imputation |
| Output | A probability between 0 and 1, and a flag when it is at least 0.457 |
| Training data | 34,426 resolved tickets created 2024-02-01 to 2025-06-30 |
| Evaluated | Once, on 11,747 resolved tickets created 2025-07-01 to 2025-12-17, from commit `e6d8fe5` |
| Code | `src/opspilot/modeling/`; rebuild with `python -m opspilot.modeling.train` |
| Version | scikit-learn 1.9.1, XGBoost 3.4.1 |
| Data | **Synthetic.** Generated to resemble a university IT service desk; see [dataset_design.md](dataset_design.md) |

## Intended use

- **Triage support.** Flag newly created tickets with a high risk of breaching so a lead can look at them early: reassign, escalate, or contact the requester.
- **Users:** service-desk leads and operations managers.
- **Operating point:** the threshold 0.457 was chosen to flag about 10% of tickets, an assumed review capacity. The desk should choose its own point from the capacity curve below.
- **Risk display:** predicted probabilities are well calibrated and can be shown as percentages.

## Out-of-scope uses

- **Judging individual agents or teams.** The model predicts from ticket attributes and queue conditions. A team with many flags is a team with risky work, not a team performing badly.
- **Deciding which tickets get worked.** It is a prompt to look, not a replacement for triage. Unflagged tickets still breach (see below).
- **Real service desks without retraining and re-evaluation.** It was trained on synthetic data. Its scores describe how well the method recovers the simulated patterns, not how it would do on real tickets.
- **Predicting after creation.** It uses only information available at creation. Information that arrives later (reassignments, reopens) is deliberately excluded and would need a different model.

## Factors

Performance was checked by **assigned team** (seven teams) and by **month** of the test period. The exploratory analysis found department and urgent wording to be proxies for issue type and priority, so they are not used as features.

## Metrics

| Metric | Why |
|---|---|
| Average precision (primary) | Breaches are 15.7% of tickets and the model's job is to rank tickets for attention |
| ROC-AUC | Ranking quality independent of the base rate |
| Brier score, expected calibration error | Whether predicted probabilities mean what they say |
| Precision and recall at the threshold | What the desk experiences: how many flags are real, how many breaches are reached |
| 95% bootstrap intervals | Uncertainty from which tickets happened to fall in the test period |

All choices of model, settings and threshold were made on three time-ordered validation folds inside the training period. The test period was scored once.

## Results

### Test period, overall

| Metric | Value | 95% interval | Validation mean |
|---|---|---|---|
| Average precision | 0.680 | 0.661-0.699 | 0.672 |
| ROC-AUC | 0.897 | 0.890-0.904 | 0.894 |
| Brier score | 0.082 | 0.078-0.085 | 0.084 |
| Expected calibration error | 0.005 | | 0.004 |
| Share flagged at threshold | 10.1% | | |
| Precision at threshold | 71.3% | 68.7-73.8% | |
| Recall at threshold | 46.0% | 43.6-48.2% | |

At the threshold the model flagged 1,189 tickets: 848 breached and 341 did not. It did not flag 995 tickets that breached.

### Compared with simpler approaches (test period)

| Approach | Average precision |
|---|---|
| This model | 0.680 |
| Logistic regression with two interaction terms | 0.666 |
| The issue type's recent breach rate alone | 0.313 |
| No information (base rate) | 0.157 |

The logistic regression is a reasonable alternative: almost as accurate and easier to inspect.

### By team (test period)

| Team | Tickets | Breach rate | ROC-AUC | Flagged | Precision | Recall |
|---|---|---|---|---|---|---|
| Network Operations | 1,681 | 26.1% | 0.847 | 15.9% | 74.6% | 45.7% |
| Enterprise Applications | 1,958 | 23.1% | 0.838 | 15.1% | 69.2% | 45.1% |
| Desktop Support | 2,209 | 18.7% | 0.884 | 13.9% | 69.2% | 51.6% |
| Security Operations | 614 | 16.8% | 0.858 | 7.7% | 93.6% | 42.7% |
| Classroom Technology | 683 | 16.5% | 0.863 | 9.2% | 84.1% | 46.9% |
| Identity & Access | 1,918 | 12.5% | 0.887 | 8.3% | 65.4% | 43.5% |
| Service Desk | 2,684 | 3.2% | 0.963 | 1.8% | 61.2% | 35.3% |

No team is poorly served, but most flags fall on three teams, which matters for planning who reviews them.

### Review capacity trade-off (validation folds)

| Share of tickets reviewed | Precision | Recall |
|---|---|---|
| 5% | 87.8% | 27.6% |
| 10% | 70.8% | 44.5% |
| 15% | 59.9% | 56.5% |
| 20% | 53.1% | 66.7% |
| 30% | 42.6% | 80.4% |

### What the model relies on

Permutation importance and SHAP values agree on the main drivers: the issue type's recent breach rate, the SLA target, priority, hours until the desk next opens, and the assigned team's open tickets per agent. Academic period, channel, requester type and holidays contribute almost nothing. Importance describes this model, not causes, and correlated features share credit. Per-ticket reasons are available from `opspilot.modeling.explain`.

## Limitations and caveats

1. **Synthetic data makes the scores optimistic.** Most of what drives a breach in the generator (issue type, priority, the wait until opening) is visible at creation. Real tickets have more unobserved causes, and a real deployment should expect lower scores.
2. **Half of breaches are missed at this capacity.** Breaches caused by events after creation (reopens, reassignments, unexpectedly long work) look ordinary when the ticket arrives.
3. **The review load varies.** A fixed threshold flags more tickets in riskier periods: 6.5% of tickets in July and 10-11% in later months of the test period. A fixed daily quota would keep the load constant but treat calm and busy days alike.
4. **Zeros are read as missing.** The pipeline feeds XGBoost a sparse matrix, and XGBoost treats zeros that are not stored as missing values, learning a default branch for them. This is consistent between training and scoring and is what was evaluated; the preprocessing is fixed to always produce sparse output so it cannot change from batch to batch.
5. **The capacity is assumed.** The 10% review capacity has not been measured.
6. **History features need warm-up.** Recent breach rates are undefined for a new team or issue type; the pipeline imputes them with a missing-value flag, but predictions for new categories are less reliable.

## Monitoring and retraining

- **Drift.** Track the population stability index of the rolling-history features, starting with the team's 30-day breach rate, the one feature that moved between training and test.
- **Performance.** Once outcomes are known, track average precision, calibration and the share flagged by team and month.
- **Retraining.** Repeat the same process: validation folds, the selection rule, a threshold set on validation, and a single test evaluation. Consider dropping the features that contribute nothing, and comparing dense with sparse input to XGBoost, on the validation folds first.

## Ethical considerations

The data is synthetic and contains no personal information. On real data, the main risk is misuse as a performance measure for people or teams, which this card rules out. Flags should prompt help, such as earlier attention or more staff, not blame.
