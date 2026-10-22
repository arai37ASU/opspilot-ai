# OpsPilot AI - Project Requirements

## 1. Project Overview

OpsPilot AI is an operational intelligence platform designed to analyze service requests and support tickets.

The platform will help teams:
- understand recurring operational issues
- identify tickets at risk of missing SLA targets
- analyze workload and resolution patterns
- surface important trends
- generate AI-assisted management insights

## 2. Problem Statement

Organizations often manage large volumes of service requests across multiple departments.

As ticket volume grows, it becomes difficult to identify recurring issues, prioritize high-risk requests, and understand where operational bottlenecks occur.

OpsPilot AI will combine data analytics, machine learning, and AI-generated insights to help users make faster and more informed operational decisions.

## 3. Target Users

Primary users:
- Operations managers
- Technical support leads
- Service desk managers
- IT managers
- Project and program managers

Secondary users:
- Data analysts
- Business analysts
- Technical teams

## 4. Core MVP Features

### Data Management
- Generate or ingest realistic service-request data
- Store ticket information in a structured format
- Clean and validate ticket data

### Operational Analytics
- Analyze ticket volume
- Measure SLA compliance
- Calculate resolution times
- Compare departments and categories
- Identify recurring issues

### Machine Learning
- Predict whether a ticket is likely to breach SLA
- Compare multiple classification models
- Evaluate model performance

### AI Insights
- Summarize important operational trends
- Explain high-risk areas
- Generate management-focused recommendations

### Dashboard
- Display key operational metrics
- Show ticket trends and SLA performance
- Display AI-generated insights

## 5. Initial Success Metrics

The project will track:

- SLA compliance rate
- Average resolution time
- Median resolution time
- Ticket volume by category
- Ticket volume by department
- SLA breach prediction accuracy
- Precision
- Recall
- F1 score
- ROC-AUC

## 6. Technical Stack

Initial stack:

- Python
- Pandas
- PostgreSQL
- SQL
- scikit-learn
- FastAPI
- pytest
- Git
- GitHub

Later additions may include:

- XGBoost
- SHAP
- Docker
- Streamlit
- LLM API
- GitHub Actions
- AWS

## 7. Project Phases

### Phase 1
Project setup and requirements

### Phase 2
Synthetic dataset generation

### Phase 3
SQL database and analysis

### Phase 4
Exploratory data analysis

### Phase 5
Machine learning

### Phase 6
API development

### Phase 7
Dashboard

### Phase 8
AI insight generation

### Phase 9
Testing, deployment, and documentation