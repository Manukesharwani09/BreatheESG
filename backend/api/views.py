import csv
import json
import io
from datetime import datetime
from django.db.models import Sum, Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.models import (
    Organization, PlantLookup, AirportLookup, EmissionFactor,
    IngestionBatch, RawRecord, NormalizedRecord, AuditLog
)
from api.serializers import (
    OrganizationSerializer, PlantLookupSerializer, AirportLookupSerializer,
    EmissionFactorSerializer, IngestionBatchSerializer, RawRecordSerializer,
    NormalizedRecordSerializer, AuditLogSerializer
)
from api.parsers import (
    process_sap_row, process_utility_row, process_travel_payload
)

# -------------------------------------------------------------------------
# LOOKUPS & CONFIG VIEWSETS
# -------------------------------------------------------------------------

class PlantLookupViewSet(viewsets.ModelViewSet):
    queryset = PlantLookup.objects.all()
    serializer_class = PlantLookupSerializer

class AirportLookupViewSet(viewsets.ModelViewSet):
    queryset = AirportLookup.objects.all()
    serializer_class = AirportLookupSerializer

class EmissionFactorViewSet(viewsets.ModelViewSet):
    queryset = EmissionFactor.objects.all()
    serializer_class = EmissionFactorSerializer

# -------------------------------------------------------------------------
# INGESTION BATCH VIEWSET
# -------------------------------------------------------------------------

