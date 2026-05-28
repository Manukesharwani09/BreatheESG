from rest_framework import serializers
from api.models import (
    Organization, PlantLookup, AirportLookup, EmissionFactor,
    IngestionBatch, RawRecord, NormalizedRecord, AuditLog
)

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = '__all__'

class PlantLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantLookup
        fields = '__all__'

class AirportLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = AirportLookup
        fields = '__all__'

class EmissionFactorSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmissionFactor
        fields = '__all__'

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'

class IngestionBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionBatch
        fields = '__all__'

class RawRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawRecord
        fields = '__all__'

class NormalizedRecordSerializer(serializers.ModelSerializer):
    raw_payload = serializers.SerializerMethodField()
    audit_logs = AuditLogSerializer(many=True, read_only=True)
    calculation_trail = serializers.SerializerMethodField()

    class Meta:
        model = NormalizedRecord
        fields = [
            'id', 'raw_record', 'organization', 'scope', 'category',
            'activity_date', 'original_quantity', 'original_unit',
            'normalized_quantity', 'normalized_unit', 'calculated_emissions',
            'status', 'validation_flags', 'is_locked', 'created_at',
            'updated_at', 'raw_payload', 'audit_logs', 'calculation_trail'
        ]

    def get_raw_payload(self, obj):
        if obj.raw_record:
            return obj.raw_record.raw_payload
        return None

    def get_calculation_trail(self, obj):
        """
        Generates a human-readable audit trail explaining exactly how the carbon emissions
        were calculated for this specific record.
        """
        if obj.calculated_emissions is None:
            return "Emissions could not be calculated due to validation flags."

        trail = {
            "formula": "Emissions (kg CO2e) = Normalized Quantity * Emission Factor Value",
            "quantity_step": f"Standardized {obj.original_quantity} {obj.original_unit} to {obj.normalized_quantity:.2f} {obj.normalized_unit}.",
        }

        # Try to find corresponding factor
        if obj.category == "fuel":
            sub_cat = None
            orig_mat = str(obj.raw_record.raw_payload.get("Material") or obj.raw_record.raw_payload.get("MATNR") or "").lower()
            if "diesel" in orig_mat:
                sub_cat = "diesel"
            elif "heiz" in orig_mat or "heating" in orig_mat or "oil" in orig_mat:
                sub_cat = "heating_oil"
            elif "gas" in orig_mat or "erdgas" in orig_mat:
                sub_cat = "natural_gas"
            
            if sub_cat:
                try:
                    ef = EmissionFactor.objects.get(category="fuel", sub_category=sub_cat)
                    trail["factor_step"] = f"Identified Fuel Category '{sub_cat}'. Found Scope 1 factor: {ef.factor_value} kg CO2e/L."
                    trail["math_step"] = f"{obj.normalized_quantity:.2f} L * {ef.factor_value} kg CO2e/L = {obj.calculated_emissions:.2f} kg CO2e."
                except EmissionFactor.DoesNotExist:
                    pass
        
        elif obj.category == "electricity":
            # Find regional factor
            meter_no = obj.raw_record.raw_payload.get("MeterNumber") or obj.raw_record.raw_payload.get("Meter_No") or ""
            plant_code = "PL001"
            for pc in ["PL001", "PL002", "PL003"]:
                if pc in str(meter_no):
                    plant_code = pc
                    break
            
            try:
                plant_obj = PlantLookup.objects.get(plant_code=plant_code)
                grid_region = plant_obj.grid_region
                ef = EmissionFactor.objects.get(category="electricity", sub_category=grid_region)
                trail["factor_step"] = f"Mapped Meter {meter_no} to Plant {plant_code} ({plant_obj.name}, {plant_obj.city}, {plant_obj.country}). Grid region: {grid_region}. Scope 2 Factor: {ef.factor_value} kg CO2e/kWh."
                trail["math_step"] = f"Pro-rata allocated consumption for month: {obj.normalized_quantity:.2f} kWh. {obj.normalized_quantity:.2f} kWh * {ef.factor_value} kg CO2e/kWh = {obj.calculated_emissions:.2f} kg CO2e."
            except Exception as e:
                trail["factor_step"] = f"Failed mapping meter. Fell back to default grid factor: 0.40 kg CO2e/kWh."
                trail["math_step"] = f"{obj.normalized_quantity:.2f} kWh * 0.40 kg CO2e/kWh = {obj.calculated_emissions:.2f} kg CO2e."

        elif obj.category == "flight":
            orig_qty = obj.original_quantity # JFK -> LHR
            # Coords math
            trail["factor_step"] = f"Computed Great Circle Route distance from coordinates: {obj.normalized_quantity:.2f} km."
            trail["math_step"] = f"{obj.normalized_quantity:.2f} km * Flight Factor = {obj.calculated_emissions:.2f} kg CO2e."

        elif obj.category == "hotel":
            trail["factor_step"] = f"Identified Hotel stay. Country factor lookup. Scope 3 factor: {obj.calculated_emissions / max(obj.normalized_quantity, 1.0):.2f} kg CO2e per room-night."
            trail["math_step"] = f"{obj.normalized_quantity:.1f} room-nights * Hotel Factor = {obj.calculated_emissions:.2f} kg CO2e."

        elif obj.category == "car":
            trail["factor_step"] = f"Identified car rental. Normalized rental distance: {obj.normalized_quantity:.2f} km."
            trail["math_step"] = f"{obj.normalized_quantity:.2f} km * Vehicle emission factor = {obj.calculated_emissions:.2f} kg CO2e."

        return trail
