# SIH26143 — AIS Data Pipeline
## MarineCadastre → Download → Clean → Parquet → DuckDB → Sequential Querying → Candidate Vessels

> **Purpose:** Detailed implementation plan for the AIS side of SIH26143.
>
> **Core idea:** We do not use another ML model for vessel attribution. The project architecture defines AIS correlation as spatial + temporal analysis, followed by evidence features and weighted scoring.
>
> **Source basis:** This document follows the SIH26143 architecture specification. Concrete rules for missing values, Parquet/DuckDB layout, and SQL are implementation recommendations.

---

# 1. AIS's place in the system

```text
Sentinel-1 SAR / EO
        ↓
U-Net segmentation
        ↓
Oil-spill mask
        ↓
Spill characterisation
(area / polygon / centroid / extent)
        ↓
Environmental data
(wind + currents)
        ↓
Drift / hindcast
        ↓
Probable spill origin + origin-time window
        ↓
AIS spatial + temporal search
        ↓
Candidate vessels
        ↓
Trajectory reconstruction
        ↓
Evidence feature extraction
        ↓
Weighted evidence scoring
        ↓
Ranked candidate vessels
        ↓
Confidence / evidence-quality assessment
```

The architecture defines AIS inputs as MMSI, timestamp, latitude, longitude, speed, course, heading, and vessel metadata where available. It also defines the AIS functions for cleaning, validation, time/bbox/radius filtering, sorting/grouping by MMSI, trajectory construction/interpolation, distance/time/track calculations, behaviour features, candidate search, and attribution scoring. fileciteturn4file0L183-L200 fileciteturn7file0L13-L54

---

# 2. What to download

## Prototype recommendation

Do **not** begin by downloading the complete historical archive.

Start with the year(s) containing the incident(s) we want to test.

Example:

```text
Target incident:
2026-01-01 00:00 UTC

Initial AIS archive:
2026 daily files
```

The public source to use is the Marine Cadastre Vessel Traffic archive:

https://hub.marinecadastre.gov/pages/vesseltraffic

Keep raw files untouched.

```text
data/
└── raw/
    └── ais/
        ├── 2026/
        │   ├── 2026-01-01.csv
        │   ├── 2026-01-02.csv
        │   └── ...
        └── 2025/
            └── ...
```

The project architecture lists MarineCadastre as a candidate AIS source. fileciteturn4file0L183-L200

> **Implementation note:** The exact current MarineCadastre file/service URLs should be taken from the official page/catalog at implementation time. Do not invent a URL pattern.

---

# 3. Choose the required dates for an incident

The AIS archive is daily, so select only the date partitions that overlap the investigation window.

Example:

```text
Origin time = 2026-01-01 00:05
Investigation window = ±60 min

Required dates:
2025-12-31
2026-01-01
```

Python:

```python
from datetime import timedelta

def required_dates(start_time, end_time):
    dates = []
    current = start_time.date()

    while current <= end_time.date():
        dates.append(current)
        current += timedelta(days=1)

    return dates
```

This handles midnight/year-boundary cases automatically.

---

# 4. Download layer

Recommended downloader responsibilities:

```text
get_required_dates()
        ↓
find MarineCadastre source URL/file
        ↓
download
        ↓
verify file exists / size / checksum if available
        ↓
store in data/raw/ais/YYYY/
```

Keep the original file name and record:

```text
source_url
source_file
download_timestamp
source_date
```

This gives us provenance and makes reprocessing reproducible.

---

# 5. Do not load huge CSVs blindly

For large files, process them in chunks:

```python
import pandas as pd

for chunk in pd.read_csv(
    "data/raw/ais/2026/2026-01-01.csv",
    chunksize=250_000
):
    process_chunk(chunk)
```

Chunk processing is useful for schema checks, cleaning, validation, and Parquet conversion.

---

# 6. Normalize the AIS schema

Use a stable internal schema:

```text
mmsi
base_date_time
longitude
latitude
sog
cog
heading
vessel_name
imo
call_sign
vessel_type
status
length
width
draft
cargo
transceiver
source_file
source_date
```

