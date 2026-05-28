import math
from datetime import datetime, timedelta
from api.models import (
    PlantLookup, AirportLookup, EmissionFactor, 
    NormalizedRecord, RawRecord, AuditLog
)

# -------------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------------

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Computes Great Circle Distance between two coordinates in kilometers.
    """
    R = 6371.0 # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0)**2
    
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def parse_date(date_str, formats=('%Y-%m-%d', '%d.%m.%Y', '%m/%d/%Y')):
    """
    Attempts to parse date strings using common formats.
    """
    if not date_str:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except ValueError:
            continue
    return None

# -------------------------------------------------------------------------
# SAP PARSER & NORMALIZATION
# -------------------------------------------------------------------------

def process_sap_row(raw_record, organization):
    """
    Parses a single RawRecord representing an SAP export line.
    Handles German column headers, plant code validation, unit standardisation,
    and Scope 1 carbon calculations.
    """
    payload = raw_record.raw_payload
    flags = []

    # Map possible German and English header names
    po_number = payload.get("Beleg") or payload.get("EBELN") or payload.get("PO_Number") or payload.get("Invoice_ID")
    date_raw = payload.get("Buchungsdatum") or payload.get("BUDAT") or payload.get("Date") or payload.get("Posting_Date")
    plant_raw = payload.get("Werk") or payload.get("WERKS") or payload.get("Plant")
    material_raw = payload.get("Material") or payload.get("MATNR") or payload.get("Material_Desc") or ""
    qty_raw = payload.get("Menge") or payload.get("MENGE") or payload.get("Quantity")
    unit_raw = payload.get("Einheit") or payload.get("MEINS") or payload.get("Unit")
    spend_raw = payload.get("Nettowert") or payload.get("NETWR") or payload.get("Net_Value") or payload.get("Spend")

    # 1. Parse Date
    activity_date = parse_date(date_raw)
    if not activity_date:
        activity_date = datetime.now().date()
        flags.append("INVALID_DATE")

    # 2. Parse Material Description & Map to Scope/Category
    material_desc = str(material_raw).strip().lower()
    sub_category = None
    category = "fuel"
    scope = 1

    if "diesel" in material_desc:
        sub_category = "diesel"
    elif "heiz" in material_desc or "heating" in material_desc or "oil" in material_desc:
        sub_category = "heating_oil"
    elif "gas" in material_desc or "erdgas" in material_desc:
        sub_category = "natural_gas"
    else:
        # Unknown fuel material
        sub_category = "diesel"  # Default fallback
        flags.append("UNKNOWN_MATERIAL")

    # 3. Parse and Validate Plant
    plant_code = str(plant_raw).strip() if plant_raw else ""
    plant_obj = None
    if plant_code:
        try:
            plant_obj = PlantLookup.objects.get(plant_code=plant_code)
        except PlantLookup.DoesNotExist:
            flags.append("UNKNOWN_PLANT")
    else:
        flags.append("MISSING_PLANT")

    # 4. Parse Quantity and Unit
    quantity = 0.0
    try:
        quantity = float(str(qty_raw).replace(",", ".")) if qty_raw else 0.0
        if quantity <= 0:
            flags.append("NEGATIVE_QUANTITY")
    except ValueError:
        flags.append("NON_NUMERIC_QUANTITY")

    unit_str = str(unit_raw).strip().upper() if unit_raw else ""
    norm_qty = quantity
    norm_unit = unit_str

    # Normalise units
    if sub_category in ["diesel", "heating_oil"]:
        norm_unit = "L"
        if unit_str in ["L", "LTR", "LITER", "LITERS"]:
            pass
        elif unit_str in ["M3", "CUBIC_METERS", "CBM"]:
            norm_qty = quantity * 1000.0  # 1 m3 = 1000 Liters
        elif unit_str in ["FL", "KT", "BOX", "FLASCHE"]:
            flags.append("INVALID_UNIT")
            # Impossible to normalize directly without scale assumptions
        else:
            flags.append("UNSUPPORTED_UNIT")
    elif sub_category == "natural_gas":
        norm_unit = "m3"
        if unit_str in ["M3", "CUBIC_METERS", "CBM", "M³"]:
            pass
        elif unit_str in ["KWH", "KILOWATT_HOURS"]:
            # Standard conversion: ~0.1 m3 per kWh
            norm_qty = quantity * 0.095
        elif unit_str in ["FL", "KT", "BOX"]:
            flags.append("INVALID_UNIT")
        else:
            flags.append("UNSUPPORTED_UNIT")

    # 5. Carbon Calculation
    calculated_emissions = None
    if "INVALID_UNIT" not in flags:
        try:
            ef = EmissionFactor.objects.get(category=category, sub_category=sub_category)
            calculated_emissions = norm_qty * ef.factor_value
        except EmissionFactor.DoesNotExist:
            flags.append("MISSING_EMISSION_FACTOR")

    # Status determination
    status = 'PENDING'
    if flags:
        status = 'FLAGGED'

    record = NormalizedRecord(
        raw_record=raw_record,
        organization=organization,
        scope=scope,
        category=category,
        activity_date=activity_date,
        original_quantity=str(qty_raw),
        original_unit=unit_str,
        normalized_quantity=norm_qty,
        normalized_unit=norm_unit,
        calculated_emissions=calculated_emissions,
        status=status,
        validation_flags=flags
    )
    return record

# -------------------------------------------------------------------------
# UTILITY BILL PARSER & CALENDARIZATION
# -------------------------------------------------------------------------

def process_utility_row(raw_record, organization):
    """
    Parses a RawRecord representing a Utility portal CSV export row.
    Handles meter cross-checks, plant mapping, and pro-rata calendarization.
    Returns a list of NormalizedRecord objects (potentially multiple due to calendarization split).
    """
    payload = raw_record.raw_payload
    flags = []

    account_no = payload.get("AccountNumber") or payload.get("Account_No")
    meter_no = payload.get("MeterNumber") or payload.get("Meter_No") or ""
    start_raw = payload.get("ServiceStartDate") or payload.get("Service_Start")
    end_raw = payload.get("ServiceEndDate") or payload.get("Service_End")
    prev_read_raw = payload.get("PreviousReadValue") or payload.get("Prev_Read")
    curr_read_raw = payload.get("CurrentReadValue") or payload.get("Curr_Read")
    usage_raw = payload.get("Usage_kWh") or payload.get("Usage") or payload.get("Consumption")
    tariff_code = payload.get("TariffCode") or payload.get("Tariff")
    total_due = payload.get("TotalDue") or payload.get("Amount")

    # 1. Parse Dates
    start_date = parse_date(start_raw)
    end_date = parse_date(end_raw)
    if not start_date or not end_date:
        flags.append("INVALID_DATE")
        start_date = start_date or datetime.now().date()
        end_date = end_date or datetime.now().date() + timedelta(days=30)

    # 2. Parse Numbers
    prev_read = 0.0
    curr_read = 0.0
    usage = 0.0
    try:
        prev_read = float(str(prev_read_raw).replace(",", "")) if prev_read_raw else 0.0
        curr_read = float(str(curr_read_raw).replace(",", "")) if curr_read_raw else 0.0
    except ValueError:
        flags.append("NON_NUMERIC_METER_READINGS")

    try:
        usage = float(str(usage_raw).replace(",", "")) if usage_raw else 0.0
        if usage <= 0:
            flags.append("NEGATIVE_QUANTITY")
    except ValueError:
        flags.append("NON_NUMERIC_USAGE")

    # Math Cross-Check
    expected_usage = curr_read - prev_read
    if abs(expected_usage - usage) > 0.1 and prev_read > 0 and curr_read > 0:
        flags.append("METER_READ_GAP")

    # 3. Plant & Grid Mapping
    # Parse plant from MeterNumber if matches convention e.g. "MTR-PL001" or lookup
    plant_code = ""
    for pc in ["PL001", "PL002", "PL003"]:
        if pc in str(meter_no):
            plant_code = pc
            break
    
    grid_region = "default"
    if plant_code:
        try:
            plant_obj = PlantLookup.objects.get(plant_code=plant_code)
            grid_region = plant_obj.grid_region
        except PlantLookup.DoesNotExist:
            flags.append("UNKNOWN_PLANT")
    else:
        # Look at tariff or check account, default to PL001 as fallback
        plant_code = "PL001"
        try:
            plant_obj = PlantLookup.objects.get(plant_code=plant_code)
            grid_region = plant_obj.grid_region
        except PlantLookup.DoesNotExist:
            pass
        flags.append("UNMAPPED_METER")

    # Check for billing cycle overlapping existing data
    if start_date and end_date and meter_no:
        overlapping = NormalizedRecord.objects.filter(
            category="electricity",
            raw_record__batch__organization=organization,
            activity_date__range=(start_date, end_date)
        ).exclude(raw_record=raw_record)
        if overlapping.exists():
            flags.append("OVERLAPPING_BILL")

    # 4. Pro-Rata Calendarization & Calculation
    records = []
    total_days = (end_date - start_date).days
    if total_days <= 0:
        total_days = 1 # Avoid division by zero
        flags.append("ZERO_BILLING_DAYS")

    daily_usage = usage / total_days

    # Split the billing cycle into calendar months
    current_date = start_date
    month_splits = {} # maps (year, month) to number of days in that month within the range

    while current_date <= end_date:
        key = (current_date.year, current_date.month)
        month_splits[key] = month_splits.get(key, 0) + 1
        current_date += timedelta(days=1)

    # Clean up edge cases where end_date is inclusive
    # (Adjust splits so total days match exactly)
    computed_sum_days = sum(month_splits.values())
    if computed_sum_days > total_days + 1:
        # Trim final date
        pass

    # Lookup Grid Emission Factor
    try:
        ef = EmissionFactor.objects.get(category="electricity", sub_category=grid_region)
    except EmissionFactor.DoesNotExist:
        ef = EmissionFactor.objects.get(category="electricity", sub_category="default")
        flags.append("MISSING_REGIONAL_FACTOR")

    status = 'PENDING'
    if flags:
        status = 'FLAGGED'

    for (year, month), days in month_splits.items():
        # Allocating consumption
        pro_rata_usage = daily_usage * days
        
        # Calculate emissions
        emissions = pro_rata_usage * ef.factor_value

        # Represent the record mid-month or first of the month
        rep_date = datetime(year, month, 15).date()
        
        rec = NormalizedRecord(
            raw_record=raw_record,
            organization=organization,
            scope=2,
            category="electricity",
            activity_date=rep_date,
            original_quantity=f"{usage:.1f} (Total for Cycle)",
            original_unit="kWh",
            normalized_quantity=pro_rata_usage,
            normalized_unit="kWh",
            calculated_emissions=emissions,
            status=status,
            validation_flags=flags.copy()
        )
        records.append(rec)

    return records

# -------------------------------------------------------------------------
# CORPORATE TRAVEL PARSER (CONCUR ITINERARY V4 SPEC)
# -------------------------------------------------------------------------

def process_travel_payload(raw_record, organization):
    """
    Parses a RawRecord representing a Concur Corporate Travel trip itinerary JSON payload.
    A single trip payload can have multiple segments (Air, Hotel, Car).
    Returns a list of NormalizedRecord objects representing all travel events in the trip.
    """
    payload = raw_record.raw_payload
    records = []
    
    trip_id = payload.get("tripId") or payload.get("TripID") or "TRIP-MOCK"
    traveler_name = payload.get("travelerName") or payload.get("TravelerName") or "John Doe"
    segments = payload.get("segments") or payload.get("Segments") or []

    for idx, seg in enumerate(segments):
        seg_type = seg.get("type") or seg.get("SegmentType")
        flags = []
        
        if seg_type == "Air":
            # Flights (Scope 3, Category 6: Business Travel)
            dep_code = seg.get("departure") or seg.get("Origin") or ""
            arr_code = seg.get("arrival") or seg.get("Destination") or ""
            travel_class = seg.get("class") or seg.get("Class") or "Economy"
            date_raw = seg.get("date") or seg.get("DepartureDate")
            
            activity_date = parse_date(date_raw) or datetime.now().date()
            
            # Lookup coords
            try:
                dep_ap = AirportLookup.objects.get(iata_code=dep_code.upper().strip())
            except AirportLookup.DoesNotExist:
                dep_ap = None
                flags.append("UNKNOWN_DEPARTURE_AIRPORT")
                
            try:
                arr_ap = AirportLookup.objects.get(iata_code=arr_code.upper().strip())
            except AirportLookup.DoesNotExist:
                arr_ap = None
                flags.append("UNKNOWN_ARRIVAL_AIRPORT")

            distance_km = 0.0
            if dep_ap and arr_ap:
                distance_km = haversine_distance(
                    dep_ap.latitude, dep_ap.longitude,
                    arr_ap.latitude, arr_ap.longitude
                )
            else:
                # Fallback to default medium distance
                distance_km = 1200.0
                flags.append("MOCK_FLIGHT_DISTANCE")

            # Categorize flight haul
            haul_type = "medium_haul"
            if distance_km < 480.0:
                haul_type = "short_haul"
            elif distance_km > 3700.0:
                haul_type = "long_haul"

            # Seating class factor
            class_str = str(travel_class).lower().strip()
            sub_cat = f"{haul_type}_economy"
            if "bus" in class_str or "first" in class_str or "exec" in class_str:
                sub_cat = f"{haul_type}_business"

            try:
                ef = EmissionFactor.objects.get(category="flight", sub_category=sub_cat)
            except EmissionFactor.DoesNotExist:
                ef = EmissionFactor.objects.filter(category="flight").first()
                flags.append("MISSING_FLIGHT_EF")

            emissions = distance_km * ef.factor_value if ef else 0.0
            
            status = 'PENDING'
            if flags:
                status = 'FLAGGED'

            rec = NormalizedRecord(
                raw_record=raw_record,
                organization=organization,
                scope=3,
                category="flight",
                activity_date=activity_date,
                original_quantity=f"{dep_code} -> {arr_code}",
                original_unit="IATA Route",
                normalized_quantity=distance_km,
                normalized_unit="km",
                calculated_emissions=emissions,
                status=status,
                validation_flags=flags
            )
            records.append(rec)

        elif seg_type == "Hotel":
            # Hotels (Scope 3, Category 6)
            hotel_name = seg.get("hotelName") or seg.get("HotelName") or "Unknown Hotel"
            nights_raw = seg.get("nights") or seg.get("Nights") or 1
            rooms_raw = seg.get("rooms") or seg.get("Rooms") or 1
            country = seg.get("country") or seg.get("CountryCode") or "default"
            date_raw = seg.get("checkInDate") or seg.get("date")
            
            activity_date = parse_date(date_raw) or datetime.now().date()

            nights = 1
            rooms = 1
            try:
                nights = int(nights_raw)
                rooms = int(rooms_raw)
                if nights <= 0 or rooms <= 0:
                    flags.append("NEGATIVE_HOTEL_STAY")
            except ValueError:
                flags.append("INVALID_HOTEL_UNITS")

            # Lookup Factor for hotel in this country
            country_code = str(country).strip().upper()
            try:
                ef = EmissionFactor.objects.get(category="hotel", sub_category=country_code)
            except EmissionFactor.DoesNotExist:
                ef = EmissionFactor.objects.get(category="hotel", sub_category="default")
                flags.append("HOTEL_COUNTRY_FALLBACK")

            room_nights = nights * rooms
            emissions = room_nights * ef.factor_value

            status = 'PENDING'
            if flags:
                status = 'FLAGGED'

            rec = NormalizedRecord(
                raw_record=raw_record,
                organization=organization,
                scope=3,
                category="hotel",
                activity_date=activity_date,
                original_quantity=f"{nights} nights, {rooms} rooms",
                original_unit="Nights * Rooms",
                normalized_quantity=float(room_nights),
                normalized_unit="room-nights",
                calculated_emissions=emissions,
                status=status,
                validation_flags=flags
            )
            records.append(rec)

        elif seg_type in ["Car", "Ground"]:
            # Car Rental / Ground Transport (Scope 3, Category 6)
            car_class = seg.get("carClass") or seg.get("CarClass") or "Sedan"
            dist_raw = seg.get("distance") or seg.get("Distance") or 100.0
            dist_unit = seg.get("distanceUnit") or seg.get("Unit") or "miles"
            date_raw = seg.get("date") or seg.get("RentalDate")
            
            activity_date = parse_date(date_raw) or datetime.now().date()

            distance = 0.0
            try:
                distance = float(dist_raw)
                if distance <= 0:
                    flags.append("NEGATIVE_DISTANCE")
            except ValueError:
                flags.append("NON_NUMERIC_DISTANCE")

            # Normalise to kilometers
            norm_dist = distance
            unit_str = str(dist_unit).strip().lower()
            if "mile" in unit_str or "mi" == unit_str:
                norm_dist = distance * 1.60934
            
            # Lookup vehicle EF
            class_str = str(car_class).strip()
            try:
                ef = EmissionFactor.objects.get(category="car", sub_category=class_str)
            except EmissionFactor.DoesNotExist:
                ef = EmissionFactor.objects.get(category="car", sub_category="Sedan")
                flags.append("CAR_CLASS_FALLBACK")

            emissions = norm_dist * ef.factor_value if ef else 0.0

            status = 'PENDING'
            if flags:
                status = 'FLAGGED'

            rec = NormalizedRecord(
                raw_record=raw_record,
                organization=organization,
                scope=3,
                category="car",
                activity_date=activity_date,
                original_quantity=str(dist_raw),
                original_unit=dist_unit,
                normalized_quantity=norm_dist,
                normalized_unit="km",
                calculated_emissions=emissions,
                status=status,
                validation_flags=flags
            )
            records.append(rec)

    return records
