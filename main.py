from machine import ADC, Pin, PWM, time_pulse_us
import dht
import time

try:
    import neopixel
except ImportError:
    neopixel = None

# Smart Waste Bin - Ultra Advanced Wokwi Simulation
# Simulates a production-style IoT edge node without requiring WiFi credentials.

DEVICE_ID = "SWBIN-BEY-001"
FIRMWARE_VERSION = "4.0.0-edge-platform"
LOCATION = "Beirut Campus - Block A"
FLEET_ID = "BEY-SMART-WASTE-FLEET"
GEOHASH = "svc4r8"
ROUTE_ZONE = "A1"

TRIG_PIN = 5
ECHO_PIN = 18
PIR_PIN = 19
SERVO_PIN = 21
COMPACTOR_SERVO_PIN = 32
BUZZER_PIN = 22
NEOPIXEL_PIN = 13
NEOPIXEL_COUNT = 16
GREEN_LED_PIN = 25
YELLOW_LED_PIN = 26
RED_LED_PIN = 27
BUTTON_PIN = 14
DHT_PIN = 23
BATTERY_ADC_PIN = 34
GAS_ADC_PIN = 35

EMPTY_DISTANCE_CM = 100.0
FULL_DISTANCE_CM = 8.0
BIN_VOLUME_LITERS = 120.0
TRUCK_CAPACITY_LITERS = 2400.0

READINGS_PER_CYCLE = 9
READ_INTERVAL_MS = 45
LOOP_INTERVAL_NORMAL_MS = 900
LOOP_INTERVAL_LOW_POWER_MS = 2200
DHT_INTERVAL_MS = 6000
CLOUD_INTERVAL_MS = 5000
FULL_ALERT_DELAY_MS = 10000
LID_OPEN_MS = 3000
LONG_PRESS_MS = 1800
STUCK_SENSOR_WINDOW = 10
COMPACTION_MIN_INTERVAL_MS = 20000
QUEUE_MAX_DEPTH = 12
SANITATION_REVIEW_MIN = 180

STATUS_THRESHOLDS = {
    "OK": 0,
    "WATCH": 40,
    "MONITOR": 55,
    "COLLECT": 75,
    "CRITICAL": 90,
    "OVERFLOW": 97,
}

STATUS_ORDER = ("OK", "WATCH", "MONITOR", "COLLECT", "CRITICAL", "OVERFLOW")
STATUS_HYSTERESIS = 3.0

trigger = Pin(TRIG_PIN, Pin.OUT)
echo = Pin(ECHO_PIN, Pin.IN)
pir = Pin(PIR_PIN, Pin.IN)
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)
dht_sensor = dht.DHT22(Pin(DHT_PIN))

green_led = Pin(GREEN_LED_PIN, Pin.OUT)
yellow_led = Pin(YELLOW_LED_PIN, Pin.OUT)
red_led = Pin(RED_LED_PIN, Pin.OUT)

buzzer = PWM(Pin(BUZZER_PIN))
buzzer.duty(0)

servo = PWM(Pin(SERVO_PIN), freq=50)
compactor_servo = PWM(Pin(COMPACTOR_SERVO_PIN), freq=50)

if neopixel:
    status_pixels = neopixel.NeoPixel(Pin(NEOPIXEL_PIN), NEOPIXEL_COUNT)
else:
    status_pixels = None

battery_adc = ADC(Pin(BATTERY_ADC_PIN))
gas_adc = ADC(Pin(GAS_ADC_PIN))
for adc in (battery_adc, gas_adc):
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass


def now_ms():
    return time.ticks_ms()


def elapsed_ms(start_ms):
    return time.ticks_diff(now_ms(), start_ms)


def clamp(value, low, high):
    return max(low, min(high, value))


def monotonic_seconds():
    return now_ms() // 1000


def set_servo_angle(angle):
    duty = int(26 + (clamp(angle, 0, 180) / 180) * 102)
    servo.duty(duty)


def close_lid():
    set_servo_angle(0)


def open_lid():
    set_servo_angle(95)


def set_compactor_angle(angle):
    duty = int(26 + (clamp(angle, 0, 180) / 180) * 102)
    compactor_servo.duty(duty)


def rest_compactor():
    set_compactor_angle(20)