`source_file` and `source_date` are recommended audit fields.

Example:

```text
source_file = 2026-01-01.csv
source_date = 2026-01-01
```

---

# 7. Data types

Recommended internal types:

```text
mmsi            → string/integer identifier
base_date_time  → timestamp
longitude       → float
latitude        → float
sog             → float
cog             → float
heading         → float
vessel_name     → string
imo             → string
call_sign       → string
vessel_type     → integer/category
status          → integer/category
length          → float
width           → float
draft           → float
cargo           → integer/category
transceiver     → category/string
```

Keep identifiers such as IMO as strings if the source can contain mixed formatting.

Do not assume every categorical field uses the same codebook across every source.

---

# 8. Cleaning stage

Create:

```python
def clean_ais_data(df):
    ...
```

Responsibilities:

1. normalize column names;
2. parse timestamps;
3. coerce numeric fields carefully;
4. standardize nulls;
5. strip whitespace in text fields;
6. preserve provenance.

Example:

```python
df.columns = (
    df.columns
      .str.strip()
      .str.lower()
      .str.replace(" ", "_")
)

df["base_date_time"] = pd.to_datetime(
    df["base_date_time"],
    errors="coerce"
)
```

The architecture explicitly separates `clean_ais_data()` and `validate_ais_records()`. fileciteturn8file3L104-L119

---

# 9. Validation rules

## Timestamp

Valid example:

```text
2026-01-01 00:02:00
```

Invalid example:

```text
not-a-date
```

Invalid timestamps should not silently continue into temporal correlation.

## Latitude

```text
-90 ≤ latitude ≤ 90
```

## Longitude

```text
-180 ≤ longitude ≤ 180
```

The project architecture requires explicit validation of coordinates and timestamps and warns against silently continuing with invalid data. fileciteturn9file2L228-L264

---

# 10. Missing-value policy

This section is an implementation policy. The architecture requires explicit handling of missing/incomplete AIS and forbids inventing evidence, but it does not prescribe a replacement value for every AIS field. fileciteturn4file0L13-L29

## 10.1 Missing MMSI

```text
mmsi = NULL
```

Action:

```text
Do not group into a vessel trajectory.
Do not invent an ID.
Keep in quarantine/audit statistics if useful.
Exclude from vessel attribution.
```

## 10.2 Missing timestamp

```text
base_date_time = NULL
```

Action:

```text
Reject for temporal analysis.
Do not guess the time.
```

## 10.3 Missing latitude

Cannot perform spatial analysis.

Exclude from spatial candidate search.

## 10.4 Missing longitude

Same as latitude.

## 10.5 Missing latitude OR longitude

Never do:

```text
NULL → 0
```

That creates a fake location.

Keep only for non-spatial audit/metadata if needed.

## 10.6 Missing SOG

Do **not** replace with `0`.

Use:

```text
speed_score = unavailable
```

if the speed feature is required.

The vessel can still participate using other available evidence.

## 10.7 Missing COG

Do not replace with zero.

Set the course-based feature to unavailable.

## 10.8 Missing heading

Do not copy COG into heading.

Set heading-related evidence to unavailable.

## 10.9 Missing vessel name

Does not invalidate the track.

Use:

```text
MMSI + time + position + movement fields
```

Display:

```text
Name unavailable
```

## 10.10 Missing IMO

Does not invalidate an otherwise usable MMSI trajectory.

IMO is supporting identity metadata, not the primary trajectory key.

## 10.11 Missing call sign

Optional metadata; no impact on core trajectory analysis.

## 10.12 Missing vessel type

Optional/contextual. If `vessel_type_score` cannot be computed, mark that feature unavailable.

## 10.13 Missing status

Optional/contextual. Do not infer a status from NULL.

## 10.14 Missing length / width / draft

Leave NULL. These are contextual metadata.

## 10.15 Missing cargo

Leave NULL. Do not infer cargo from the vessel name.

## 10.16 Missing transceiver

Leave NULL. Treat as source/equipment metadata.

