# Chapter 1: Executive Summary
## 1.1 Project Overview
RAAD is a cloud-based School Bus Tracking and Student Transportation Management Platform designed to improve student safety, operational efficiency, and communication between schools, parents, drivers, and transport administrators.

The platform combines real-time GPS tracking (JT808), live video monitoring (JT1078), intelligent trip management, fleet management, and parent notifications into a single integrated solution.

RAAD is designed as a scalable SaaS platform capable of serving schools, transport companies, organizations, and commercial fleet operators.
## 1.2 Purpose

The purpose of RAAD is to:

- Improve student transportation safety.
- Provide schools with complete visibility over daily transport operations.
- Enable parents to monitor their children's transportation during active trips.
- Help transport operators efficiently manage vehicles, drivers, routes, and trips.
- Reduce operational risks through real-time monitoring and intelligent notifications.

---

## 1.3 Target Customers

RAAD is designed for:

- Private Schools
- International Schools
- School Transportation Companies
- Universities and Educational Institutions
- Government and NGO Student Transport Programs
- Organizations operating employee transportation services.
- Commercial fleet owners who want to monitor and manage buses, trucks, vans, or company vehicles using GPS and MDVR technology.

---

## 1.4 Core Technologies

The platform integrates industry-standard technologies including:

- JT808 GPS Communication Protocol
- JT1078 Live Video Streaming Protocol
- GPS Tracking
- MDVR Devices
- Cloud Infrastructure
- Mobile Applications
- Web Management Dashboard

RAAD is built around open telematics standards (JT808/JT1078) rather than being tied to a single hardware manufacturer. This enables the platform to integrate with multiple compatible GPS and MDVR devices from different vendors, giving customers greater flexibility and protecting their investment.

---

## 1.5 Core Value Proposition

RAAD is not just a GPS tracking platform.

It is a complete transportation management ecosystem that combines:

- Real-time GPS Tracking
- Live Video Monitoring
- Transport Operations Management
- Fleet Management
- Parent Notifications
- Device Management
- School Transportation Management

within a single unified platform.

---

## 1.6 Project Philosophy

Student Safety First.
Real-Time Always.

Every product, engineering, and business decision must prioritize student safety, operational reliability, scalability, and real-time visibility.








# Chapter 2: Business Problem

## 2.1 Problem Statement

Many schools and transport operators still manage student transportation manually or with disconnected systems. Parents have limited visibility into their children's daily transportation, while school administrators struggle to monitor buses, drivers, and transport operations in real time.

The lack of an integrated transportation platform creates safety risks, operational inefficiencies, communication gaps, and poor decision-making.

---

## 2.2 Problems Faced by Schools

Schools face several operational challenges:

- No centralized platform to manage transportation.
- Limited visibility into daily bus operations.
- Difficulty monitoring drivers and vehicle activity.
- Lack of real-time GPS and live video monitoring.
- Manual transport fee management.
- Limited operational reporting and analytics.

---

## 2.3 Problems Faced by Parents

Parents often experience uncertainty because:

- They do not know when the bus has started its trip.
- They cannot accurately estimate bus arrival time.
- They receive little or no communication during transportation.
- They have no visibility during active trips.
- They cannot easily review previous transportation activities.

---

## 2.4 Problems Faced by Transport Operators

Transport operators face challenges including:

- Managing multiple buses and drivers.
- Monitoring vehicle health and device connectivity.
- Tracking route performance.
- Responding quickly to operational incidents.
- Managing multiple schools from one platform.

---

## 2.5 Market Opportunity

There is increasing demand for modern transportation management systems that combine:

- Real-time GPS Tracking
- Live Video Monitoring
- Parent Communication
- Fleet Management
- Intelligent Reporting
- Device Management

within one cloud platform.

RAAD is designed to address this growing demand using open telematics standards and a scalable cloud architecture.
# Chapter 3: Product Vision & Mission

## 3.1 Vision

To become Africa's leading intelligent transportation management platform by providing safe, reliable, and real-time school and fleet transportation solutions powered by open telematics standards and modern cloud technology.

---

## 3.2 Mission

Our mission is to improve transportation safety, operational efficiency, and communication by enabling schools, organizations, fleet operators, drivers, and parents to manage and monitor transportation through one intelligent platform.

---

## 3.3 Product Goals

RAAD aims to achieve the following goals:

