# OpsPilot AI - Modeling the SLA Breach Risk

This is the short story of Phase 5. The charts and full tables are in [notebooks/03_modeling.ipynb](../notebooks/03_modeling.ipynb); the facts a user of the model needs are in the [model card](model_card.md).

## 1. A plan before any model

The exploratory analysis ended with a decision record ([notebook 02](../notebooks/02_feature_assessment.ipynb)): the population, a time-based split, three expanding-window validation folds, the features, average precision as the primary metric, a 10% review capacity, and baselines. It became code in `src/opspilot/modeling/config.py`, with each excluded feature listed next to its reason. Two details were added before the results they govern: a selection rule (choose the simplest model within 0.01 average precision of the best) and the order that defines "simplest".

## 2. Baselines first

On the validation folds, predicting the base rate for every ticket scores 0.159 average precision. Using the issue type's recent breach rate as the prediction scores 0.310. Any model had to clearly beat the second number.

## 3. Logistic regression

With encoding, imputation and scaling inside the pipeline, logistic regression reached 0.640. Adding the two interactions found in the exploratory analysis (priority with hours until opening, team with workload) raised it to 0.652, in every fold. Balanced class weights did not help ranking and badly hurt calibration (Brier 0.088 to 0.144), so they were not used.

Two checks before trusting a jump from 0.310 to 0.640: with shuffled labels the pipeline scored exactly the base rate, so nothing leaks through it, and removing feature groups showed the gain comes from priority, the SLA target and arrival time, which is how the data was generated. The shuffled-label check is now a permanent test.

## 4. Tree models and the selection rule

Random forest and XGBoost were tuned on small fixed grids; in both, the more regularized settings won. Mean validation average precision:

| Model | Average precision |
|---|---|
| XGBoost | 0.672 |
| Random forest | 0.657 |
| Logistic regression with interactions | 0.652 |
| Logistic regression | 0.640 |

The rule selected XGBoost, 0.020 ahead of the best linear model and ahead in every fold. At the 10% capacity the practical difference is about one percentage point of precision and recall.

## 5. Threshold and calibration

On out-of-fold predictions, XGBoost was already well calibrated (expected calibration error 0.004), and a time-respecting isotonic calibration made ranking worse, so none was added. The threshold that flags 10% of validation tickets is a predicted risk of 0.457. Because it is fixed, the share flagged follows the risk of each period.

## 6. One test evaluation

The test period was scored once by a command that refuses to run on uncommitted code or to overwrite an earlier result. The result records its commit (`e6d8fe5`).

| Metric | Test | Validation |
|---|---|---|
| Average precision | 0.680 (0.661-0.699) | 0.672 |
| ROC-AUC | 0.897 | 0.894 |
| Precision at threshold | 71.3% | |
| Recall at threshold | 46.0% | |

Test results match validation. The logistic regression with interactions scored 0.666 on the same period.

## 7. What the model relies on

Permutation importance and SHAP values agree on the issue type's recent breach rate, the SLA target, priority, hours until opening and team workload. While building the explanations, a latent risk came to light: scikit-learn chooses sparse or dense output per batch, and XGBoost reads unstored zeros in sparse input as missing. Every batch had in fact been sparse, so predictions were unaffected (verified by refitting and comparing), but the preprocessing now always produces sparse output, and explanations are computed with XGBoost's own TreeSHAP on exactly the matrix the model predicts from.

## What I would do differently with real data

- Expect lower scores: real tickets have causes that are not visible at creation.
- Measure the review capacity and the cost of a missed breach before choosing the threshold.
- Run the model alongside the current process for a few weeks and compare which tickets it would have flagged.
