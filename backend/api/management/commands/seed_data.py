import os
from django.core.management.base import BaseCommand
from api.models import Organization, PlantLookup, AirportLookup, EmissionFactor

class Command(BaseCommand):
    help = "Seeds initial database lookup records for the Breathe ESG prototype."

    def handle(self, *args, **options):
        self.stdout.write("Seeding data...")

        # 1. Organization
        org, created = Organization.objects.get_or_create(id=1, defaults={"name": "Acme Corp"})
        if created:
            self.stdout.write("Created Organization: Acme Corp")
        else:
            self.stdout.write("Organization Acme Corp already exists")

        # 2. Plant Lookup
        plants = [
            {"plant_code": "PL001", "name": "Main Refinery", "city": "Houston", "country": "US", "grid_region": "ERCT"},
            {"plant_code": "PL002", "name": "Stuttgart Assembly", "city": "Stuttgart", "country": "DE", "grid_region": "DE"},
            {"plant_code": "PL003", "name": "Bengaluru IT Hub", "city": "Bengaluru", "country": "IN", "grid_region": "IN"},
        ]
        for p in plants:
            pl, created = PlantLookup.objects.get_or_create(plant_code=p["plant_code"], defaults=p)
            if created:
                self.stdout.write(f"Created Plant: {p['plant_code']}")

        # 3. Airport Lookup
        airports = [
            {"iata_code": "JFK", "name": "John F. Kennedy International Airport", "latitude": 40.6398, "longitude": -73.7789, "country": "US"},
            {"iata_code": "LHR", "name": "London Heathrow Airport", "latitude": 51.4700, "longitude": -0.4543, "country": "GB"},
            {"iata_code": "CDG", "name": "Charles de Gaulle Airport", "latitude": 49.0097, "longitude": 2.5479, "country": "FR"},
            {"iata_code": "FRA", "name": "Frankfurt Airport", "latitude": 50.0333, "longitude": 8.5705, "country": "DE"},
            {"iata_code": "BLR", "name": "Kempegowda International Airport", "latitude": 13.1986, "longitude": 77.7066, "country": "IN"},
            {"iata_code": "SFO", "name": "San Francisco International Airport", "latitude": 37.6190, "longitude": -122.3749, "country": "US"},
        ]
        for a in airports:
            ap, created = AirportLookup.objects.get_or_create(iata_code=a["iata_code"], defaults=a)
            if created:
                self.stdout.write(f"Created Airport: {a['iata_code']}")

        # 4. Emission Factors
        factors = [
            # Scope 1 - Fuels
            {"category": "fuel", "sub_category": "diesel", "scope": 1, "factor_value": 2.68, "unit": "kg CO2e/L"},
            {"category": "fuel", "sub_category": "heating_oil", "scope": 1, "factor_value": 2.54, "unit": "kg CO2e/L"},
            {"category": "fuel", "sub_category": "natural_gas", "scope": 1, "factor_value": 2.03, "unit": "kg CO2e/m3"},
            
            # Scope 2 - Electricity (Grid regions)
            {"category": "electricity", "sub_category": "ERCT", "scope": 2, "factor_value": 0.385, "unit": "kg CO2e/kWh"},
            {"category": "electricity", "sub_category": "DE", "scope": 2, "factor_value": 0.350, "unit": "kg CO2e/kWh"},
            {"category": "electricity", "sub_category": "IN", "scope": 2, "factor_value": 0.710, "unit": "kg CO2e/kWh"},
            {"category": "electricity", "sub_category": "default", "scope": 2, "factor_value": 0.400, "unit": "kg CO2e/kWh"},

            # Scope 3 - Flight (Short-haul < 480km, Medium-haul 480-3700km, Long-haul > 3700km)
            {"category": "flight", "sub_category": "short_haul_economy", "scope": 3, "factor_value": 0.150, "unit": "kg CO2e/km"},
            {"category": "flight", "sub_category": "medium_haul_economy", "scope": 3, "factor_value": 0.140, "unit": "kg CO2e/km"},
            {"category": "flight", "sub_category": "medium_haul_business", "scope": 3, "factor_value": 0.280, "unit": "kg CO2e/km"},
            {"category": "flight", "sub_category": "long_haul_economy", "scope": 3, "factor_value": 0.130, "unit": "kg CO2e/km"},
            {"category": "flight", "sub_category": "long_haul_business", "scope": 3, "factor_value": 0.380, "unit": "kg CO2e/km"},

            # Scope 3 - Hotels (per room night)
            {"category": "hotel", "sub_category": "US", "scope": 3, "factor_value": 18.5, "unit": "kg CO2e/room-night"},
            {"category": "hotel", "sub_category": "GB", "scope": 3, "factor_value": 12.2, "unit": "kg CO2e/room-night"},
            {"category": "hotel", "sub_category": "DE", "scope": 3, "factor_value": 15.4, "unit": "kg CO2e/room-night"},
            {"category": "hotel", "sub_category": "IN", "scope": 3, "factor_value": 42.1, "unit": "kg CO2e/room-night"},
            {"category": "hotel", "sub_category": "FR", "scope": 3, "factor_value": 6.5, "unit": "kg CO2e/room-night"},
            {"category": "hotel", "sub_category": "default", "scope": 3, "factor_value": 20.0, "unit": "kg CO2e/room-night"},

            # Scope 3 - Rental Cars (per km)
            {"category": "car", "sub_category": "SUV", "scope": 3, "factor_value": 0.220, "unit": "kg CO2e/km"},
            {"category": "car", "sub_category": "Sedan", "scope": 3, "factor_value": 0.150, "unit": "kg CO2e/km"},
            {"category": "car", "sub_category": "Electric", "scope": 3, "factor_value": 0.040, "unit": "kg CO2e/km"},
        ]

        for f in factors:
            ef, created = EmissionFactor.objects.get_or_create(
                category=f["category"],
                sub_category=f["sub_category"],
                defaults=f
            )
            if created:
                self.stdout.write(f"Created EmissionFactor: {f['category']} - {f['sub_category']}")

        self.stdout.write("Database seeded successfully!")
