# Breathe ESG Ingestion & Normalization Prototype

Welcome to the Breathe ESG tech intern assessment prototype. This application is a fully integrated **Django REST Framework** backend and **React (Vite + Vanilla CSS)** frontend built to ingest, validate, calendarize, and calculate Scope 1, 2, and 3 emissions from three enterprise source systems: **SAP Procurement & Fuels**, **Utility Portals**, and **Corporate Travel (Concur)**.

---

## 🚀 Quick Start Guide

### 1. Backend Setup & Seeding (Django)

In your terminal, navigate to the `backend/` directory and activate the virtual environment:

```powershell
# From the project root folder:
# 1. Activate Virtual Environment
.\venv\Scripts\activate

# 2. Navigate to backend
cd backend

# 3. Create and Apply Migrations
python manage.py makemigrations
python manage.py migrate

# 4. Seed Corporate Masters & Emission Factors
python manage.py seed_data

# 5. Run the Server
python manage.py runserver
```
*The API is now live at `http://localhost:8000/api/`.*

### 2. Frontend Setup & Build (React)

Open a second terminal window, navigate to the `frontend/` directory, and run the developer server:

```bash
# From the project root folder:
cd frontend

# Install Dependencies (if not already done)
npm install

# Start Vite Developer Server
npm run dev
```
*The UI is now live at `http://localhost:5173/`.*

---

## 🔬 Running Automated Unit Tests

A comprehensive suite of automated tests verifies our distance calculations, pro-rata splits, and unit anomalies. Run them from the `backend/` directory:

```bash
python manage.py test
```

---

## ⚡ Live Demo Walkthrough

Once both servers are running:
1.  Open `http://localhost:5173/` in your browser.
2.  Click the glowing **"🚀 Seed Live Demo Data"** button in the header. This triggers the simulation engine to generate highly realistic, complex, and messy mock datasets from **SAP (German CSV)**, **Utility Portals (Consumption Splits)**, and **Concur Travel (Scope 3 JSON itineraries)**.
3.  **Explore the Review Dashboard Grid**:
    *   Toggle between SAP, Utility, and Travel sources.
    *   Filter by Compliance Status (e.g. examine `FLAGGED` anomalies).
4.  **Audit & Override a Row**:
    *   Click **"Drill Down"** on any row to open the compliance drawer.
    *   Inspect the **Source of Truth Raw JSON** payload.
    *   Examine the step-by-step **Emissions Calculation Science** trail.
    *   Click **"Manually Override Quantities"**, input new values, provide a reason, and watch the carbon footprint and graph update instantly.
    *   Observe the immutable entry appended to the **Permanent Audit Timeline**.
5.  **Compliance Lock**:
    *   Click **"Approve & Lock"**. The row's input fields freeze forever, securing it against any future changes, ready for external auditing.

---

## 📁 Repository Deliverables

The evaluation criteria is supported by the following structured documentation in the root directory:
*   📜 [MODEL.md](file:///c:/Users/MANU/Desktop/productuve/assignments/breatheesg/MODEL.md): Deep-dive into database normalization, multi-tenancy, raw JSON preserves, and compliance trails.
*   📜 [DECISIONS.md](file:///c:/Users/MANU/Desktop/productuve/assignments/breatheesg/DECISIONS.md): Outline of ambiguities resolved, source data bounds, and strategic questions for the PM.
*   📜 [TRADEOFFS.md](file:///c:/Users/MANU/Desktop/productuve/assignments/breatheesg/TRADEOFFS.md): Detailed analysis of the three features we deliberately did not build and why.
*   📜 [SOURCES.md](file:///c:/Users/MANU/Desktop/productuve/assignments/breatheesg/SOURCES.md): Technical research on SAP ME2N csv exports, utility Green Button schemas, and Concur Itinerary APIs.