---

# 11. Zero vs missing is critical

These are different:

```text
SOG = 0
```

means a value was reported as zero.

```text
SOG = NULL
```

means unavailable.

Do not convert:

```text
NULL → 0
```

because that creates false movement evidence.

Likewise:

```text
missing heading → COG
missing COG → 0
missing location → 0,0
```

are not acceptable defaults.

---

# 12. Duplicate handling

The architecture does not prescribe a specific duplicate policy, so use an explicit engineering policy.

For exact duplicate rows:

```python
df = df.drop_duplicates()
```

but log the count.

For rows with the same:

```text
MMSI + timestamp
```

but different values:

```text
Do NOT blindly drop them.
```

Flag them as potentially conflicting/duplicate observations and preserve provenance until the source behaviour is understood.

---

# 13. CSV → Parquet

After cleaning a daily file:

```python
df.to_parquet(
    "data/processed/ais/year=2026/date=2026-01-01/data.parquet",
    index=False
)
```

Recommended structure:

```text
data/
└── processed/
    └── ais/
        ├── year=2026/
        │   ├── date=2026-01-01/
        │   │   └── data.parquet
        │   ├── date=2026-01-02/
        │   │   └── data.parquet
        │   └── ...
        └── year=2025/
            └── ...
```

Raw CSV remains the source archive; Parquet is the query-optimized processed representation.

---

# 14. DuckDB role

DuckDB is the **SQL query engine** over the Parquet AIS archive.

Install:

```bash
pip install duckdb pandas pyarrow
```

Connect:

```python
import duckdb

con = duckdb.connect("data/ais.duckdb")
```

You can query Parquet directly; you do not have to import the whole archive into a traditional database table.

---

# 15. Basic DuckDB query

```sql
SELECT *
FROM read_parquet(
    'data/processed/ais/year=*/date=*/data.parquet'
)
LIMIT 10;
```

Example by MMSI:

```sql
SELECT
    mmsi,
    base_date_time,
    latitude,
    longitude,
    sog,
    cog,
    heading
FROM read_parquet(
    'data/processed/ais/year=2026/date=*/data.parquet'
)
WHERE mmsi = 368164470
ORDER BY base_date_time;
```

That gives the chronological observations for one vessel.

---

# 16. Incident → AIS inputs

The AIS stage receives something like:

```text
incident_id
origin_lat
origin_lon
origin_time
origin_uncertainty
origin_region
origin/drift path
search_radius_km
time_window_minutes
```

The architecture's candidate search begins from probable origin + origin time and then applies spatial + temporal filtering. fileciteturn7file0L13-L30

---

# 17. Sequential query pipeline

```text
1. Determine required date partitions
        ↓
2. Time filter
        ↓
3. Bounding-box prefilter
        ↓
4. Exact radius/distance filter
        ↓
5. Extract candidate MMSIs
        ↓
6. Fetch wider tracks only for candidate MMSIs
        ↓
7. Sort each track by time
        ↓
8. Build trajectory
        ↓
9. Interpolate only when justified
        ↓
10. Compute evidence features
        ↓
11. Weighted score + rank
        ↓
12. Assess AIS coverage / confidence
```

This follows the architecture's explicit sequence: spatial/temporal filter → candidate vessels → feature engineering → weighted evidence scoring → ranked vessels. fileciteturn6file3L193-L207

---

# 18. Query 1 — time filter

Suppose:

```text
origin_time = 2026-01-01 00:00
window      = ±30 min
```

Then:

```text
23:30 → 00:30
```

SQL:

```sql
SELECT *
FROM read_parquet(
    'data/processed/ais/year=2026/date=*/data.parquet'
)
WHERE base_date_time
      BETWEEN TIMESTAMP '2025-12-31 23:30:00'
      AND TIMESTAMP '2026-01-01 00:30:00';
```

For a real midnight-crossing query, include both required daily partitions.

---

# 19. Query 2 — geographic bounding box

Suppose the probable origin is:

```text
lat = 36.87
lon = -76.32
```