- Improve student safety during transportation.
- Provide real-time visibility of transport operations.
- Reduce manual transport management processes.
- Improve communication between schools, drivers, and parents.
- Enable intelligent fleet management through GPS and live video.
- Support multiple organizations from a single cloud platform.
- Build a scalable Software-as-a-Service (SaaS) transportation platform.

---

## 3.4 Long-Term Vision

RAAD is designed to evolve beyond school transportation.

Future versions of the platform will support:

- Commercial Fleet Management
- Logistics and Delivery Fleets
- Employee Transportation
- Government Transportation Projects
- Public Transport Monitoring
- AI-powered Fleet Intelligence
- Predictive Maintenance
- Driver Behavior Analytics
- Smart City Transportation Integration

---

## 3.5 Product Principles

Every feature developed for RAAD must follow these principles:

- Student Safety First
- Real-Time by Default
- Cloud-Native Architecture
- Multi-Tenant by Design
- Device Vendor Independence
- Security by Default
- Scalability First
- Simplicity for End Users
- Reliability over Complexity

---

## 3.6 Success Metrics

The success of RAAD will be measured by:

- Improved transportation safety.
- Increased parent confidence.
- Reduced transport management workload.
- Higher operational efficiency.
- Reliable real-time GPS and video performance.
- Customer satisfaction and platform adoption.
- Growth in schools, organizations, and fleet customers.

# Chapter 4: Target Users & Stakeholders

## 4.1 Overview

RAAD serves multiple user groups, each with different responsibilities, permissions, and business objectives. Every user interacts with the platform according to their assigned role and organizational scope.

The platform is designed around Role-Based Access Control (RBAC), ensuring that every user only accesses the information required for their responsibilities.

---

## 4.2 RAAD Founder

The Founder has unrestricted access to the entire RAAD platform.

Responsibilities include:

- Platform administration
- Customer management
- Regional management
- Staff management
- Business analytics
- Subscription management
- Platform configuration
- System-wide monitoring
- Strategic decision making

The Founder is the only role with complete visibility across the entire platform.

---

## 4.3 RAAD Regional Manager

Regional Managers oversee customers within assigned geographic regions.

Responsibilities include:

- Managing organizations within assigned regions
- Customer onboarding
- Operational monitoring
- Customer support coordination
- Regional performance reporting

Regional Managers cannot access organizations outside their assigned region.

---

## 4.4 RAAD Support Staff

Support Staff provide operational and technical assistance.

Responsibilities include:

- Customer support
- Device activation
- Device troubleshooting
- Organization setup
- Platform configuration assistance

Support Staff can only access organizations assigned to them.

---

## 4.5 RAAD Finance Staff

Finance Staff manage commercial operations.

Responsibilities include:

- Subscription management
- Invoice management
- Payment verification
- Revenue reporting
- Customer billing

Finance Staff cannot access operational monitoring unless explicitly authorized.

---

## 4.6 Organization Administrator

Organization Administrators manage transportation operations within their own organization.

The organization may be:

- School
- School Transportation Company
- Commercial Fleet Company
- Government Organization
- NGO
- Employee Transportation Provider

Responsibilities include:

- Student management (where applicable)
- Parent management (where applicable)
- Driver management
- Vehicle management
- Device management
- Route management
- Stop management
- Trip management
- Transport payment management
- Reports and analytics
- Organization settings

Organization Administrators can only access data belonging to their own organization.

---

## 4.7 Driver

Drivers operate assigned vehicles during active trips.

Responsibilities include:

- Secure login
- View assigned vehicle
- View assigned route
- View assigned students
- View assigned stops
- Start morning trip
- End morning trip
- Start afternoon trip
- End afternoon trip

Drivers cannot access administrative features.

---

## 4.8 Parent / Guardian

Parents monitor their children's transportation.

Responsibilities include:

- Secure login
- View assigned child or children
- Receive transportation notifications
- View live GPS during active trips only
- View live video (if enabled by the organization)
- View trip history
- View transport payment status

Parents can only access information related to their own children.

---

## 4.9 Future User Roles

Future platform versions may introduce additional roles including:

- Fleet Supervisor
- Route Dispatcher
- Transport Coordinator
- Security Officer
- Maintenance Technician
- Operations Manager

These roles are outside the MVP scope but should be supported by the platform architecture.

---

## 4.10 Stakeholders

