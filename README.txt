SMART WASTE IOT SIMULATION

An ESP32-based smart waste bin simulation built for Wokwi using MicroPython.
The project demonstrates embedded sensing, local decision-making, actuator
control, operational telemetry, and fleet-style collection prioritization.


PROJECT OVERVIEW

The simulated node estimates bin fill level using an HC-SR04 ultrasonic sensor
and combines that reading with motion, temperature, humidity, battery, and
odor-risk inputs. The firmware produces structured telemetry that can be used
for dashboard, cloud ingestion, or IoT architecture demonstrations.

The simulation is designed to represent a realistic edge-IoT workflow:
- Sense bin fill level and operating conditions
- Filter and validate sensor data
- Classify bin state using threshold and hysteresis logic
- Predict collection urgency
- Trigger local indicators and actuators
- Emit cloud-ready serial telemetry


HARDWARE COMPONENTS

- ESP32 DevKit V4
- HC-SR04 ultrasonic sensor for fill-level measurement
- PIR motion sensor for automatic lid activation
- Servo motor for lid movement
- Servo motor for simulated compactor movement
- 16-pixel NeoPixel ring for fill and risk visualization
- Green, yellow, and red status LEDs
- Buzzer for alert patterns
- Pushbutton for collection reset and maintenance mode
- DHT22 temperature and humidity sensor
- Potentiometer for simulated battery level
- Potentiometer for simulated odor or gas risk


PIN MAP

| Component | Signal | ESP32 Pin |
| --- | --- | --- |
| HC-SR04 | TRIG | GPIO 5 |
| HC-SR04 | ECHO | GPIO 18 |
| PIR sensor | OUT | GPIO 19 |
| Lid servo | PWM | GPIO 21 |
| Compactor servo | PWM | GPIO 32 |
| Buzzer | Signal | GPIO 22 |
| NeoPixel ring | DIN | GPIO 13 |
| Green LED | Anode | GPIO 25 |
| Yellow LED | Anode | GPIO 26 |
| Red LED | Anode | GPIO 27 |
| Pushbutton | Signal | GPIO 14 |
| DHT22 | Data | GPIO 23 |
| Battery potentiometer | Analog | GPIO 34 |
| Odor/gas potentiometer | Analog | GPIO 35 |


CORE FEATURES

- Robust ultrasonic sampling with trimmed averaging
- Sensor quality scoring
- Fill-level calculation calibrated from 100 cm empty to 8 cm full
- Status classification with hysteresis to reduce noisy state changes
- Remaining capacity estimate in liters
- Waste volume and estimated truck-load contribution
- Fill-rate calculation in percent per minute
- Trend detection: STABLE, FILLING, FILLING_FAST, SURGE, EMPTYING
- ETA prediction for collection and overflow thresholds
- Risk score based on fill level, odor/gas, temperature, humidity, battery,
  trend, and sensor quality
- Sanitation risk score based on odor/gas, environment, and time since the
  last collection reset
- Health score for predictive maintenance demonstrations
- Confidence score for telemetry trust assessment
- Carbon score for route optimization demonstrations
- Route zone, service-window, and pickup-batch recommendations
- Route priority levels from P0_IMMEDIATE to P4_NORMAL
- SLA state classification: ON_TRACK, DUE_TODAY, DUE_30_MIN, BREACH_RISK
- Edge action selection for dispatch, compaction, maintenance, or telemetry
- Compaction lockouts for gas-risk or anomaly conditions
- Offline queue depth and cloud acknowledgement simulation
- Digital twin snapshot in each telemetry packet
- Packet checksum for transmission-integrity demonstrations
- Event logging for boot, status changes, lid movement, collection, and faults
- Low-power loop behavior when simulated battery level is low
- Maintenance mode controlled by long button press


STATUS LEVELS