Use a generous bounding box as a cheap prefilter:

```sql
SELECT *
FROM read_parquet(
    'data/processed/ais/year=2026/date=*/data.parquet'
)
WHERE base_date_time
      BETWEEN TIMESTAMP '2025-12-31 23:30:00'
      AND TIMESTAMP '2026-01-01 00:30:00'
  AND latitude BETWEEN 36.78 AND 36.96
  AND longitude BETWEEN -76.42 AND -76.22;
```

This is a prefilter, not the final distance test.

---

# 20. Query 3 — exact radius

After the box filter, compute geodesic/Haversine distance:

```python
distance_km = haversine(
    row["latitude"],
    row["longitude"],
    origin_lat,
    origin_lon,
)
```

Then:

```text
distance_km <= search_radius_km
```

The project architecture explicitly defines both bbox and radius filtering. fileciteturn7file0L32-L54

---

# 21. Query 4 — candidate MMSIs

```python
candidate_mmsis = (
    candidates["mmsi"]
    .dropna()
    .unique()
)
```

Example:

```text
368164470
367712350
369053000
366961280
```

These are **candidate vessels**, not responsible vessels.

---

# 22. Query 5 — retrieve wider trajectories

Do not analyze only the one observation that happened to pass the first filter.

Fetch a wider time context for the candidate MMSIs.

Example:

```text
candidate window: 23:30–00:30
trajectory context: 22:00–03:00
```

SQL:

```sql
SELECT *
FROM read_parquet(
    'data/processed/ais/year=2026/date=*/data.parquet'
)
WHERE mmsi IN (
    368164470,
    367712350,
    369053000
)
AND base_date_time
    BETWEEN TIMESTAMP '2025-12-31 22:00:00'
    AND TIMESTAMP '2026-01-01 03:00:00'
ORDER BY mmsi, base_date_time;
```

The exact wider context window should be configurable.

---

# 23. Query 6 — sort/group tracks

```python
track_df = df.sort_values(
    ["mmsi", "base_date_time"]
)

groups = track_df.groupby("mmsi")
```

Conceptually:

```text
MMSI 368164470
    23:58 → point A
    00:00 → point B
    00:02 → point C
    00:04 → point D

MMSI 369053000
    23:58 → point A
    00:01 → point B
    00:03 → point C
```

The architecture explicitly requires sorting vessel tracks, grouping records by MMSI, and building trajectories. fileciteturn6file1L20-L31

---

# 24. Build trajectories

```text
AIS points
    ↓
sort by timestamp
    ↓
connect chronological points
    ↓
vessel trajectory
```

Example:

```text
A ---- B ---- C ---- D ---- E
                  ↑
             spill origin
```

Do not use only the nearest AIS point.

---

# 25. Interpolation

The architecture includes:

```python
interpolate_vessel_position(track, timestamp)
```

Example:

```text
23:59 → A
00:01 → B
```

For an origin time of `00:00`, you can interpolate only when the gap is small and the surrounding observations are valid.

Do not interpolate across very large gaps.

Example bad situation:

```text
00:04
  ↓
90-minute AIS gap
  ↓
01:34
```

Treat the middle as unknown and reduce coverage quality.

---

# 26. Evidence features

The architecture recommends:

```text
distance_score
 time_score
 trajectory_score
 heading_score
 speed_score
 path_proximity_score
 behaviour_score
 vessel_type_score
```

The architecture specifically says **do not use nearest vessel = culprit**. fileciteturn7file0L90-L152

---

# 27. Distance feature

Question:

> How close did the vessel get to the probable origin?

Example:

```text
minimum distance = 1.4 km
```

Convert that into a configurable normalized score.

---

# 28. Time feature

Question:

> How closely does the vessel timing match the inferred origin time?

Example:

```text
origin time = 00:00
nearest/origin-crossing vessel time = 00:05
Δt = 5 min
```

Smaller time differences can receive stronger time scores.

---

# 29. Trajectory + origin intersection

Use:

```python
calculate_trajectory_match()
calculate_origin_intersection()
calculate_path_proximity()
```

