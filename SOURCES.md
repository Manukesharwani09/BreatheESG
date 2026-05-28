# Data Sources Research & Rationale (`SOURCES.md`)

This document presents the real-world research behind our three data ingestion sources, justifies our simulated sample dataset, and outlines what would break when deploying this in a production enterprise environment.

---

## 1. SAP Fuel & Procurement Ingestion

### What We Researched & Learned
*   **Source Format**: We researched standard SAP transactions for procurement and inventory tracking, specifically `ME2N` (Purchase Orders by Document Number) and `ME80FN` (General Purchase Order Reporting).
*   **The Reality**: In enterprise SAP configurations, column headers are often stored in German technical names (the direct ABAP database field names) rather than friendly English labels:
    *   `WERKS` = Plant (Werk)
    *   `MENGE` = Purchase Order Quantity
    *   `MEINS` = Base Unit of Measure (Bestelleinheit)
    *   `NETWR` = Net Value of Order (Nettowert)
    *   `BUDAT` = Posting Date of Material Document (Buchungsdatum)
*   **Messy Units**: SAP units are highly inconsistent because purchasing departments book items using whatever unit matches the contract. While fuel should be in Liters (`L`), it is often entered as:
    *   `M3` (Cubic meters)
    *   `FL` (Flasche / Bottle)
    *   `KT` (Karton / Box)
    *   `TO` (Tons)
*   **Plant Codes**: SAP only displays code identifiers (e.g. `Werk 1000` or `PL002`), which require a custom relational join against an corporate organization Master Data table to identify the physical address (needed to determine country-specific carbon grid factors).

### Rationale of Our Sample Data
Our SAP simulation batch (`sap_extract_q2_2026.csv`) mimics this enterprise messiness:
1.  **Clean Rows**: Standard rows for diesel and natural gas written in German headers (`Menge`, `Einheit`, `Material`), which our parser maps and translates automatically.
2.  **Unknown Plant Anomaly**: A row with plant `PL999` which does not exist in master lookups, triggering a red validation flag.
3.  **Invalid Unit Anomaly**: A fuel invoice booked in `FL` (Flaschen/bottles). Since there is no standard conversion factor between a "bottle" and a liter of diesel, the engine raises a high-priority flag.
4.  **Negative Quantities**: A return or adjustment row with a negative quantity (`-150`), which the parser flags as an anomaly.

### What Breaks in Production
*   **Custom Field Configurations**: Enterprise clients often add custom fields (e.g., `ZZ_CARBON_TAG`) or rename standard tables, which breaks rigid CSV header parsers.
*   **Encodings & Delimiters**: SAP CSVs are frequently exported using different local formats (e.g., semicolon delimiters `;` in Europe, comma `,` in the US) or encoded in legacy Windows UTF-16 formats, causing string reading failures.

---

## 2. Utility Portal Electricity Data

### What We Researched & Learned
*   **Source Format**: We researched utility portal CSV exports and the **Green Button Alliance XML/CSV schema**, which is the national standard for energy data in North America.
*   **The Reality**: In Green Button and generic utility CSVs:
    *   Meter readings represent the cumulative dial numbers on the physical hardware (`PreviousReadValue` vs `CurrentReadValue`), and usage is derived mathematically from their difference.
    *   **Billing Cycles vs Calendar Months**: Invoices are almost never aligned to standard calendar months. A typical billing cycle runs from April 15 to May 14. For quarterly GHG compliance reporting, these must be proportionally pro-rated.
    *   **Tariff Complexity**: Rates schedules (Time-of-Use `TOU` vs Flat vs Peak Demand) dictate the pricing structure and can indicate different power grid grid-tied factors.

### Rationale of Our Sample Data
Our Utility simulation (`utility_direct_scrape_may26.csv`) contains:
1.  **Calendarization Trigger**: An invoice spanning April 15 to May 14. Our system demonstrates pro-rata math by splitting this row into two separate monthly records, mid-month.
2.  **Reading Gap Anomaly**: A row where `CurrentReadValue - PreviousReadValue != Usage_kWh`, indicating a reading mismatch or dial-rollover multiplier gap, flagged immediately for review.
3.  **Bill Overlaps**: If a duplicate bill is uploaded for the same period, the parser flags it as an `OVERLAPPING_BILL`.

### What Breaks in Production
*   **Net Metering / Solar**: Facilities with solar arrays feed power *back* into the grid, resulting in net negative consumption on certain dials which can break simple validation ranges if not accounted for.
*   **Meter Replacements**: When a physical meter breaks and is replaced, the cumulative dial resets to `0`. A naive reading checker would flag a massive negative gap because `CurrentRead (e.g., 50) < PreviousRead (e.g., 9000)`, when in reality it is a legitimate hardware reset.

---

## 3. Corporate Travel Platform Data (Scope 3)

### What We Researched & Learned
*   **Source Format**: We researched the **SAP Concur Itinerary v4 API specification**, which is the gold standard for global business travel reporting.
*   **The Reality**: Concur exports data as high-level trip containers holding an array of travel segments:
    *   `Air`: Standardizes airport locations using standard **3-letter IATA codes** (e.g., `JFK`, `LHR`). Distances are not provided; distance must be calculated between these airport coordinates.
    *   `Hotel`: Bookings are tracked in room-nights. Carbon emissions vary dramatically by the **electricity grid of the destination country** (e.g. 1 night in a coal-powered Indian hotel emits ~42kg CO2e, while a night in nuclear-powered France emits only ~6kg CO2e).
    *   `Car`: Rentals provide car category designations (SUV vs Compact) and distances in mixed units (miles vs kilometers).

### Rationale of Our Sample Data
Our Travel simulation (`concur_itineraries_q2.json`) features:
1.  **Jane Doe's Premium Long-Haul Trip**: A business flight from JFK to London Heathrow, a hotel in the UK, and an SUV rental. It demonstrates the business-class emissions multiplier and high SUV factors.
2.  **Arjun Mehta's High-Carbon Destination Trip**: A flight from Frankfurt to Bangalore, and a stay in India. This highlights the high country-specific hotel factor due to India's coal-heavy grid.
3.  **Sophie Laurent's Eco-Friendly Trip**: A short flight from Paris to Frankfurt and a hotel stay in France, showcasing the low-carbon impact of a nuclear-powered electricity grid.

### What Breaks in Production
*   **Multi-Leg Flights**: Flights with multiple layovers (e.g., JFK -> CDG -> BLR) would be calculated as a single direct great-circle flight (JFK -> BLR) in naive parsers, under-reporting distance and associated carbon emissions.
*   **Hotel Booking Adjustments**: Cancelled hotel bookings or mid-trip changes are represented in Concur as adjustments, which must be deduplicated to avoid double-counting.
