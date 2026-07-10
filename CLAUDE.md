# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What RAAD Is

RAAD is a cloud-based **School Bus Tracking and Student Transportation Management Platform**.

It exists to solve one problem: giving schools, transport operators, drivers, and parents real-time
visibility and control over school bus operations. Every feature decision should be evaluated against
that single purpose.

## Product Scope

### In scope (this is what RAAD does)
- Real-time GPS tracking of school buses
- Live video streaming from onboard bus cameras (JT1078)
- GPS/vehicle terminal communication (JT808)
- Parent notifications (e.g., bus location, arrival/departure, pickup/drop-off events)
- Fleet management (buses/vehicles as assets)
- Driver management
- Route management
- Student transportation (linking students to routes/buses, boarding/alighting tracking)

### Explicitly out of scope
RAAD is **not** a school ERP. Do not add, extend toward, or casually suggest features from these domains,
even if a request seems adjacent:
- Classroom/school attendance tracking
- General school ERP functionality
- Payroll
- Exams / gradebook / academic records
- Learning Management System (LMS) features

If a request would pull RAAD toward any of the above, say so explicitly and ask for confirmation
rather than implementing it. Scope creep into general school-management territory is the main risk
to design against in this codebase.

## Core Technical Domains

RAAD's real-time capabilities are built on two vehicle telematics protocols — these are the terms
you'll see across GPS ingestion, video, and device-communication code:

- **JT808** (JT/T 808) — the protocol used for communication between the bus's onboard terminal and
  the platform: GPS positioning data, terminal registration/auth, status, alarms/events, and commands
  sent to the device.
- **JT1078** (JT/T 1078) — the protocol used for transmitting live audio/video from onboard cameras
  to the platform over the public network.

Treat these two protocols as first-class architectural concerns: most "real-time tracking" and
"live video" features in this codebase are ultimately about correctly implementing, parsing, or
relaying JT808/JT1078 traffic between bus terminals and the platform.

## Domain Vocabulary

- **Fleet** — the set of buses/vehicles operated by a school or transport operator.
- **Route** — a defined path a bus follows, with an ordered set of stops.
- **Driver** — the operator assigned to a bus/route.
- **Student transportation record** — the association between a student and the route/bus they ride.
- **Parent notification** — an alert sent to a parent/guardian about their child's bus (e.g., approaching stop, boarded, dropped off).

## Repository Status

This repository is currently greenfield: no application code, tech stack, build tooling, or tests
exist yet (only this file). Do not assume any particular language, framework, database, or service
architecture — none has been chosen yet. When implementation begins, this file must be updated with:

- The actual tech stack and why it was chosen
- Build/lint/test commands (including how to run a single test)
- Real architecture: service boundaries, how JT808/JT1078 ingestion is structured, data flow from
  bus terminal → platform → parent app
- Any conventions established in code review or CLAUDE.md/rules files as the project grows

Until those decisions are made, treat this file's Product Scope and Core Technical Domains sections
as the durable source of truth, and treat everything else as not-yet-decided rather than inferable.