The primary stakeholders of the RAAD platform include:

- Students
- Parents and Guardians
- Drivers
- Organization Administrators
- RAAD Founder
- RAAD Regional Managers
- RAAD Support Staff
- RAAD Finance Staff
- Fleet Operators
- Organizations using the platform


# Chapter 5: Core Business Modules

## 5.1 Overview

RAAD is designed using a modular architecture.

Each module is responsible for a specific business domain while working together as one integrated transportation management platform.

This modular approach improves scalability, maintainability, security, and future expansion.

---

## 5.2 Transport Operations

The Transport Operations module manages all daily transportation activities.

Core responsibilities include:

- Vehicle Management
- Driver Management
- Student Management
- Parent Management
- Route Management
- Stop Management
- Trip Management
- Vehicle Assignment
- Transport Fee Management

This module serves as the operational core of the platform.

---

## 5.3 Tracking & Monitoring

This module provides real-time visibility into transportation operations.

Core responsibilities include:

- Live GPS Tracking
- Live Vehicle Monitoring
- Live Video Streaming (JT1078)
- Video Playback
- Vehicle Status Monitoring
- Device Status Monitoring
- Trip Monitoring

Organization administrators have continuous monitoring access.

Parents only receive live tracking during active trips.

---

## 5.4 Notification Center

The Notification Center delivers transportation-related notifications.

Core responsibilities include:

- Trip Started Notifications
- Bus Approaching Stop Notifications
- Arrival Notifications
- Trip Completed Notifications
- In-App Notifications
- Notification History

Notifications are event-driven and generated automatically by the platform.

---

## 5.5 Organization Management

This module manages organizations using the RAAD platform.

Core responsibilities include:

- Organization Management
- Organization Settings
- Organization Users
- Fleet Ownership
- Organization Configuration

Every organization operates independently within the multi-tenant platform.

---

## 5.6 Identity & Access

This module manages authentication and authorization.

Core responsibilities include:

- Authentication
- User Accounts
- Role Management
- Permission Management
- Session Management
- Access Control

The platform follows Role-Based Access Control (RBAC).

---

## 5.7 Device Management

This module manages GPS and MDVR hardware.

Core responsibilities include:

- Device Registration
- Device Assignment
- Device Configuration
- Device Monitoring
- Camera Management
- Remote Device Commands

The platform supports multiple hardware vendors using open telematics standards.

---

## 5.8 Reports & Analytics

This module provides operational and business insights.

Core responsibilities include:

- Student Transport Reports
- Transport Payment Reports
- Dashboard Analytics
- PDF Export
- Excel Export

Reports support operational management and business decision-making.

---

## 5.9 Platform Services

This module provides shared platform capabilities.

Core responsibilities include:

- System Settings
- Audit Logs
- API Integrations
- Platform Configuration

These services support the entire platform infrastructure.

---

## 5.10 Subscription & Billing

This module manages commercial operations between RAAD and customer organizations.

Core responsibilities include:

- Subscription Plans
- Billing Management
- Invoice Management
- Subscription Renewal
- Payment Tracking

The platform supports multiple billing models, including organization-paid and parent-paid subscriptions.

---

## 5.11 Module Design Principles

All business modules must follow these principles:

- Single Responsibility
- Loose Coupling
- High Cohesion
- API-First Communication
- Security by Default
- Scalability First
- Vendor Independence
- Real-Time Architecture
# Chapter 6: Business Entities

## 6.1 Overview

Business Entities represent the core business objects of the RAAD platform.

Every feature, database table, API endpoint, and business process is built around these entities.

Each entity has a clear responsibility and defined relationships with other entities.

---

## 6.2 Organization

Represents a customer using the RAAD platform.

Examples include:

- Schools
- School Transportation Companies
- Commercial Fleet Companies
- Government Organizations
- NGOs
- Employee Transportation Providers

Responsibilities:

- Owns vehicles
- Owns drivers
- Owns students (where applicable)
- Owns routes
- Owns trips
- Owns devices
- Owns subscription

---

## 6.3 Vehicle

Represents a physical bus or commercial vehicle.

Responsibilities:

- Assigned to one organization
- Connected to one GPS/MDVR device
- Assigned to trips
- Assigned to drivers
- Assigned to routes

The vehicle is an operational asset, not a tracking device.

---

## 6.4 Device

