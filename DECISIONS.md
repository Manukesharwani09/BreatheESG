# Decisions Log (`DECISIONS.md`)

This document records the engineering decisions, real-world data assumptions, and trade-offs made during the development of the Breathe ESG prototype, including the precise subsets of data handled and the questions we would pose to the Product Manager.

---

## 1. Ambiguities Resolved & Selected Approaches

### SAP Procurement & Fuel Data
*   **The Ambiguity**: SAP exports can be delivered in dozens of forms (BAPIs, OData JSON, IDoc files, or arbitrary flat reports). The columns are notoriously messy, frequently using raw German technical abbreviations (e.g. `WERKS`, `MENGE`, `MEINS`).
*   **Our Decision**: We decided to handle a **flat CSV report** representing an invoice/purchase-order extract (similar to an `ME2N` or `ME80FN` transaction extract). This matches how facilities managers typically pull data without engineering assistance.
*   **Columns Handled**: We built the parser to support standard German/English headers:
    *   `Beleg` or `EBELN` (Document ID)
    *   `Buchungsdatum` or `BUDAT` (Posting Date - parsed in both standard SQL format and German `DD.MM.YYYY`)
    *   `Werk` or `WERKS` (Plant lookup identifier)
    *   `Material` or `MATNR` (Material description - diesel, heavy oil, natural gas)
    *   `Menge` or `MENGE` (Activity quantity)
    *   `Einheit` or `MEINS` (Messy unit representation - L, m³, liters, and invalid entries like `FL` for Flasche / bottle)
*   **What We Ignored**: We ignored purchasing groups, material numbers (relying instead on keyword matching in description strings), vendor addresses, VAT rates, and general ledger accounts.

### Utility Portal Billing Data
*   **The Ambiguity**: Facilities teams pull utility data from portals as CSVs, which contain arbitrary meter readings, demand thresholds, reactive power variables, and billing cycles that overlap calendar months (e.g., April 15 to May 14).
*   **Our Decision**: We opted to parse a **Portal CSV Export** representing invoice and billing cycle parameters.
*   **Calendar Pro-Rata Normalization**: To resolve the monthly reporting problem, our parser executes a **pro-rata splitting algorithm**. If a bill spans multiple calendar months, the usage is divided by the total billing days to obtain a daily rate, and then split proportionally into monthly `NormalizedRecord` entries, mid-month. This is the industry-standard greenhouse gas (GHG) reporting practice, but is rarely implemented in basic CRUD software.
*   **Mathematical Cross-Check**: The parser verifies whether `CurrentReadValue - PreviousReadValue == Usage_kWh`. If a gap is detected (indicating a reading error, multiplier slip, or manual credit adjustment), the record is automatically `FLAGGED` as a `METER_READ_GAP` anomaly for analyst investigation.
*   **What We Ignored**: We ignored demand charges (kW), power factor adjustments, reactive power (kVAR), taxes, and fixed service fees. We focused strictly on consumption (kWh) and associated tariff rates.

### Corporate Travel Platform Data (Scope 3)
*   **The Ambiguity**: Travel platforms like Concur or Navan expose itinerary data. However, travel bookings are highly layered (a single trip contains flights, hotel bookings, car rentals) and do not natively give carbon metrics. Distances are rarely provided directly; only origin/destination IATA airport codes are exported.
*   **Our Decision**: We chose to parse a **Structured Trip Itinerary JSON Payload** mimicking the actual **SAP Concur Itinerary API v4** structure.
*   **Geospatial Distance Engine**: For passenger flights (`Air` segments), we implemented a **Haversine Great Circle distance calculation**. The system retrieves the exact latitude and longitude coordinates of standard IATA codes (e.g., JFK, LHR, BLR) from our `AirportLookup` table and calculates the flight distance dynamically.
*   **GHG Seating Class Modifiers**: Following DEFRA carbon standards, flight factors are dynamically adjusted by seating class. Business/First class tickets carry a **2.5x to 3x higher carbon multiplier** than Economy tickets, due to the physical cabin space occupied by the passenger.
*   **Hotel & Car Normalization**:
    *   Hotels are normalized into `room-nights` (Nights * Rooms) and multiplied by **country-specific factors** (staying in a hotel in coal-heavy India has a significantly higher carbon footprint than in nuclear-heavy France).
    *   Car rentals are normalized to standard kilometers (converting miles to km) and multiplied by vehicle category factors (SUV vs Sedan vs Electric).
*   **What We Ignored**: We ignored train segments (rail), meals/dining bookings, booking cancellations, baggage fees, layovers, and multi-segment flight details (assuming direct great-circle routes).

---

## 2. What We Would Ask the PM

If we were pair-programming with the Product Manager, here are the three critical questions we would ask:

1.  **Overlapping Billing vs Meter Swaps**: *"When a utility bill overlaps an existing record, we flag it as an anomaly (`OVERLAPPING_BILL`). However, sometimes physical meters are broken and swapped mid-month. How should the system distinguish between a data duplication error and a legitimate meter swap?"*
2.  **Scope 2 Market-Based vs Location-Based Factors**: *"We currently calculate Scope 2 using location-based grid emission factors (e.g., eGRID ERCT factor for Texas). Does the client purchase Renewable Energy Certificates (RECs) or have specific Power Purchase Agreements (PPAs) that would require support for Market-Based calculation tracks?"*
3.  **Audit Sign-off Access Control Roles**: *"Once an analyst clicks 'Approve & Lock', the row is frozen forever. Should we implement a multi-signature workflow where a Sustainability Lead or an external auditor can 'Unlock' a row in case of emergency, or must it remain permanently immutable?"*