def pulse_compactor():
    set_compactor_angle(135)
    time.sleep_ms(350)
    set_compactor_angle(20)


def beep(frequency=800, duration_ms=80, duty=256):
    buzzer.freq(frequency)
    buzzer.duty(duty)
    time.sleep_ms(duration_ms)
    buzzer.duty(0)


def read_distance_once():
    trigger.value(0)
    time.sleep_us(2)
    trigger.value(1)
    time.sleep_us(10)
    trigger.value(0)

    duration = time_pulse_us(echo, 1, 30000)
    if duration < 0:
        return None

    distance = duration / 58.0
    if distance < 2 or distance > 400:
        return None
    return distance


def robust_distance_read():
    samples = []
    for _ in range(READINGS_PER_CYCLE):
        value = read_distance_once()
        if value is not None:
            samples.append(value)
        time.sleep_ms(READ_INTERVAL_MS)

    if not samples:
        return None, 0, 0, "NO_ECHO"

    samples.sort()
    if len(samples) >= 5:
        trimmed = samples[1:-1]
    else:
        trimmed = samples

    average = sum(trimmed) / len(trimmed)
    spread = samples[-1] - samples[0]
    quality = int(clamp(100 - (spread * 4) - ((READINGS_PER_CYCLE - len(samples)) * 12), 0, 100))

    if quality < 45:
        quality_label = "NOISY"
    elif len(samples) < READINGS_PER_CYCLE:
        quality_label = "PARTIAL"
    else:
        quality_label = "GOOD"

    return average, len(samples), quality, quality_label


def calculate_fill_level(distance_cm):
    usable_depth = EMPTY_DISTANCE_CM - FULL_DISTANCE_CM
    fill = ((EMPTY_DISTANCE_CM - distance_cm) / usable_depth) * 100
    return round(clamp(fill, 0, 100), 1)


def status_index(status):
    return STATUS_ORDER.index(status)


def status_from_fill(fill_level, current_status):
    candidate = "OK"
    for status in STATUS_ORDER:
        if fill_level >= STATUS_THRESHOLDS[status]:
            candidate = status

    if candidate == current_status:
        return current_status

    if status_index(candidate) > status_index(current_status):
        return candidate

    current_floor = STATUS_THRESHOLDS[current_status]
    if fill_level <= current_floor - STATUS_HYSTERESIS:
        return candidate
    return current_status


def read_adc_percent(adc):
    try:
        raw = adc.read()
    except Exception:
        return None, None
    return raw, round((raw / 4095) * 100, 1)


def status_color(status):
    colors = {
        "OK": (0, 50, 8),
        "WATCH": (30, 45, 0),
        "MONITOR": (60, 30, 0),
        "COLLECT": (70, 16, 0),
        "CRITICAL": (80, 0, 0),
        "OVERFLOW": (70, 0, 45),
    }
    return colors.get(status, (15, 15, 15))