Evaluate the full vessel route against:

- probable origin;
- origin region;
- inferred drift path/corridor;
- spill geometry when appropriate.

The architecture explicitly defines these functions. fileciteturn7file0L74-L86

---

# 30. Heading feature

If valid heading exists:

```text
heading_score = computed
```

If missing:

```text
heading_score = unavailable
```

Never copy COG into heading.

---

# 31. Speed feature

If SOG is valid:

```text
speed_score = computed
```

If SOG is missing:

```text
speed_score = unavailable
```

Never convert missing SOG to `0`.

---

# 32. Behaviour features

The architecture includes:

```python
calculate_average_speed()
calculate_heading_change()
calculate_speed_change()
detect_course_anomalies()
detect_speed_anomalies()
```

Example pattern:

```text
23:50  10.2 kn
23:52  10.1 kn
23:54   9.8 kn
23:56   5.2 kn
23:58   1.2 kn
00:00   0.0 kn
00:02   1.4 kn
00:04   5.1 kn
```

This may be flagged as unusual behaviour, but:

```text
behaviour anomaly ≠ proof of spill causation
```

It is one evidence feature.

---

# 33. Vessel type feature

`vessel_type_score` is contextual.

Do not let it dominate trajectory/time/distance evidence.

The architecture makes all weights configuration values. fileciteturn7file0L154-L192

---

# 34. Weighted evidence score

Prototype formula:

```text
Total Score =
    w1 * distance_score
  + w2 * time_score
  + w3 * trajectory_score
  + w4 * heading_score
  + w5 * speed_score
  + w6 * path_proximity_score
  + w7 * behaviour_score
  + w8 * vessel_type_score
```

Weights belong in configuration, not scattered hard-coded values.

Example only:

```yaml
weights:
  distance: 0.25
  time: 0.20
  trajectory: 0.25
  heading: 0.10
  speed: 0.05
  path_proximity: 0.10
  behaviour: 0.04
  vessel_type: 0.01
```

These are prototype/example numbers, not validated scientific weights.

---

# 35. Do not present score as legal probability

Bad:

```text
Vessel A caused the spill: 82%
```

Good:

```text
Rank: 1
MMSI: 369053000
Evidence score: 0.82
Confidence: Medium
```

Show the evidence:

```text
✓ 2.1 km from probable origin
✓ strong temporal match
✓ trajectory compatible with drift corridor
✓ heading compatible
✓ moderate behavioural anomaly
```

The project architecture explicitly gives this explainable style and rejects a black-box accusation. fileciteturn5file1L278-L307

---

# 36. Missing AIS / incomplete AIS states

The architecture defines:

```text
FULL
PARTIAL
INSUFFICIENT
UNAVAILABLE
```

### FULL

```text
AIS coverage: Full
Attribution: Available
Confidence: High / Medium / Low
```

### PARTIAL

```text
AIS coverage: Partial
Attribution: Available with reduced confidence
```

### INSUFFICIENT / UNAVAILABLE

```text
AIS coverage: Insufficient
Attribution: Unavailable
Reason: insufficient vessel evidence
```

The architecture explicitly requires this behaviour. fileciteturn9file0L15-L50

---

# 37. Case: no AIS exists

```text
Oil spill detected
      ↓
Probable origin estimated
      ↓
AIS query finds no usable AIS coverage
      ↓
Attribution unavailable
```

Never fabricate a vessel or confidence score. fileciteturn4file0L13-L29

---

# 38. Case: AIS exists but is sparse

Example:

```text
AIS available
but large timestamp gaps
or poor local coverage
```

Use:

```text
AIS coverage = PARTIAL
```

Run reduced analysis and lower confidence.

---

# 39. Case: AIS query works but no candidates are returned

Different from AIS being unavailable:

```text
AIS available
        ↓
query succeeded
        ↓
zero vessels inside search criteria
```

Output:

```text
candidate_count = 0
attribution = unavailable / no supported candidate
```

Do not keep expanding the radius until a vessel appears unless a configured fallback policy says to do so.