Represents GPS and MDVR hardware.

Responsibilities:

- GPS communication (JT808)
- Live video streaming (JT1078)
- Device monitoring
- Camera management
- Remote communication

One device is assigned to one vehicle.

---

## 6.5 Driver

Represents the vehicle operator.

Responsibilities:

- Login
- Operate assigned vehicle
- Start trips
- End trips
- View assigned route
- View assigned passengers

Drivers perform transportation operations only.

---

## 6.6 Student

Represents a transported student.

Responsibilities:

- Assigned to an organization
- Linked to parent(s)
- Assigned to a vehicle
- Assigned to a route
- Assigned pickup stop
- Assigned drop-off stop
- Transport payment records

Student transportation is the primary business domain of RAAD.

---

## 6.7 Parent / Guardian

Represents the responsible person for one or more students.

Responsibilities:

- Login
- Receive notifications
- Monitor active trips
- View transport payments
- Access assigned student information

Parents only access their own children.

---

## 6.8 Route

Represents the transportation path followed by a vehicle.

Responsibilities:

- Defines pickup sequence
- Defines drop-off sequence
- Contains multiple stops
- Used by scheduled trips

Routes organize daily transportation operations.

---

## 6.9 Stop

Represents a pickup or drop-off location.

Responsibilities:

- GPS location
- Pickup point
- Drop-off point
- Stop sequence
- Estimated arrival calculations

Multiple stops form one route.

---

## 6.10 Trip

Represents one transportation journey.

Examples:

- Morning Trip
- Afternoon Trip

Responsibilities:

- Trip scheduling
- Trip status
- Driver assignment
- Vehicle assignment
- Route execution
- Live tracking activation
- Trip history

Trips are the operational center of daily transportation.

---

## 6.11 Subscription

Represents the commercial agreement between RAAD and an organization.

Responsibilities:

- Subscription plan
- Billing model
- Active status
- Renewal
- Payment records

Subscriptions control platform access.

---

## 6.12 Entity Relationships

The core business relationships are:

Organization
├── Vehicles
├── Devices
├── Drivers
├── Students
├── Routes
├── Trips
└── Subscription

Vehicle
├── Device
├── Driver
├── Route
└── Trips

Student
├── Parent
├── Route
├── Pickup Stop
└── Drop-off Stop

Route
└── Stops

Trip
├── Vehicle
├── Driver
├── Route
└── Students




# Chapter 7: Business Rules

## 7.1 Overview

Business Rules define the mandatory operational logic of the RAAD platform.

These rules apply regardless of the technology stack, programming language, or deployment environment and must always be enforced throughout the system.

---

## 7.2 Organization Rules

- Every organization operates independently within the platform.
- Organizations cannot access data belonging to other organizations.
- Every organization owns its own vehicles, drivers, students, routes, trips, and devices.
- Every organization must have an active subscription to access platform services.

---

## 7.3 User Access Rules

- Every user must authenticate before accessing the platform.
- Every user is assigned a role.
- Every role has predefined permissions.
- Every user may only access data within their authorized scope.
- Platform access is controlled using Role-Based Access Control (RBAC).

---

## 7.4 Vehicle Rules

- Every vehicle belongs to one organization.
- Every vehicle can only have one active GPS/MDVR device.
- A vehicle cannot perform multiple active trips simultaneously.
- A vehicle may complete multiple trips each day.

---

## 7.5 Device Rules

- Every GPS/MDVR device is assigned to one vehicle.
- One device cannot be connected to multiple vehicles simultaneously.
- Device connectivity must be monitored continuously.
- Device communication follows JT808 and JT1078 standards.

---

## 7.6 Driver Rules

- Drivers must authenticate before operating a vehicle.
- Drivers may only operate assigned vehicles.
- Drivers manually start and end every trip.
- Drivers cannot access administrative features.

---

## 7.7 Student Rules

- Every student belongs to one organization.
- Every student must have at least one registered parent or guardian.
- Every student is assigned to one transportation route.
- Every student has one pickup stop and one drop-off stop.
- Every student has a transport payment record.

---

## 7.8 Parent Rules

- Parents can only access information related to their own children.
- Parents receive automatic transportation notifications.
- Parents can only view live GPS during active trips.
- Parents can only view live video if enabled by the organization.
- Outside active trips, parents can only view trip history and transport information.

---

## 7.9 Trip Rules