def render_pixel_ring(status, fill_level, risk, maintenance_mode, anomalies):
    if not status_pixels:
        return

    lit_pixels = int(round((fill_level / 100) * NEOPIXEL_COUNT))
    base_color = status_color(status)

    if maintenance_mode:
        base_color = (15, 15, 40)
    elif anomalies:
        base_color = (65, 0, 35)

    for index in range(NEOPIXEL_COUNT):
        if index < lit_pixels:
            status_pixels[index] = base_color
        else:
            status_pixels[index] = (0, 0, 0)

    if risk >= 85:
        status_pixels[0] = (90, 0, 0)
        status_pixels[NEOPIXEL_COUNT // 2] = (90, 0, 0)

    status_pixels.write()


def read_environment(last_env, last_read_at):
    if elapsed_ms(last_read_at) < DHT_INTERVAL_MS:
        return last_env, last_read_at

    try:
        dht_sensor.measure()
        env = {
            "temp_c": round(dht_sensor.temperature(), 1),
            "humidity": round(dht_sensor.humidity(), 1),
            "ok": True,
        }
    except Exception:
        env = {
            "temp_c": last_env["temp_c"],
            "humidity": last_env["humidity"],
            "ok": False,
        }
    return env, now_ms()


def get_trend(history):
    if len(history) < 4:
        return "STABLE"

    change = history[-1][1] - history[0][1]
    minutes = max(1 / 60, (history[-1][0] - history[0][0]) / 60000)
    rate = change / minutes

    if rate >= 18:
        return "SURGE"
    if rate >= 6:
        return "FILLING_FAST"
    if rate >= 1.5:
        return "FILLING"
    if rate <= -8:
        return "EMPTYING"
    return "STABLE"


def fill_rate_percent_per_min(history):
    if len(history) < 2:
        return 0.0
    delta_fill = history[-1][1] - history[0][1]
    delta_min = max(1 / 60, (history[-1][0] - history[0][0]) / 60000)
    return round(delta_fill / delta_min, 2)


def eta_to_threshold(fill_level, rate_per_min, threshold):
    if rate_per_min <= 0 or fill_level >= threshold:
        return 0 if fill_level >= threshold else None
    return round((threshold - fill_level) / rate_per_min, 1)


def estimate_remaining_liters(fill_level):
    return round(BIN_VOLUME_LITERS * (100 - fill_level) / 100, 1)


def estimate_waste_liters(fill_level):
    return round(BIN_VOLUME_LITERS * fill_level / 100, 1)


def collection_age_min(last_collection_at):
    return round(max(0, elapsed_ms(last_collection_at)) / 60000, 1)


def sanitation_risk(gas_percent, env, collection_age):
    score = 0
    score += (gas_percent or 0) * 0.55
    score += max(0, (env["temp_c"] or 22) - 28) * 1.8
    score += max(0, (env["humidity"] or 50) - 65) * 0.45
    score += min(collection_age, SANITATION_REVIEW_MIN) * 0.08
    return round(clamp(score, 0, 100), 1)


def risk_score(fill_level, gas_percent, env, trend, battery_percent, sensor_quality):
    score = fill_level * 0.52
    score += (gas_percent or 0) * 0.22
    score += max(0, (env["temp_c"] or 22) - 30) * 1.5
    score += max(0, (env["humidity"] or 50) - 70) * 0.35
    score += max(0, 45 - (battery_percent or 100)) * 0.45
    score += max(0, 60 - sensor_quality) * 0.35
    if trend == "SURGE":
        score += 16
    elif trend == "FILLING_FAST":
        score += 9
    return round(clamp(score, 0, 100), 1)


def health_score(sensor_quality, battery_percent, anomalies, collection_count, compaction_count):
    score = sensor_quality * 0.45
    score += (battery_percent if battery_percent is not None else 100) * 0.25
    score += max(0, 100 - (len(anomalies) * 18)) * 0.2
    score += max(0, 100 - ((collection_count + compaction_count) * 0.8)) * 0.1
    return round(clamp(score, 0, 100), 1)


def confidence_score(sample_count, quality, anomalies, env_ok):
    score = quality
    score -= max(0, READINGS_PER_CYCLE - sample_count) * 8
    score -= len(anomalies) * 10
    if not env_ok:
        score -= 6
    return round(clamp(score, 0, 100), 1)


def carbon_score(priority, eta_collect_min, remaining_liters):
    base = {
        "P0_IMMEDIATE": 96,
        "P1_NEXT_TRUCK": 80,
        "P2_TODAY": 62,
        "P3_WATCHLIST": 38,
        "P4_NORMAL": 18,
    }[priority]
    if eta_collect_min is not None and eta_collect_min <= 10:
        base += 8
    if remaining_liters < 15:
        base += 7
    return round(clamp(base, 0, 100), 1)


def sla_state(priority, eta_overflow_min):
    if priority == "P0_IMMEDIATE":
        return "BREACH_RISK"
    if eta_overflow_min is not None and eta_overflow_min <= 30:
        return "DUE_30_MIN"
    if priority in ("P1_NEXT_TRUCK", "P2_TODAY"):
        return "DUE_TODAY"
    return "ON_TRACK"


def service_window(priority, eta_collect_min, sanitation_score, collection_age):
    if priority == "P0_IMMEDIATE" or sanitation_score >= 90:
        return "NOW"
    if eta_collect_min is not None and eta_collect_min <= 30:
        return "NEXT_30_MIN"
    if priority in ("P1_NEXT_TRUCK", "P2_TODAY") or sanitation_score >= 70:
        return "TODAY"
    if collection_age >= SANITATION_REVIEW_MIN:
        return "SANITATION_REVIEW"
    return "NORMAL_ROUTE"


def route_load_percent(waste_liters):
    return round(clamp((waste_liters / TRUCK_CAPACITY_LITERS) * 100, 0, 100), 1)


def pickup_batch(priority, load_percent, queue_depth, confidence):
    if priority == "P0_IMMEDIATE":
        return "EXPEDITE"
    if queue_depth >= QUEUE_MAX_DEPTH:
        return "RECOVER_OFFLINE"
    if confidence < 50:
        return "VERIFY_FIRST"
    if load_percent >= 4:
        return "BATCH_WITH_ZONE"
    return "DEFER_UNTIL_ROUTE"


def compaction_decision(fill_level, gas_percent, status, anomalies, last_compaction_at):
    if status not in ("COLLECT", "CRITICAL") or fill_level < 82:
        return "SKIP"
    if gas_percent is not None and gas_percent >= 75:
        return "LOCKOUT_GAS"
    if anomalies:
        return "LOCKOUT_ANOMALY"
    if elapsed_ms(last_compaction_at) < COMPACTION_MIN_INTERVAL_MS:
        return "COOLDOWN"
    return "RUN"


def edge_action(priority, status, anomalies, compaction_action):
    if "ODOR_GAS_HIGH" in anomalies:
        return "VENTILATION_INSPECTION"
    if compaction_action == "RUN":
        return "LOCAL_COMPACTION"
    if priority == "P0_IMMEDIATE":
        return "DISPATCH_NOW"
    if status in ("CRITICAL", "OVERFLOW"):
        return "ESCALATE_ROUTE"
    if anomalies:
        return "MAINTENANCE_TICKET"
    return "TELEMETRY_ONLY"


def route_priority(status, score, eta_collect_min):
    if status == "OVERFLOW" or score >= 88:
        return "P0_IMMEDIATE"
    if status == "CRITICAL" or score >= 75:
        return "P1_NEXT_TRUCK"
    if status == "COLLECT" or (eta_collect_min is not None and eta_collect_min <= 20):
        return "P2_TODAY"
    if status == "MONITOR":
        return "P3_WATCHLIST"
    return "P4_NORMAL"


def packet_checksum(text):
    checksum = 0
    for char in text:
        checksum = ((checksum << 5) - checksum + ord(char)) & 0xFFFF
    return checksum


def queue_depth_after_publish(queue_depth, should_publish, ack_ok):
    if not should_publish:
        return queue_depth
    if ack_ok:
        return max(0, queue_depth - 1)
    return min(QUEUE_MAX_DEPTH, queue_depth + 1)


def cloud_ack_ok(battery_percent, gas_percent, risk):
    if battery_percent is not None and battery_percent < 10:
        return False
    if gas_percent is not None and gas_percent > 94:
        return False
    return risk < 99


def detect_anomalies(fill_history, distance_cm, gas_percent, battery_percent, quality_label):
    issues = []

    if quality_label in ("NOISY", "NO_ECHO"):
        issues.append("ULTRASONIC_QUALITY")

    if len(fill_history) >= 2:
        jump = abs(fill_history[-1][1] - fill_history[-2][1])
        if jump >= 35:
            issues.append("IMPOSSIBLE_FILL_JUMP")

    if len(fill_history) >= STUCK_SENSOR_WINDOW:
        recent = [point[1] for point in fill_history[-STUCK_SENSOR_WINDOW:]]
        if max(recent) - min(recent) <= 0.2 and distance_cm < EMPTY_DISTANCE_CM - 5:
            issues.append("POSSIBLE_SENSOR_STUCK")

    if gas_percent is not None and gas_percent >= 82:
        issues.append("ODOR_GAS_HIGH")

    if battery_percent is not None and battery_percent <= 18:
        issues.append("BATTERY_LOW")

    return issues


def set_status_leds(status, maintenance_mode):
    if maintenance_mode:
        green_led.value(1)
        yellow_led.value(1)
        red_led.value(1)
        return

    green_led.value(status in ("OK", "WATCH"))
    yellow_led.value(status in ("MONITOR", "COLLECT"))
    red_led.value(status in ("CRITICAL", "OVERFLOW"))


def alert_for_status(status, anomalies):
    if "ODOR_GAS_HIGH" in anomalies:
        beep(1100, 90)
        time.sleep_ms(60)
        beep(1100, 90)
        return

    patterns = {
        "WATCH": (1, 430, 50),
        "MONITOR": (1, 560, 70),
        "COLLECT": (2, 720, 90),
        "CRITICAL": (3, 900, 120),
        "OVERFLOW": (4, 1050, 140),
    }
    if status not in patterns:
        return

    pulses, frequency, duration = patterns[status]
    for _ in range(pulses):
        beep(frequency, duration)
        time.sleep_ms(70)


def button_is_pressed():
    return button.value() == 0


def add_event(event_log, event_type, details):
    event = {
        "ts": monotonic_seconds(),
        "type": event_type,
        "details": details,
    }
    event_log.append(event)
    if len(event_log) > 8:
        event_log.pop(0)
    print('{{"event":"{}","ts":{},"details":"{}"}}'.format(event_type, event["ts"], details))


def print_boot():
    print("Smart Waste Bin Edge Platform Simulator")
    print("---------------------------------------")
    print("Device: {} | Firmware: {}".format(DEVICE_ID, FIRMWARE_VERSION))
    print("Location: {}".format(LOCATION))
    print("Fleet: {} | Geohash: {} | Route zone: {}".format(FLEET_ID, GEOHASH, ROUTE_ZONE))
    print("Serial output includes cloud-ready telemetry, edge actions, and digital twin state.")


def print_telemetry(payload):
    print(
        '{{"device":"{}","fleet":"{}","fw":"{}","location":"{}","geohash":"{}","uptime_s":{},'
        '"distance_cm":{:.1f},"fill_percent":{:.1f},"remaining_liters":{:.1f},'
        '"status":"{}","trend":"{}","fill_rate_pct_min":{:.2f},'
        '"eta_collect_min":{},"eta_overflow_min":{},"risk_score":{:.1f},'
        '"health_score":{:.1f},"confidence_score":{:.1f},"carbon_score":{:.1f},'
        '"sanitation_score":{:.1f},"collection_age_min":{:.1f},'
        '"waste_liters":{:.1f},"truck_load_percent":{:.1f},'
        '"route_priority":"{}","sla":"{}","edge_action":"{}","compaction":"{}",'
        '"route_zone":"{}","service_window":"{}","pickup_batch":"{}",'
        '"samples":{},"quality":{},"quality_label":"{}",'
        '"lid":"{}","alert":"{}","battery_percent":{},"battery_raw":{},'
        '"gas_percent":{},"gas_raw":{},"temp_c":{},"humidity":{},'
        '"maintenance":{},"collections":{},"compactions":{},"queue_depth":{},'
        '"cloud_ack":{},"anomalies":"{}","twin":"{}","cloud_seq":{},"checksum":{}}}'.format(
            DEVICE_ID,
            FLEET_ID,
            FIRMWARE_VERSION,
            LOCATION,
            GEOHASH,
            payload["uptime_s"],
            payload["distance_cm"],
            payload["fill_percent"],
            payload["remaining_liters"],
            payload["status"],
            payload["trend"],
            payload["fill_rate"],
            payload["eta_collect"],
            payload["eta_overflow"],
            payload["risk"],
            payload["health"],
            payload["confidence"],
            payload["carbon"],
            payload["sanitation"],
            payload["collection_age"],
            payload["waste_liters"],
            payload["truck_load"],
            payload["priority"],
            payload["sla"],
            payload["edge_action"],
            payload["compaction"],
            ROUTE_ZONE,
            payload["service_window"],
            payload["pickup_batch"],
            payload["samples"],
            payload["quality"],
            payload["quality_label"],
            payload["lid"],
            payload["alert"],
            payload["battery_percent"],
            payload["battery_raw"],
            payload["gas_percent"],
            payload["gas_raw"],
            payload["temp_c"],
            payload["humidity"],
            str(payload["maintenance"]).lower(),
            payload["collections"],
            payload["compactions"],
            payload["queue_depth"],
            str(payload["cloud_ack"]).lower(),
            payload["anomalies"],
            payload["twin"],
            payload["cloud_seq"],
            payload["checksum"],
        )
    )


fill_history = []
event_log = []
lid_opened_at = None
urgent_started_at = None
last_alert_at = 0
last_cloud_at = 0
last_button_down_at = None
last_env_read_at = -DHT_INTERVAL_MS
collection_count = 0
compaction_count = 0
cloud_sequence = 0
offline_queue_depth = 0
maintenance_mode = False
current_status = "OK"
last_status = "OK"
last_env = {"temp_c": 22.0, "humidity": 45.0, "ok": False}
last_compaction_at = -COMPACTION_MIN_INTERVAL_MS
last_collection_at = now_ms()

close_lid()
rest_compactor()
print_boot()
add_event(event_log, "boot", "node_online")

while True:
    if button_is_pressed() and last_button_down_at is None:
        last_button_down_at = now_ms()

    if not button_is_pressed() and last_button_down_at is not None:
        press_ms = elapsed_ms(last_button_down_at)
        last_button_down_at = None

        if press_ms >= LONG_PRESS_MS:
            maintenance_mode = not maintenance_mode
            add_event(event_log, "maintenance_mode", "enabled" if maintenance_mode else "disabled")
            beep(1300, 90)
            time.sleep_ms(80)
            beep(900, 90)
        else:
            collection_count += 1
            fill_history = []
            urgent_started_at = None
            current_status = "OK"
            last_collection_at = now_ms()
            close_lid()
            add_event(event_log, "collection_reset", "manual_collection")
            beep(1200, 120)

    if pir.value() == 1 and lid_opened_at is None and not maintenance_mode:
        open_lid()
        lid_opened_at = now_ms()
        add_event(event_log, "lid_opened", "pir_motion")

    if lid_opened_at is not None and elapsed_ms(lid_opened_at) >= LID_OPEN_MS:
        close_lid()
        lid_opened_at = None
        add_event(event_log, "lid_closed", "timeout")

    distance, sample_count, quality, quality_label = robust_distance_read()
    if distance is None:
        red_led.value(1)
        yellow_led.value(0)
        green_led.value(0)
        beep(300, 60)
        add_event(event_log, "sensor_fault", "ultrasonic_timeout")
        time.sleep_ms(LOOP_INTERVAL_NORMAL_MS)
        continue

    last_env, last_env_read_at = read_environment(last_env, last_env_read_at)
    battery_raw, battery_percent = read_adc_percent(battery_adc)
    gas_raw, gas_percent = read_adc_percent(gas_adc)

    fill_level = calculate_fill_level(distance)
    fill_history.append((now_ms(), fill_level))
    if len(fill_history) > 18:
        fill_history.pop(0)

    current_status = status_from_fill(fill_level, current_status)
    trend = get_trend(fill_history)
    fill_rate = fill_rate_percent_per_min(fill_history)
    eta_collect = eta_to_threshold(fill_level, fill_rate, STATUS_THRESHOLDS["COLLECT"])
    eta_overflow = eta_to_threshold(fill_level, fill_rate, STATUS_THRESHOLDS["OVERFLOW"])
    anomalies = detect_anomalies(fill_history, distance, gas_percent, battery_percent, quality_label)
    risk = risk_score(fill_level, gas_percent, last_env, trend, battery_percent, quality)
    priority = route_priority(current_status, risk, eta_collect)
    remaining_liters = estimate_remaining_liters(fill_level)
    waste_liters = estimate_waste_liters(fill_level)
    collection_age = collection_age_min(last_collection_at)
    sanitation = sanitation_risk(gas_percent, last_env, collection_age)
    health = health_score(quality, battery_percent, anomalies, collection_count, compaction_count)
    confidence = confidence_score(sample_count, quality, anomalies, last_env["ok"])
    carbon = carbon_score(priority, eta_collect, remaining_liters)
    sla = sla_state(priority, eta_overflow)
    window = service_window(priority, eta_collect, sanitation, collection_age)
    truck_load = route_load_percent(waste_liters)
    compaction_action = compaction_decision(fill_level, gas_percent, current_status, anomalies, last_compaction_at)
    action = edge_action(priority, current_status, anomalies, compaction_action)

    if compaction_action == "RUN" and not maintenance_mode:
        pulse_compactor()
        compaction_count += 1
        last_compaction_at = now_ms()
        add_event(event_log, "compaction", "cycle_{}".format(compaction_count))

    status_changed = current_status != last_status
    if status_changed:
        add_event(event_log, "status_change", "{}_to_{}".format(last_status, current_status))
        last_status = current_status

    set_status_leds(current_status, maintenance_mode)
    render_pixel_ring(current_status, fill_level, risk, maintenance_mode, anomalies)

    if current_status in ("CRITICAL", "OVERFLOW"):
        if urgent_started_at is None:
            urgent_started_at = now_ms()
        alert_state = "OVERFLOW_RISK" if elapsed_ms(urgent_started_at) >= FULL_ALERT_DELAY_MS else "FULL"
    elif anomalies:
        urgent_started_at = None
        alert_state = "ANOMALY"
    else:
        urgent_started_at = None
        alert_state = "NORMAL"

    if (current_status != "OK" or anomalies) and elapsed_ms(last_alert_at) >= 5000 and not maintenance_mode:
        alert_for_status(current_status, anomalies)
        last_alert_at = now_ms()

    low_power = battery_percent is not None and battery_percent < 18
    should_publish = elapsed_ms(last_cloud_at) >= CLOUD_INTERVAL_MS or status_changed or anomalies
    ack_ok = cloud_ack_ok(battery_percent, gas_percent, risk)
    if should_publish:
        cloud_sequence += 1
        last_cloud_at = now_ms()
        offline_queue_depth = queue_depth_after_publish(offline_queue_depth, should_publish, ack_ok)

    pickup = pickup_batch(priority, truck_load, offline_queue_depth, confidence)
    twin_state = "{}:{}:{}L:{}Q:{}".format(current_status, priority, remaining_liters, offline_queue_depth, window)
    checksum_text = "{}:{}:{}:{}:{}:{}:{}".format(
        DEVICE_ID,
        cloud_sequence,
        fill_level,
        risk,
        priority,
        window,
        ",".join(anomalies) if anomalies else "none",
    )

    payload = {
        "uptime_s": monotonic_seconds(),
        "distance_cm": distance,
        "fill_percent": fill_level,
        "remaining_liters": remaining_liters,
        "waste_liters": waste_liters,
        "status": current_status,
        "trend": trend,
        "fill_rate": fill_rate,
        "eta_collect": "null" if eta_collect is None else eta_collect,
        "eta_overflow": "null" if eta_overflow is None else eta_overflow,
        "risk": risk,
        "health": health,
        "confidence": confidence,
        "carbon": carbon,
        "sanitation": sanitation,
        "collection_age": collection_age,
        "truck_load": truck_load,
        "priority": priority,
        "sla": sla,
        "service_window": window,
        "pickup_batch": pickup,
        "edge_action": action,
        "compaction": compaction_action,
        "samples": sample_count,
        "quality": quality,
        "quality_label": quality_label,
        "lid": "OPEN" if lid_opened_at is not None else "CLOSED",
        "alert": alert_state,
        "battery_percent": "null" if battery_percent is None else battery_percent,
        "battery_raw": "null" if battery_raw is None else battery_raw,
        "gas_percent": "null" if gas_percent is None else gas_percent,
        "gas_raw": "null" if gas_raw is None else gas_raw,
        "temp_c": "null" if last_env["temp_c"] is None else last_env["temp_c"],
        "humidity": "null" if last_env["humidity"] is None else last_env["humidity"],
        "maintenance": maintenance_mode,
        "collections": collection_count,
        "compactions": compaction_count,
        "queue_depth": offline_queue_depth,
        "cloud_ack": ack_ok,
        "anomalies": ",".join(anomalies) if anomalies else "none",
        "twin": twin_state,
        "cloud_seq": cloud_sequence,
        "checksum": packet_checksum(checksum_text),
    }
    print_telemetry(payload)

    if low_power:
        add_event(event_log, "power_mode", "low_power")
        time.sleep_ms(LOOP_INTERVAL_LOW_POWER_MS)
    else:
        time.sleep_ms(LOOP_INTERVAL_NORMAL_MS)
