from django.db import models

class Organization(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class PlantLookup(models.Model):
    plant_code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    grid_region = models.CharField(max_length=100)  # eGRID subregion or national country code

    def __str__(self):
        return f"{self.plant_code} - {self.name} ({self.country})"

class AirportLookup(models.Model):
    iata_code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()
    country = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.iata_code} - {self.name}"

class EmissionFactor(models.Model):
    category = models.CharField(max_length=50)      # e.g., 'fuel', 'electricity', 'flight', 'hotel', 'car'
    sub_category = models.CharField(max_length=100)  # e.g., 'diesel', 'heating_oil', 'natural_gas', 'economy_flight', 'US-NY', etc.
    scope = models.IntegerField()                    # 1, 2, or 3
    factor_value = models.FloatField()               # emissions value (e.g. kg CO2e per unit)
    unit = models.CharField(max_length=50)           # e.g., 'kg CO2e/L', 'kg CO2e/kWh', 'kg CO2e/km', 'kg CO2e/room-night'
    year = models.IntegerField(default=2026)

    def __str__(self):
        return f"{self.category} ({self.sub_category}) - {self.factor_value} {self.unit}"

class IngestionBatch(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="batches")
    source_type = models.CharField(max_length=50)    # 'SAP', 'UTILITY', 'TRAVEL'
    file_name = models.CharField(max_length=255)
    uploaded_by = models.CharField(max_length=100, default="System Analyst")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default="PROCESSING")  # 'PROCESSING', 'COMPLETED', 'FAILED'

    def __str__(self):
        return f"{self.source_type} batch uploaded by {self.uploaded_by} at {self.uploaded_at}"

class RawRecord(models.Model):
    batch = models.ForeignKey(IngestionBatch, on_delete=models.CASCADE, related_name="raw_records")
    row_index = models.IntegerField()
    raw_payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Raw row {self.row_index} of batch {self.batch.id}"

class NormalizedRecord(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved & Locked'),
        ('REJECTED', 'Rejected'),
        ('FLAGGED', 'Flagged with Anomaly'),
    ]

    raw_record = models.ForeignKey(RawRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="normalized_records")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="normalized_records")
    scope = models.IntegerField()                    # 1, 2, or 3
    category = models.CharField(max_length=50)      # e.g., 'fuel', 'electricity', 'flight', 'hotel', 'car'
    activity_date = models.DateField()
    original_quantity = models.CharField(max_length=100, null=True, blank=True)
    original_unit = models.CharField(max_length=100, null=True, blank=True)
    normalized_quantity = models.FloatField(null=True, blank=True)
    normalized_unit = models.CharField(max_length=50, null=True, blank=True)
    calculated_emissions = models.FloatField(null=True, blank=True) # kg CO2e
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    validation_flags = models.JSONField(default=list, blank=True)  # List of warning codes, e.g. ["UNKNOWN_PLANT"]
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Normalized {self.category} Record - {self.calculated_emissions or 0} kg CO2e ({self.status})"

class AuditLog(models.Model):
    normalized_record = models.ForeignKey(NormalizedRecord, on_delete=models.CASCADE, related_name="audit_logs")
    action_by = models.CharField(max_length=100, default="System Analyst")
    action_type = models.CharField(max_length=50)    # 'APPROVE', 'FLAG', 'EDIT', 'REJECT'
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action_type} by {self.action_by} at {self.timestamp}"