class IngestionBatchViewSet(viewsets.ModelViewSet):
    queryset = IngestionBatch.objects.all().order_by('-uploaded_at')
    serializer_class = IngestionBatchSerializer

    @action(detail=False, methods=['post'], url_path='ingest')
    def ingest_file(self, request):
        """
        Main ingestion endpoint. Handles file upload, raw record preservation,
        and triggers the normalization pipeline for SAP, UTILITY, and TRAVEL.
        """
        source_type = request.data.get("source_type")
        file_obj = request.FILES.get("file")
        uploaded_by = request.data.get("uploaded_by", "Analyst User")

        if not source_type or not file_obj:
            return Response(
                {"error": "Missing source_type or file"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        source_type = source_type.upper()
        if source_type not in ["SAP", "UTILITY", "TRAVEL"]:
            return Response(
                {"error": "Invalid source_type. Must be SAP, UTILITY, or TRAVEL"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get default organization Acme Corp
        org = Organization.objects.first()
        if not org:
            org = Organization.objects.create(id=1, name="Acme Corp")

        # Create Ingestion Batch
        batch = IngestionBatch.objects.create(
            organization=org,
            source_type=source_type,
            file_name=file_obj.name,
            uploaded_by=uploaded_by,
            status="PROCESSING"
        )

        try:
            if source_type == "SAP":
                # Process CSV file
                decoded_file = file_obj.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string, delimiter=';' if ';' in decoded_file else ',')
                
                row_idx = 1
                for row in reader:
                    # Save Raw Record
                    raw_rec = RawRecord.objects.create(
                        batch=batch,
                        row_index=row_idx,
                        raw_payload=row
                    )
                    # Normalize
                    norm_rec = process_sap_row(raw_rec, org)
                    norm_rec.save()
                    row_idx += 1

            elif source_type == "UTILITY":
                # Process CSV file
                decoded_file = file_obj.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string, delimiter=';' if ';' in decoded_file else ',')
                
                row_idx = 1
                for row in reader:
                    # Save Raw
                    raw_rec = RawRecord.objects.create(
                        batch=batch,
                        row_index=row_idx,
                        raw_payload=row
                    )
                    # Normalize (returns a list due to pro-rata calendar splitting)
                    norm_recs = process_utility_row(raw_rec, org)
                    for r in norm_recs:
                        r.save()
                    row_idx += 1

            elif source_type == "TRAVEL":
                # Process JSON file
                decoded_file = file_obj.read().decode('utf-8')
                trips = json.loads(decoded_file)
                
                if not isinstance(trips, list):
                    trips = [trips]

                row_idx = 1
                for trip in trips:
                    # Save Raw
                    raw_rec = RawRecord.objects.create(
                        batch=batch,
                        row_index=row_idx,
                        raw_payload=trip
                    )
                    # Normalize
                    norm_recs = process_travel_payload(raw_rec, org)
                    for r in norm_recs:
                        r.save()
                    row_idx += 1

            batch.status = "COMPLETED"
            batch.save()
            return Response(IngestionBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            batch.status = "FAILED"
            batch.save()
            return Response(
                {"error": f"Failed to ingest: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# -------------------------------------------------------------------------
# NORMALIZED RECORDS VIEWSET
# -------------------------------------------------------------------------

class NormalizedRecordViewSet(viewsets.ModelViewSet):
    queryset = NormalizedRecord.objects.all().order_by('-created_at')
    serializer_class = NormalizedRecordSerializer

    def get_queryset(self):
        """
        Supports advanced filtering by status, category, scope, and source.
        """
        qs = NormalizedRecord.objects.all().order_by('-created_at')
        
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())

        category_param = self.request.query_params.get('category')
        if category_param:
            qs = qs.filter(category=category_param.lower())

        scope_param = self.request.query_params.get('scope')
        if scope_param:
            qs = qs.filter(scope=int(scope_param))

        source_param = self.request.query_params.get('source')
        if source_param:
            # Map source to underlying raw records batch source_type
            qs = qs.filter(raw_record__batch__source_type=source_param.upper())

        return qs

    def update(self, request, *args, **kwargs):
        """
        Supports inline overrides by analysts. Triggers recalculation
        of emissions and stores changes in the immutable AuditLog.
        """
        instance = self.get_object()
        
        if instance.is_locked:
            return Response(
                {"error": "This record is APPROVED and locked for auditing. It cannot be modified."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Keep original values for AuditLog
        old_values = {
            "normalized_quantity": instance.normalized_quantity,
            "normalized_unit": instance.normalized_unit,
            "calculated_emissions": instance.calculated_emissions,
            "status": instance.status,
            "validation_flags": instance.validation_flags
        }

        # Retrieve new user inputs
        new_qty = request.data.get("normalized_quantity")
        new_unit = request.data.get("normalized_unit")
        new_status = request.data.get("status")
        reason = request.data.get("reason", "Analyst Override")
        action_by = request.data.get("action_by", "Analyst User")

        if new_qty is not None:
            try:
                instance.normalized_quantity = float(new_qty)
            except ValueError:
                return Response({"error": "Quantity must be numeric"}, status=status.HTTP_400_BAD_REQUEST)
        
        if new_unit is not None:
            instance.normalized_unit = str(new_unit)

        if new_status is not None:
            instance.status = str(new_status).upper()

        # Recalculate Emissions based on new inputs
        if new_qty is not None or new_unit is not None:
            # Re-fetch emission factor matching category and specific subcategory
            # Find sub category from original mapping or default
            sub_category = "diesel"
            if instance.category == "fuel":
                orig_mat = str(instance.raw_record.raw_payload.get("Material") or instance.raw_record.raw_payload.get("MATNR") or "").lower()
                if "diesel" in orig_mat:
                    sub_category = "diesel"
                elif "heiz" in orig_mat or "heating" in orig_mat or "oil" in orig_mat:
                    sub_category = "heating_oil"
                elif "gas" in orig_mat or "erdgas" in orig_mat:
                    sub_category = "natural_gas"
            elif instance.category == "electricity":
                meter_no = instance.raw_record.raw_payload.get("MeterNumber") or instance.raw_record.raw_payload.get("Meter_No") or ""
                plant_code = "PL001"
                for pc in ["PL001", "PL002", "PL003"]:
                    if pc in str(meter_no):
                        plant_code = pc
                        break
                try:
                    plant_obj = PlantLookup.objects.get(plant_code=plant_code)
                    sub_category = plant_obj.grid_region
                except PlantLookup.DoesNotExist:
                    sub_category = "default"
            elif instance.category == "flight":
                distance_km = instance.normalized_quantity
                haul_type = "medium_haul"
                if distance_km < 480.0:
                    haul_type = "short_haul"
                elif distance_km > 3700.0:
                    haul_type = "long_haul"
                sub_category = f"{haul_type}_economy"
            elif instance.category == "hotel":
                country = instance.raw_record.raw_payload.get("country") or "default"
                sub_category = str(country).upper().strip()
            elif instance.category == "car":
                car_class = instance.raw_record.raw_payload.get("carClass") or "Sedan"
                sub_category = str(car_class).strip()

            try:
                ef = EmissionFactor.objects.get(category=instance.category, sub_category=sub_category)
            except EmissionFactor.DoesNotExist:
                ef = EmissionFactor.objects.filter(category=instance.category).first()

            if ef:
                instance.calculated_emissions = instance.normalized_quantity * ef.factor_value
            
            # Clear validation flags if the user fixed the issue
            if "INVALID_UNIT" in instance.validation_flags and new_unit:
                instance.validation_flags = [f for f in instance.validation_flags if f != "INVALID_UNIT"]
            if "NEGATIVE_QUANTITY" in instance.validation_flags and instance.normalized_quantity > 0:
                instance.validation_flags = [f for f in instance.validation_flags if f != "NEGATIVE_QUANTITY"]

        instance.save()

        # Write AuditLog
        new_values = {
            "normalized_quantity": instance.normalized_quantity,
            "normalized_unit": instance.normalized_unit,
            "calculated_emissions": instance.calculated_emissions,
            "status": instance.status,
            "validation_flags": instance.validation_flags
        }

        AuditLog.objects.create(
            normalized_record=instance,
            action_by=action_by,
            action_type="EDIT",
            old_values=old_values,
            new_values=new_values,
            reason=reason
        )

        return Response(NormalizedRecordSerializer(instance).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """
        Signs off a row, lock it from any future edits.
        """
        instance = self.get_object()
        if instance.is_locked:
            return Response({"error": "Already approved and locked"}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get("reason", "Analyst Sign-off")
        action_by = request.data.get("action_by", "Analyst User")

        old_status = instance.status
        instance.status = "APPROVED"
        instance.is_locked = True
        instance.save()

        AuditLog.objects.create(
            normalized_record=instance,
            action_by=action_by,
            action_type="APPROVE",
            old_values={"status": old_status, "is_locked": False},
            new_values={"status": "APPROVED", "is_locked": True},
            reason=reason
        )

        return Response(NormalizedRecordSerializer(instance).data)

    @action(detail=True, methods=['post'])
    def flag(self, request, pk=None):
        """
        Flags a record with specific anomaly notes.
        """
        instance = self.get_object()
        if instance.is_locked:
            return Response({"error": "Cannot flag a locked record"}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get("reason", "Flagging row anomaly")
        action_by = request.data.get("action_by", "Analyst User")

        old_status = instance.status
        instance.status = "FLAGGED"
        
        # Add custom flag code to validation_flags
        if "ANALYST_FLAGGED" not in instance.validation_flags:
            instance.validation_flags.append("ANALYST_FLAGGED")
            
        instance.save()

        AuditLog.objects.create(
            normalized_record=instance,
            action_by=action_by,
            action_type="FLAG",
            old_values={"status": old_status},
            new_values={"status": "FLAGGED"},
            reason=reason
        )

        return Response(NormalizedRecordSerializer(instance).data)

    @action(detail=False, methods=['post'], url_path='bulk_approve')
    def bulk_approve(self, request):
        """
        Bulk approves clean rows to accelerate analyst workflows.
        """
        ids = request.data.get("ids", [])
        action_by = request.data.get("action_by", "Analyst User")
        reason = request.data.get("reason", "Bulk Analyst Sign-off")

        if not ids:
            return Response({"error": "No IDs provided"}, status=status.HTTP_400_BAD_REQUEST)

        records = NormalizedRecord.objects.filter(id__in=ids, is_locked=False)
        updated_count = 0

        for rec in records:
            old_status = rec.status
            rec.status = "APPROVED"
            rec.is_locked = True
            rec.save()

            AuditLog.objects.create(
                normalized_record=rec,
                action_by=action_by,
                action_type="APPROVE",
                old_values={"status": old_status, "is_locked": False},
                new_values={"status": "APPROVED", "is_locked": True},
                reason=reason
            )
            updated_count += 1

        return Response({"message": f"Successfully approved {updated_count} records."})

# -------------------------------------------------------------------------
# METRICS & STATS VIEWSET
# -------------------------------------------------------------------------

class StatsViewSet(viewsets.ViewSet):
    """
    Computes aggregated performance data and carbon accounting breakdown.
    """
    def list(self, request):
        total_carbon = NormalizedRecord.objects.filter(
            status="APPROVED"
        ).aggregate(sum=Sum('calculated_emissions'))['sum'] or 0.0

        # Total including pending to show hypothetical full footprint
        all_carbon = NormalizedRecord.objects.all().aggregate(sum=Sum('calculated_emissions'))['sum'] or 0.0

        total_rows = NormalizedRecord.objects.count()
        approved_rows = NormalizedRecord.objects.filter(status="APPROVED").count()
        flagged_rows = NormalizedRecord.objects.filter(status="FLAGGED").count()
        pending_rows = NormalizedRecord.objects.filter(status="PENDING").count()

        approval_rate = (approved_rows / total_rows * 100.0) if total_rows > 0 else 0.0
        flagged_rate = (flagged_rows / total_rows * 100.0) if total_rows > 0 else 0.0

        # Breakdown by Scope
        scope_breakdown = NormalizedRecord.objects.values('scope').annotate(
            carbon=Sum('calculated_emissions'),
            count=Count('id')
        )

        # Breakdown by Source
        source_breakdown = NormalizedRecord.objects.values('raw_record__batch__source_type').annotate(
            carbon=Sum('calculated_emissions'),
            count=Count('id')
        )

        # Breakdown by Category
        category_breakdown = NormalizedRecord.objects.values('category').annotate(
            carbon=Sum('calculated_emissions'),
            count=Count('id')
        )

        data = {
            "total_approved_carbon": total_carbon,
            "total_hypothetical_carbon": all_carbon,
            "total_rows": total_rows,
            "approved_rows": approved_rows,
            "flagged_rows": flagged_rows,
            "pending_rows": pending_rows,
            "approval_rate": approval_rate,
            "flagged_rate": flagged_rate,
            "scope_breakdown": list(scope_breakdown),
            "source_breakdown": list(source_breakdown),
            "category_breakdown": list(category_breakdown)
        }
        return Response(data)

# -------------------------------------------------------------------------
# SIMULATION INGESTION TRIGGERS
# -------------------------------------------------------------------------

class SimulationViewSet(viewsets.ViewSet):
    """
    Generates highly realistic, complex sample datasets for demonstration.
    """
    @action(detail=False, methods=['post'], url_path='seed_all')
    def seed_simulation_data(self, request):
        org = Organization.objects.first()
        if not org:
            org = Organization.objects.create(id=1, name="Acme Corp")

        # 1. SAP Simulation (Fuel and Procurement)
        sap_batch = IngestionBatch.objects.create(
            organization=org,
            source_type="SAP",
            file_name="sap_extract_q2_2026.csv",
            uploaded_by="SAP Integration (Automated)",
            status="COMPLETED"
        )

        sap_payloads = [
            {"Beleg": "1000214", "Buchungsdatum": "12.04.2026", "Werk": "PL001", "Material": "Diesel Kraftstoff", "Menge": "1250", "Einheit": "L", "Nettowert": "1800.00"},
            {"Beleg": "1000215", "Buchungsdatum": "20.04.2026", "Werk": "PL002", "Material": "Heizöl schwer", "Menge": "3500", "Einheit": "L", "Nettowert": "4200.00"},
            {"Beleg": "1000216", "Buchungsdatum": "25.04.2026", "Werk": "PL003", "Material": "Erdgas Lieferungen", "Menge": "480", "Einheit": "M3", "Nettowert": "600.00"},
            # Anomaly 1: Unknown Plant
            {"Beleg": "1000217", "Buchungsdatum": "28.04.2026", "Werk": "PL999", "Material": "Diesel Kraftstoff", "Menge": "800", "Einheit": "L", "Nettowert": "1100.00"},
            # Anomaly 2: Inconsistent Unit ("FL" = Flasche / Bottle)
            {"Beleg": "1000218", "Buchungsdatum": "02.05.2026", "Werk": "PL001", "Material": "Diesel Kraftstoff", "Menge": "20", "Einheit": "FL", "Nettowert": "120.00"},
            # Anomaly 3: Negative Quantity
            {"Beleg": "1000219", "Buchungsdatum": "05.05.2026", "Werk": "PL002", "Material": "Heizöl schwer", "Menge": "-150", "Einheit": "L", "Nettowert": "-180.00"}
        ]

        for i, row in enumerate(sap_payloads):
            raw = RawRecord.objects.create(batch=sap_batch, row_index=i+1, raw_payload=row)
            norm = process_sap_row(raw, org)
            norm.save()

        # 2. Utility Simulation (Electricity with calendar splits and reading gap check)
        util_batch = IngestionBatch.objects.create(
            organization=org,
            source_type="UTILITY",
            file_name="utility_direct_scrape_may26.csv",
            uploaded_by="Facilities Portal Scraper",
            status="COMPLETED"
        )

        util_payloads = [
            # Standard month cycle
            {"AccountNumber": "ACT-7711", "MeterNumber": "MTR-PL001-A", "ServiceStartDate": "2026-04-01", "ServiceEndDate": "2026-04-30", "PreviousReadValue": "10250", "CurrentReadValue": "15450", "Usage_kWh": "5200", "TariffCode": "COMM-FLAT", "TotalDue": "780.00"},
            # Mid-month split cycle (April 15 to May 14) -> Calendarization split!
            {"AccountNumber": "ACT-7712", "MeterNumber": "MTR-PL002-B", "ServiceStartDate": "2026-04-15", "ServiceEndDate": "2026-05-14", "PreviousReadValue": "22450", "CurrentReadValue": "25450", "Usage_kWh": "3000", "TariffCode": "COMM-TOU", "TotalDue": "495.00"},
            # Anomaly 1: Reading mathematical gap (Current - Previous != Usage)
            {"AccountNumber": "ACT-7713", "MeterNumber": "MTR-PL003-C", "ServiceStartDate": "2026-04-01", "ServiceEndDate": "2026-04-30", "PreviousReadValue": "8900", "CurrentReadValue": "10900", "Usage_kWh": "3500", "TariffCode": "COMM-PEAK", "TotalDue": "580.00"}
        ]

        for i, row in enumerate(util_payloads):
            raw = RawRecord.objects.create(batch=util_batch, row_index=i+1, raw_payload=row)
            recs = process_utility_row(raw, org)
            for r in recs:
                r.save()

        # 3. Concur Travel Simulation (Complex Scope 3 segments)
        travel_batch = IngestionBatch.objects.create(
            organization=org,
            source_type="TRAVEL",
            file_name="concur_itineraries_q2.json",
            uploaded_by="Concur API Integration Sync",
            status="COMPLETED"
        )

        travel_payloads = [
            {
                "tripId": "TRIP-8821A",
                "travelerName": "Jane Doe",
                "segments": [
                    # Premium Long-haul Flight (Business) -> High carbon multiplier!
                    {"type": "Air", "departure": "JFK", "arrival": "LHR", "class": "Business", "date": "2026-05-10", "cost": 4500.00},
                    # Hotel in UK (Grid moderate)
                    {"type": "Hotel", "hotelName": "London Marriott", "city": "London", "country": "GB", "nights": "4", "rooms": "1", "checkInDate": "2026-05-10", "cost": 1200.00},
                    # SUV rental -> High carbon car factor
                    {"type": "Car", "carClass": "SUV", "distance": "120", "distanceUnit": "miles", "date": "2026-05-10", "cost": 300.00}
                ]
            },
            {
                "tripId": "TRIP-8822B",
                "travelerName": "Arjun Mehta",
                "segments": [
                    # Medium-haul Flight (Economy)
                    {"type": "Air", "departure": "FRA", "arrival": "BLR", "class": "Economy", "date": "2026-05-14", "cost": 950.00},
                    # Hotel in India (Extremely high carbon factor due to heavy coal grid!)
                    {"type": "Hotel", "hotelName": "Taj Bengaluru", "city": "Bengaluru", "country": "IN", "nights": "5", "rooms": "1", "checkInDate": "2026-05-15", "cost": 1500.00},
                    # Electric car rental -> Very low carbon car factor
                    {"type": "Car", "carClass": "Electric", "distance": "80", "distanceUnit": "km", "date": "2026-05-15", "cost": 200.00}
                ]
            },
            {
                "tripId": "TRIP-8823C",
                "travelerName": "Sophie Laurent",
                "segments": [
                    # Short flight (Economy)
                    {"type": "Air", "departure": "CDG", "arrival": "FRA", "class": "Economy", "date": "2026-05-18", "cost": 250.00},
                    # Hotel in France (Extremely low carbon factor due to nuclear baseline grid!)
                    {"type": "Hotel", "hotelName": "Hyatt Paris", "city": "Paris", "country": "FR", "nights": "2", "rooms": "1", "checkInDate": "2026-05-18", "cost": 600.00}
                ]
            }
        ]

        for i, trip in enumerate(travel_payloads):
            raw = RawRecord.objects.create(batch=travel_batch, row_index=i+1, raw_payload=trip)
            recs = process_travel_payload(raw, org)
            for r in recs:
                r.save()

        return Response({"message": "Successfully generated full simulated dataset for SAP, Utility, and Travel."})
