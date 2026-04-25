# PRL — Process Reasoning Layer

A control-plan-driven reasoning layer for time-series data.

---

## What This Is

PRL monitors time-series data and evaluates whether a process is behaving as expected.

It uses:

- Control Plans (engineering-defined rules)
- Time-series data
- Process documentation
- AI-based reasoning

---

## Core Concept

Control Plan → Defines expected behavior  
Data → Shows actual behavior  
PRL → Detects drift and explains it  

---

## Features

- Time-series monitoring
- Control plan evaluation
- Drift detection (not just alarms)
- Rate-of-change tracking
- Operator notes
- AI-based explanation layer

---

## Running the Apps

### Dashboard

streamlit run app/prl_dashboard.py --server.port 8510

### Control Plan Builder

streamlit run app/prl_control_plan_builder.py --server.port 8511


---

## Data Sources

PRL works with any time-series data source, including:

- SCADA systems
- DCS systems
- IIoT platforms
- APIs or databases

PRL does not require a specific data stack.

---

## API Requirement

PRL uses a backend reasoning service.

If no API key is configured, reasoning will return:

Explanation failed: 401 Invalid or expired token


To enable reasoning, configure:

PRL_API_KEY
BACKEND_BASE_URL


---

## Notes

This repository contains the PRL framework only.

Deployment, data pipelines, and integrations are environment-specific.