| Status | Fill Level |
| --- | --- |
| OK | 0% and above |
| WATCH | 40% and above |
| MONITOR | 55% and above |
| COLLECT | 75% and above |
| CRITICAL | 90% and above |
| OVERFLOW | 97% and above |


LOCAL OUTPUTS

- Green LED: normal or watch state
- Yellow LED: monitor or collection state
- Red LED: critical or overflow state
- NeoPixel ring: visual fill-level and risk indicator
- Buzzer: escalating alert patterns
- Lid servo: opens when PIR motion is detected
- Compactor servo: runs when local compaction is allowed


HOW TO RUN IN WOKWI

1. Open a MicroPython ESP32 project in Wokwi.
2. Copy `main.py` into the Wokwi code editor.
3. Copy `diagram.json` into the Wokwi diagram editor.
4. Start the simulation.
5. Open the serial monitor to view telemetry and events.


DEMO SCENARIOS

- Adjust the HC-SR04 distance slider to simulate changing bin fill level:
  - 100 cm is close to empty
  - 50 cm is about 54% full
  - 20 cm is about 87% full
  - 8 cm or lower is treated as full
- Trigger the PIR sensor to open the lid.
- Press the COLLECT button briefly to simulate bin collection.
- Hold the COLLECT button for about two seconds to toggle maintenance mode.
- Lower the battery potentiometer to demonstrate low-power behavior.
- Increase the odor/gas potentiometer to trigger anomaly handling.
- Change DHT22 temperature or humidity to affect environmental risk scoring.
- Raise fill level above 82% with no active lockouts to trigger compaction.


TELEMETRY OUTPUT

The firmware prints JSON-style telemetry to the serial monitor. Each packet
contains device metadata, sensor readings, decision outputs, actuator states,
fleet-priority fields, and diagnostic indicators.

Example:

```json
{
  "device": "SWBIN-BEY-001",
  "fleet": "BEY-SMART-WASTE-FLEET",
  "fw": "4.0.0-edge-platform",
  "location": "Beirut Campus - Block A",
  "geohash": "svc4r8",
  "uptime_s": 42,
  "distance_cm": 50.2,
  "fill_percent": 54.1,
  "remaining_liters": 55.1,
  "waste_liters": 64.9,
  "status": "MONITOR",
  "trend": "FILLING",
  "fill_rate_pct_min": 2.35,
  "eta_collect_min": 8.9,
  "eta_overflow_min": 18.3,
  "risk_score": 46.4,
  "health_score": 91.2,
  "confidence_score": 94.0,
  "carbon_score": 38.0,
  "sanitation_score": 16.2,
  "collection_age_min": 4.1,
  "truck_load_percent": 2.7,
  "route_priority": "P3_WATCHLIST",
  "sla": "ON_TRACK",
  "edge_action": "TELEMETRY_ONLY",
  "compaction": "SKIP",
  "route_zone": "A1",
  "service_window": "NORMAL_ROUTE",
  "pickup_batch": "DEFER_UNTIL_ROUTE",
  "samples": 9,
  "quality": 96,
  "quality_label": "GOOD",
  "lid": "CLOSED",
  "alert": "NORMAL",
  "battery_percent": 85.0,
  "gas_percent": 20.0,
  "temp_c": 28.0,
  "humidity": 55.0,
  "maintenance": false,
  "collections": 0,
  "compactions": 0,
  "queue_depth": 0,
  "cloud_ack": true,
  "anomalies": "none",
  "twin": "MONITOR:P3_WATCHLIST:55.1L:0Q:NORMAL_ROUTE",
  "cloud_seq": 3,
  "checksum": 803
}
```


FILES

- `main.py`: MicroPython firmware for the ESP32 simulation
- `diagram.json`: Wokwi circuit definition
- `README.txt`: Project documentation


NOTES

This is a simulation-focused project. Cloud publishing, battery behavior,
odor/gas readings, and queue acknowledgement are modeled locally so the project
can run without external credentials or network services.