---

# 40. Case: one field is missing but the trajectory is otherwise usable

Example:

```text
MMSI      ✓
timestamp ✓
lat/lon   ✓
SOG       ✗
COG       ✓
heading   ✗
```

Use:

```text
distance   ✓
time       ✓
trajectory ✓
SOG        unavailable
heading    unavailable
```

Then reduce feature coverage / confidence as appropriate.

---

# 41. Case: missing IMO but valid MMSI

Still use the track.

```text
MMSI + timestamp + lat/lon + movement
```

is enough for core trajectory analysis.

IMO is supporting identity metadata.

---

# 42. Case: same MMSI with different IMO values

Do not automatically treat them as separate vessels.

Flag an identity inconsistency and inspect:

- timestamp
- vessel name
- call sign
- source
- identifier validity

Continue to use MMSI as the primary trajectory grouping key unless a source-specific identity correction is established.

---

# 43. Case: vessel name changes

Do not split a trajectory only because `vessel_name` changes.

MMSI remains the primary track grouping key for the prototype.

Keep the metadata history/provenance.

---

# 44. Case: missing COG but valid heading

Use:

```text
heading = available
COG = unavailable
```

Never fabricate COG.

---

# 45. Case: missing heading but valid COG

Use:

```text
COG = available
heading = unavailable
```

Never copy COG into heading.

---

# 46. Case: SOG = 0

Keep:

```text
SOG = 0
```

A vessel can still matter if it is stationary near the probable origin.

Do not assume:

```text
SOG = 0 → irrelevant
```

Use other context such as status (if valid), consecutive positions, COG, heading, and trajectory.

---

# 47. Case: large observation gaps

Example:

```text
00:04
  ↓
90-minute gap
  ↓
01:34
```

Do not pretend the vessel's position during the gap is known.

Recommended:

```text
coverage score ↓
trajectory confidence ↓
interpolation disabled for large gaps
```

---

# 48. Case: stationary vessel

A vessel with SOG=0 is not automatically irrelevant.

It may still be spatially and temporally consistent with the probable origin.

Movement features may simply have less information.

---

# 49. Case: many candidates

Return all candidates passing the initial configured search.

Example:

```text
17 candidate MMSIs
        ↓
feature extraction
        ↓
weighted scoring
        ↓
rank 1..17
```

Do not pick only the nearest vessel.

---

# 50. Environmental/drift data missing

If environmental inputs are unavailable:

```text
hindcast unavailable
forecast unavailable
origin estimation reduced/unavailable
```

AIS attribution may then have reduced confidence or become unavailable if the origin/time evidence is insufficient.

The architecture explicitly distinguishes unavailable environmental data from low-quality environmental data. fileciteturn8file0L47-L51

---

# 51. No credible spill detected

If U-Net does not produce a credible spill:

```text
No confirmed spill
        ↓
STOP
```

There is no reason to run AIS attribution without a credible spill detection. fileciteturn4file2L446-L461

---

# 52. Logging / audit trail

For every incident record:

```text
incident_id
source files
source dates
query time
investigation window
search radius
candidate count
candidate MMSIs
AIS coverage state
feature availability
final ranking
confidence
```

The architecture explicitly requires an audit trail for each incident. fileciteturn9file2L268-L284

Example:

```text
incident=INC-001
AIS dates=2025-12-31,2026-01-01
time_window=23:30..00:30
radius=10km
candidate_count=8
AIS_coverage=PARTIAL
top_rank=369053000
```

---

# 53. Recommended repository structure

```text
oilspill/
├── app/
│   ├── main.py
│   ├── orchestrator.py
│   └── config.py
│
├── ais/
│   ├── downloader.py
│   ├── ingestion.py
│   ├── cleaning.py
│   ├── validation.py
│   ├── duckdb_store.py
│   ├── query.py
│   ├── trajectory.py
│   ├── features.py
│   ├── attribution.py
│   └── quality.py
│
├── data/
│   ├── raw/
│   │   └── ais/
│   ├── processed/
│   │   └── ais/
│   └── outputs/
│
└── models/
    └── segmentation/
```