- Every trip belongs to one organization.
- Every trip has one assigned vehicle.
- Every trip has one assigned driver.
- Every trip follows one predefined route.
- Every trip has a start time and an end time.
- Morning and afternoon trips are managed independently.
- Parents receive notifications automatically when a trip starts and ends.

---

## 7.10 Tracking Rules

- Organization administrators have continuous (24/7) access to vehicle monitoring.
- Parents only receive live tracking during active trips.
- Live tracking automatically starts when the driver starts the trip.
- Live tracking automatically stops for parents when the trip ends.
- GPS and live video are synchronized with trip status.

---

## 7.11 Notification Rules

The platform automatically generates notifications for transportation events including:

- Morning Trip Started
- Vehicle Approaching Pickup Stop
- Student Pickup
- Arrival at Organization
- Afternoon Trip Started
- Vehicle Approaching Drop-off Stop
- Student Drop-off
- Trip Completed

Notifications are delivered only to authorized users.

---

## 7.12 Payment & Subscription Rules

- Organizations may choose their preferred billing model.
- Billing models include:
  - Organization Pays
  - Parent Pays
- Subscription status determines access to platform services.
- Transport fees are managed separately from platform subscriptions.

---

## 7.13 Security Rules

- Every important action must be recorded in the audit log.
- Users may only access authorized resources.
- All communication must be encrypted.
- Platform data must remain isolated between organizations.
- Privacy and student safety take precedence over convenience.

---

## 7.14 Core Business Principle

Student Safety First.

Every operational, technical, and business decision made within the RAAD platform must prioritize student safety, operational reliability, data security, and real-time visibility.


# Chapter 8: User Journeys & Business Workflows

## 8.1 Overview

This chapter describes how different users interact with the RAAD platform during daily operations.

These workflows define the expected business behavior and serve as the foundation for system architecture, API design, database relationships, and user interface design.

---

## 8.2 RAAD Founder Workflow

1. Login to the platform.
2. View platform dashboard.
3. Monitor all organizations.
4. Manage subscriptions.
5. Monitor platform health.
6. Manage regional staff.
7. Review business analytics.

---

## 8.3 Organization Administrator Workflow

1. Login.
2. Access organization dashboard.
3. Register or manage vehicles.
4. Register GPS/MDVR devices.
5. Register drivers.
6. Register students.
7. Register parents.
8. Create transportation routes.
9. Create pickup and drop-off stops.
10. Assign students to vehicles and routes.
11. Monitor active trips.
12. Review reports and transport payments.

---

## 8.4 Driver Workflow

1. Login.
2. View assigned vehicle.
3. View assigned route.
4. View assigned students.
5. Start Morning Trip.
6. Complete pickup route.
7. Arrive at organization.
8. End Morning Trip.
9. Start Afternoon Trip.
10. Complete drop-off route.
11. End Afternoon Trip.
12. Logout.

---

## 8.5 Parent Workflow

1. Login.
2. View assigned child or children.
3. Wait for trip notification.
4. Receive "Trip Started" notification.
5. View live GPS during the active trip.
6. View live video (if enabled).
7. Receive arrival notification.
8. Review trip history.
9. View transport payment status.

Parents cannot monitor vehicles outside active trips.

---

## 8.6 Daily Transportation Workflow

Organization Administrator

↓

Vehicle + Driver + Route + Students

↓

Driver Starts Trip

↓

GPS Tracking Activated

↓

Parent Notifications Sent

↓

Parents Receive Live Tracking

↓

Students Picked Up

↓

Vehicle Arrives at Organization

↓

Morning Trip Ends

↓

Afternoon Trip Starts

↓

Students Dropped Off

↓

Trip Completed

↓

Trip History Saved

---

## 8.7 Device Workflow

Device Installed

↓

Device Activated

↓

Assigned to Vehicle

↓

JT808 Connected

↓

JT1078 Connected

↓

GPS Data Received

↓

Video Stream Received

↓

Continuous Monitoring

---

## 8.8 Subscription Workflow

Organization Registration

↓

Subscription Plan Selected

↓

Payment Completed

↓

Subscription Activated

↓

Organization Enabled

↓

Renewal

---

## 8.9 Exception Workflows

The platform must correctly handle exceptional situations including:

