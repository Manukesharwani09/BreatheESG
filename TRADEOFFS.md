# Tradeoffs Log (`TRADEOFFS.md`)

To build a highly robust, focused, and understandable prototype in 4 days, we deliberately avoided "feature creep." Instead of copy-pasting generic features, we made conscious engineering compromises. 

Below are the **three specific systems we deliberately did not build**, along with our technical justifications.

---

## 1. Automated PDF Invoice OCR Parsing (Utility Bills)
*   **What we did not build**: An automated uploader that accepts raw PDF utility invoices (e.g. PGE, National Grid bills) and extracts the values using Optical Character Recognition (OCR) or Large Language Model (LLM) vision APIs.
*   **Why we made this trade-off**: 
    *   **High Complexity, Low Determinism**: Reading arbitrary PDF invoices from hundreds of global utilities is notoriously fragile. Different layout changes instantly break regex or bounding-box coordinates, leading to silent calculation gaps. LLM vision APIs are slow, expensive, and can hallucinate numerical digits (e.g. converting `8` to `3` or missing decimal points).
    *   **Focus on Accounting Rigor**: We chose to focus our engineering budget on the **core carbon accounting logic** (pro-rata calendarization, database audit logs, math reading checks) rather than building a fragile document parser. We assume the facilities team has access to portal CSV tables or a bulk invoice scraper which outputs structured parameters.

## 2. Real-Time Flight Routing API Integrations (Scope 3 Travel)
*   **What we did not build**: Integrations with external APIs (like OpenSky, Amadeus, or Google Flights) to fetch real-time flight details, layovers, exact airline carrier names, and actual flight paths to compute route distances.
*   **Why we made this trade-off**: 
    *   **Network Dependency & Cost**: Interfacing with real-time routing engines adds external network fragility, rate limits, and expensive licensing fees that are completely unnecessary for a prototype.
    *   **Standardized Compliance Math**: Sustainability reporting standards (like DEFRA and the GHG Protocol) mandate **standardized Great Circle distances** between airports, rather than actual ground flight tracks, which can vary day-by-day due to weather or holding patterns. Implementing a localized **Haversine formula coordinate lookup** is not only mathematically correct and compliant, but also works completely offline with zero API latency.

## 3. Dual-Track Scope 2 Carbon Accounting (Location vs Market-Based)
*   **What we did not build**: Support for calculating and displaying dual-track Scope 2 emissions simultaneously (Location-Based grid factors vs Market-Based energy contract factors).
*   **Why we made this trade-off**: 
    *   **Data Acquisition Overload**: A full Market-Based approach requires modeling a highly complex system of Renewable Energy Certificates (RECs), Guarantees of Origin (GOs), Power Purchase Agreements (PPAs), and utility-specific fuel mix disclosures, which are extremely difficult to acquire and standardise.
    *   **Prototype Clarity**: To avoid cluttering the UI with complex secondary numbers, we prioritized a **location-based grid factor calculation** using lookup tables mapped by plant coordinates. This is the baseline required for 100% of audits. We structured our `EmissionFactor` database table to support a `sub_category` (which represents the grid zone), laying a clean foundation that can be expanded to market-based tracking without changing the schema.
