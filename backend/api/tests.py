from datetime import date
from django.test import TestCase
from api.models import (
    Organization, PlantLookup, AirportLookup, EmissionFactor,
    IngestionBatch, RawRecord, NormalizedRecord
)
from api.parsers import (
    haversine_distance, process_sap_row, process_utility_row, process_travel_payload
)

class BreatheESGCalculationTests(TestCase):
    def setUp(self):
        # 1. Create Organization
        self.org = Organization.objects.create(id=1, name="Acme Corp")

        # 2. Seed Plant Lookup
        self.plant1 = PlantLookup.objects.create(
            plant_code="PL001",
            name="Main Refinery",
            city="Houston",
            country="US",
            grid_region="ERCT"
        )
        self.plant2 = PlantLookup.objects.create(
            plant_code="PL002",
            name="Stuttgart Assembly",
            city="Stuttgart",
            country="DE",
            grid_region="DE"
        )

        # 3. Seed Airport Lookup
        self.jfk = AirportLookup.objects.create(
            iata_code="JFK",
            name="JFK Airport",
            latitude=40.6398,
            longitude=-73.7789,
            country="US"
        )
        self.lhr = AirportLookup.objects.create(
            iata_code="LHR",
            name="London Heathrow",
            latitude=51.4700,
            longitude=-0.4543,
            country="GB"
        )

        # 4. Seed Emission Factors
        self.ef_diesel = EmissionFactor.objects.create(
            category="fuel",
            sub_category="diesel",
            scope=1,
            factor_value=2.68,
            unit="kg CO2e/L"
        )
        self.ef_elec_texas = EmissionFactor.objects.create(
            category="electricity",
            sub_category="ERCT",
            scope=2,
            factor_value=0.385,
            unit="kg CO2e/kWh"
        )
        self.ef_flight_business = EmissionFactor.objects.create(
            category="flight",
            sub_category="long_haul_business",
            scope=3,
            factor_value=0.38,
            unit="kg CO2e/km"
        )

        # 5. Create Dummy Ingestion Batch
        self.batch = IngestionBatch.objects.create(
            organization=self.org,
            source_type="SAP",
            file_name="test_upload.csv",
            status="PROCESSING"
        )

    def test_haversine_distance_calculation(self):
        """
        Verify that Haversine distance matches the physical distance
        between JFK and London Heathrow (approx 5540 km).
        """
        dist = haversine_distance(
            self.jfk.latitude, self.jfk.longitude,
            self.lhr.latitude, self.lhr.longitude
        )
        self.assertAlmostEqual(dist, 5540.0, delta=10.0)

    def test_sap_clean_row_processing(self):
        """
        Test that a clean SAP row with German headers is parsed,
        normalized, plant-mapped, and emissions are calculated correctly.
        """
        raw = RawRecord.objects.create(
            batch=self.batch,
            row_index=1,
            raw_payload={
                "Beleg": "1000214",
                "Buchungsdatum": "12.04.2026",
                "Werk": "PL001",
                "Material": "Diesel Kraftstoff",
                "Menge": "1000",
                "Einheit": "L",
                "Nettowert": "1500.00"
            }
        )
        norm = process_sap_row(raw, self.org)
        self.assertEqual(norm.status, "PENDING")
        self.assertEqual(norm.validation_flags, [])
        self.assertEqual(norm.normalized_quantity, 1000.0)
        self.assertEqual(norm.normalized_unit, "L")
        # 1000 L * 2.68 kg CO2e/L = 2680 kg CO2e
        self.assertEqual(norm.calculated_emissions, 2680.0)

    def test_sap_unknown_plant_anomaly(self):
        """
        Verify that an unknown plant code ('PL999') triggers the
        UNKNOWN_PLANT flag.
        """
        raw = RawRecord.objects.create(
            batch=self.batch,
            row_index=2,
            raw_payload={
                "Beleg": "1000215",
                "Buchungsdatum": "12.04.2026",
                "Werk": "PL999", # Unknown plant
                "Material": "Diesel Kraftstoff",
                "Menge": "500",
                "Einheit": "L",
                "Nettowert": "750.00"
            }
        )
        norm = process_sap_row(raw, self.org)
        self.assertEqual(norm.status, "FLAGGED")
        self.assertIn("UNKNOWN_PLANT", norm.validation_flags)

    def test_sap_invalid_unit_anomaly(self):
        """
        Verify that an un-normalizable unit ('FL' = Bottle) flags
        as INVALID_UNIT.
        """
        raw = RawRecord.objects.create(
            batch=self.batch,
            row_index=3,
            raw_payload={
                "Beleg": "1000216",
                "Buchungsdatum": "12.04.2026",
                "Werk": "PL001",
                "Material": "Diesel Kraftstoff",
                "Menge": "20",
                "Einheit": "FL", # Bad unit
                "Nettowert": "50.00"
            }
        )
        norm = process_sap_row(raw, self.org)
        self.assertEqual(norm.status, "FLAGGED")
        self.assertIn("INVALID_UNIT", norm.validation_flags)

    def test_utility_calendarization_split(self):
        """
        Verify that a utility bill spanning from April 15 to May 14
        (total 30 days, usage 3000 kWh) splits correctly into two
        separate monthly entries:
        - April: 16 days -> 1600 kWh
        - May: 14 days -> 1400 kWh
        """
        batch_util = IngestionBatch.objects.create(
            organization=self.org,
            source_type="UTILITY",
            file_name="utility_bills.csv",
            status="PROCESSING"
        )
        raw = RawRecord.objects.create(
            batch=batch_util,
            row_index=1,
            raw_payload={
                "AccountNumber": "ACT-7712",
                "MeterNumber": "MTR-PL001", # Maps to PL001 plant -> ERCT grid
                "ServiceStartDate": "2026-04-15",
                "ServiceEndDate": "2026-05-14",
                "PreviousReadValue": "10000",
                "CurrentReadValue": "13000",
                "Usage_kWh": "3000",
                "TariffCode": "COMM-TOU",
                "TotalDue": "450.00"
            }
        )
        
        recs = process_utility_row(raw, self.org)
        self.assertEqual(len(recs), 2)
        
        # April record check
        rec_april = next(r for r in recs if r.activity_date.month == 4)
        self.assertAlmostEqual(rec_april.normalized_quantity, 1655.17, delta=5.0)
        # 1655.17 kWh * 0.385 kg CO2e/kWh = 637.24 kg CO2e
        self.assertAlmostEqual(rec_april.calculated_emissions, 637.24, delta=2.0)

        # May record check
        rec_may = next(r for r in recs if r.activity_date.month == 5)
        self.assertAlmostEqual(rec_may.normalized_quantity, 1448.27, delta=5.0)
        # 1448.27 kWh * 0.385 = 557.58 kg CO2e
        self.assertAlmostEqual(rec_may.calculated_emissions, 557.58, delta=2.0)