- Device Offline
- Vehicle Offline
- GPS Signal Lost
- Network Failure
- Driver Login Failure
- Subscription Expired
- Trip Not Started
- Trip Interrupted

The system must recover gracefully while protecting operational data and student safety.


# Chapter 9: Subscription & Billing

## 9.1 Overview

The RAAD platform operates as a Software-as-a-Service (SaaS) solution.

Every organization must have an active subscription to access platform services.

The billing architecture is designed to support multiple commercial models without affecting the core platform architecture.

---

## 9.2 Billing Models

RAAD supports multiple billing models.

### Organization Pays

The organization pays the platform subscription.

Parents receive platform access without paying individual subscription fees.

---

### Parent Pays

Parents subscribe individually to access premium transportation services.

The organization manages transportation while parents pay for application access.

---

## 9.3 Subscription Plans

Subscription plans may vary based on:

- Number of Vehicles
- Platform Features
- Storage Capacity
- Live Video Access
- Organization Size

The pricing structure is configurable by RAAD administrators.

---

## 9.4 Subscription Lifecycle

Subscription Status includes:

- Trial
- Active
- Suspended
- Expired
- Cancelled

Platform permissions depend on the current subscription status.

---

## 9.5 Billing Cycle

The platform supports:

- Monthly Billing
- Quarterly Billing
- Annual Billing

Additional billing cycles may be introduced in future releases.

---

## 9.6 Payments

The platform records:

- Invoice Number
- Payment Date
- Payment Status
- Amount
- Billing Period
- Payment Method

---

## 9.7 Platform Access

Organizations with inactive subscriptions may experience restricted platform functionality according to platform policy.

Subscription validation is performed before granting access to premium platform services.

---

## 9.8 Future Expansion

The billing architecture should support future integrations including:

- Online Payment Gateways
- Mobile Money
- Bank Transfers
- Automatic Renewals
- Promotional Discounts
- Coupon Codes
# Chapter 10: Functional & Non-Functional Requirements

## 10.1 Functional Requirements

The RAAD platform shall provide the following core capabilities:

### Transportation Management

- Vehicle Management
- Driver Management
- Student Management
- Parent Management
- Route Management
- Stop Management
- Trip Management

---

### Real-Time Monitoring

- Live GPS Tracking
- Live Video Streaming
- Video Playback
- Device Monitoring
- Vehicle Monitoring

---

### Notifications

- Trip Started Notification
- Vehicle Approaching Stop
- Arrival Notification
- Trip Completed Notification
- In-App Notifications

---

### Reports

- Student Reports
- Transport Payment Reports
- Dashboard Analytics
- PDF Export
- Excel Export

---

### Subscription Management

- Subscription Plans
- Subscription Renewal
- Subscription Status
- Billing History

---

### Authentication

- Secure Login
- Role-Based Access Control
- Session Management

---

## 10.2 Non-Functional Requirements

The platform must satisfy the following quality attributes.

### Performance

- Fast response times
- Real-time GPS updates
- Low-latency live video

---

### Scalability

The platform must support:

- Multiple organizations
- Thousands of vehicles
- Thousands of concurrent users

---

### Reliability

- High platform availability
- Automatic error recovery
- Continuous device monitoring

---

### Security

- Secure authentication
- Data encryption
- Organization data isolation
- Audit logging

---

### Maintainability

- Modular Architecture
- Clean API Design
- Clear documentation

---

### Compatibility

The platform must support:

- Web Dashboard
- Android
- iOS
- Multiple JT808/JT1078 compatible devices

---

### Extensibility

The platform should allow future expansion without major architectural changes.

Examples include:

- AI Features
- Fleet Management
- Logistics
- Public Transportation
- Additional Payment Providers 
# Chapter 11: Technology Stack

## 11.1 Technology Overview

The RAAD platform is designed as a modern cloud-native SaaS solution built using scalable, secure, and open technologies.

The technology stack is selected to support high performance, maintainability, real-time communication, multi-tenancy, and long-term scalability while minimizing infrastructure costs.

---

## 11.2 System Architecture

Architecture Style

- Modular Monolith (MVP)
- API-First Architecture
- Multi-Tenant SaaS
- Event-Driven Notifications
- Vendor-Independent Device Integration

The architecture must allow future migration to Microservices without requiring major redesign.

---

## 11.3 Backend

Technology

- Python
- FastAPI

Responsibilities