The architecture also recommends separating raw and processed data and modular services rather than one giant `run_everything()` function. fileciteturn4file2L498-L526 fileciteturn5file2L447-L493

---

# 54. Suggested function interfaces

```python
# ingestion.py
def ingest_daily_csv(csv_path, output_parquet_path):
    ...

# cleaning.py
def clean_ais_data(df):
    ...

# validation.py
def validate_ais_records(df):
    ...

# query.py
def find_candidate_vessels(
    con,
    origin,
    origin_time,
    search_radius_km,
    time_window_minutes,
):
    ...

# trajectory.py
def build_vessel_trajectory(track):
    ...

def interpolate_vessel_position(track, timestamp):
    ...

# features.py
def build_candidate_vessel_features(
    track,
    origin,
    origin_time,
    drift_result,
):
    ...

# attribution.py
def rank_candidate_vessels(candidates, weights):
    ...

# quality.py
def assess_ais_coverage(candidates, origin, time_window):
    ...
```

The project architecture treats these as target interfaces/engineering contracts unless source code confirms an implementation already exists. fileciteturn5file3L543-L559

---

# 55. Complete implementation flow

```text
                MARINECADASTRE
                      │
                      ▼
              Download daily AIS
                      │
                      ▼
                   RAW CSV
                      │
                      ▼
            Schema normalization
                      │
                      ▼
              Data validation
                      │
          ┌───────────┴────────────┐
          │                        │
      valid rows              invalid rows
          │                        │
          ▼                        ▼
       CLEAN                    QUARANTINE
          │
          ▼
     PARQUET FILES
          │
          ▼
        DUCKDB
          │
          ▼
    Incident received
          │
          ▼
 Probable origin + time
          │
          ▼
   Determine date files
          │
          ▼
      TIME FILTER
          │
          ▼
   BBOX PRE-FILTER
          │
          ▼
   EXACT RADIUS FILTER
          │
          ▼
    CANDIDATE MMSIs
          │
          ▼
   RETRIEVE WIDER TRACK
          │
          ▼
  SORT + GROUP BY MMSI
          │
          ▼
  BUILD TRAJECTORIES
          │
          ▼
  INTERPOLATE IF VALID
          │
          ▼
    FEATURE ENGINEERING
          │
          ├── distance
          ├── time
          ├── trajectory
          ├── heading
          ├── speed
          ├── path proximity
          ├── behaviour
          └── vessel type
          │
          ▼
    WEIGHTED SCORING
          │
          ▼
     RANK CANDIDATES
          │
          ▼
 DATA QUALITY / CONFIDENCE
          │
          ▼
   EXPLAINABLE RESULT
```

---

# 56. The mental model

Think of DuckDB as:

```text
"SQL engine over our AIS Parquet archive."
```

Think of the AIS subsystem as:

```text
DOWNLOAD
   ↓
CLEAN
   ↓
VALIDATE
   ↓
PARQUET
   ↓
DUCKDB
   ↓
QUERY
   ↓
CANDIDATES
   ↓
TRAJECTORIES
   ↓
FEATURES
   ↓
SCORE
   ↓
RANK
   ↓
CONFIDENCE
```

The core engineering rule is:

> Every downstream conclusion must be traceable back to the source data and intermediate evidence that produced it.

The architecture explicitly identifies this traceability as the central design principle. fileciteturn4file3L611-L627

---

# 57. Sources

1. **SIH26143 — OILSPILL: Complete System Architecture & Engineering Specification** — project-provided architecture document.
2. **Marine Cadastre — Vessel Traffic** — official AIS archive page:
   https://hub.marinecadastre.gov/pages/vesseltraffic

---

## One-line summary

**We download only the incident-relevant AIS days, preserve raw CSVs, clean/validate into Parquet, let DuckDB perform the time/spatial candidate search, then reconstruct only the shortlisted MMSI trajectories and rank them using explainable evidence features with explicit handling of missing/insufficient data.**
