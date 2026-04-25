PROCESS MONITORING & CONTROL PLAN SYSTEM
========================================

OVERVIEW
--------
This system provides a control-plan-driven monitoring platform for any process,
machine, facility, or installation that produces time-series data.

It combines:

- Structured engineering knowledge (Control Plan)
- Live telemetry data (InfluxDB / MQTT / HTTP)
- Process documentation (PDFs via RAG)
- AI-based reasoning (interpretation, not guessing)

The result is a real-time operator assistant that detects drift and explains
system behavior.


CORE CONCEPT
------------
The system does NOT guess what is normal.

Instead:

Control Plan -> Defines expected behavior
Data         -> Shows current behavior
System       -> Compares and explains


SUPPORTED PROCESS TYPES
-----------------------

1) STEADY-STATE PROCESSES
   Maintain conditions within limits.

   Examples:
   - refrigeration
   - HVAC
   - storage systems
   - pressure systems


2) TRANSFORMATION PROCESSES
   Convert raw input into a target output.

   Examples:
   - wastewater treatment (BOD reduction)
   - refining
   - chemical processing
   - food processing


KEY FEATURES
------------
- Time-series data monitoring
- Control plan-driven logic (not AI thresholds)
- Warning and alert detection
- Rate-of-change (trajectory) monitoring
- Final outcome validation
- Operator notes and context
- Temporary operator overrides
- Document-based reasoning (RAG)
- Extensible to any data source


DIRECTORY STRUCTURE
-------------------

/srv/PRL-ui/

- PRL_dashboard.py      Main monitoring application
- control_plan_builder.py     CSV builder tool
- control_plan.csv            Active control plan
- README.txt                  This file


CONTROL PLAN (control_plan.csv)
-------------------------------
The control plan is the core of the system.

It defines:
- what variables to monitor
- acceptable limits
- expected behavior
- reaction plans
- document references


VARIABLE ROLES
--------------

process_health
  Supports system (temperature, pressure, DO, etc.)

trajectory
  Tracks progress toward a target

outcome
  Final specification check


CONTROL LOGIC
-------------

STEADY-STATE VARIABLES

- Within warning band  = NORMAL
- Near limits          = WATCH
- Outside limits       = ALERT
- No data              = NO DATA


TRANSFORMATION VARIABLES

During Process:
- Evaluate rate of change toward target

After Completion:
- Evaluate final value against specification


OPERATOR INPUTS
---------------

Operators can provide:

1) NOTES
   Free-form context such as:
   - environmental changes
   - maintenance events
   - unusual conditions

2) OVERRIDES
   Temporary adjustments such as:
   - expected rate
   - interpretation context

Overrides:
- are visible
- are temporary
- do not change final compliance requirements


CONTROL PLAN BUILDER
--------------------

Run:

streamlit run control_plan_builder.py --server.port 8511

This tool allows:
- creation of control_plan.csv
- editing any variable
- adjusting number of rows
- downloading or saving to server


MONITORING APPLICATION
----------------------

Run:

streamlit run PRL_dashboard.py --server.port 8510

Displays:
- live values
- trends
- alerts and warnings
- variables requiring attention
- process explanation (AI reasoning)


DATA SOURCES
------------

Currently supported:
- InfluxDB

Planned:
- MQTT
- HTTP endpoints
- Node-RED integration


DESIGN PHILOSOPHY
-----------------

1) Engineering First
   Control Plan defines behavior.

2) AI as Interpreter
   AI explains, it does not define limits.

3) Flexible but Controlled
   Operators can adapt the system without breaking structure.

4) Scalable Across Industries
   Same system works for:
   - industrial processes
   - utilities
   - fleets
   - facilities
   - manufacturing


TYPICAL WORKFLOW
----------------

1) Define process or asset
2) Create control plan using builder
3) Connect data source
4) Load process documentation (PDF)
5) Monitor system
6) Refine control plan over time


KEY PRINCIPLE
-------------

The system evaluates whether the process is behaving as expected,
not just whether a value is within limits.


NOTES
-----

- Start with 5–10 variables
- Expand gradually
- Refine limits based on real operation
- Use operator feedback to improve control plan


FUTURE ENHANCEMENTS
-------------------

- Event-based monitoring (automatic triggers)
- Multi-user support (DynamoDB)
- Historical analysis
- Derived variables (calculations)
- Automated control plan refinement


SUMMARY
-------

This platform provides a generic, scalable intelligence layer for monitoring
any process that produces time-series data, using structured engineering
knowledge and contextual reasoning.

Control Plan + Data + Context + Reasoning = Intelligent Monitoring