- REST APIs
- Authentication & Authorization
- Business Logic
- Organization Management
- Vehicle Management
- Driver Management
- Student Management
- Parent Management
- Route Management
- Trip Management
- Device Management
- Notification Engine
- Subscription Management
- Report Generation

---

## 11.4 Web Dashboard

Technology

- React
- TypeScript

Responsibilities

- RAAD Founder Dashboard
- Organization Dashboard
- Live Monitoring
- Reports & Analytics
- Device Management
- User Management
- Subscription Management
- Administration

---

## 11.5 Mobile Application

Technology

- Flutter

Supported Platforms

- Android
- iOS

Application Roles

- Parent
- Driver

The mobile application uses Role-Based Access Control (RBAC), allowing different user interfaces while maintaining a single shared codebase.

---

## 11.6 Database

Primary Database

- MySQL

Responsibilities

- Organization Data
- User Data
- Student Data
- Parent Data
- Vehicle Data
- Device Data
- Route Data
- Stop Data
- Trip Data
- Subscription Data
- Payment Data

The database must support multi-tenancy and future scalability.

---

## 11.7 Real-Time Communication

Protocols

- JT808
- JT1078

Responsibilities

- GPS Communication
- Live Vehicle Monitoring
- Live Video Streaming
- Device Communication
- Remote Device Commands

The platform must support multiple JT808/JT1078 compatible hardware manufacturers.

---

## 11.8 Maps & Location Services

The platform shall support:

- Live Maps
- Vehicle Tracking
- Route Visualization
- Stop Management
- ETA Calculation
- Geofencing

The map provider must remain configurable and independent from the platform architecture.

---

## 11.9 Media Storage Strategy

RAAD is a real-time monitoring platform, not a cloud video storage platform.

The MDVR remains the primary system of record for recorded video, while the RAAD platform functions as a real-time monitoring and transportation management platform.

### Video Storage

- Continuous video recording remains stored locally on the MDVR storage device (SSD, SD Card, or HDD).
- The RAAD platform does not continuously upload or archive recorded video to cloud storage.
- This architecture minimizes cloud storage costs.
- This architecture reduces server infrastructure requirements.

### Live Video

- The platform requests live video directly from the MDVR only when live monitoring is initiated.
- Organization Administrators can start live video at any time.
- Parents may only view live video during active trips if enabled by the organization.

### Video Playback

- Organization Administrators can remotely request playback from the MDVR.
- Playback streams directly from the MDVR.
- Recorded video remains stored only on the MDVR.
- Playback availability depends on the recordings retained by the MDVR storage device.

The platform never duplicates continuous recorded video into cloud storage by default.

---

## 11.10 Security

Security Standards

- HTTPS
- JWT Authentication
- Password Hashing
- Role-Based Access Control (RBAC)
- Audit Logging

Platform Security Principles

- Secure by Default
- Least Privilege Access
- Organization Data Isolation
- Encrypted Communication

---

## 11.11 Payment Integration

Primary Payment Method

- EVC Plus Mobile Money

Future Payment Providers

- Zaad
- Sahal
- eDahab
- Bank APIs
- International Payment Providers

The payment architecture must remain provider-independent.

Subscription renewals should support in-app mobile money payments without requiring users to leave the application.

---

## 11.12 Development Principles

Development Standards

- Clean Architecture
- SOLID Principles
- Domain-Driven Design (DDD)
- API-First Development
- Modular Architecture
- Git Version Control
- Continuous Documentation
- Testable Components
- Clean Code Practices

---

## 11.13 AI Development Workflow

AI-assisted development is a core part of the RAAD engineering process.

Claude Code is the primary AI development environment and will be used throughout the software lifecycle.

AI Responsibilities

- Architecture Implementation
- Backend Development
- Frontend Development
- Mobile Development
- Documentation
- Refactoring
- Testing
- Code Review
- Debugging

Project knowledge will be maintained through:

- CLAUDE.md
- .claude/rules
- .claude/skills
- .claude/agents
- Project Documentation

All AI-generated code must follow the project's architecture, coding standards, and business rules.

"Using Chapters 1–11, design a production-grade Enterprise Architecture for the RAAD platform. Do not change the business requirements unless necessary. Validate assumptions, identify risks, recommend improvements, and produce a complete architecture including system architecture, module architecture, deployment architecture, database strategy, API strategy, and scalability roadmap."
