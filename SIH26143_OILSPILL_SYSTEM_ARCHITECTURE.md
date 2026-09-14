# SIH26143 --- OILSPILL

## Complete System Architecture & Engineering Specification

> **Purpose:** This document defines the end-to-end software
> architecture for the SIH26143 marine oil-spill detection, tracing and
> vessel-attribution platform.
>
> It describes **what connects to what, why each component exists, what
> data flows between components, what technology is used, and the
> function-level interfaces that should be implemented**.
>
> **Important engineering distinction:** the project material
> establishes the conceptual pipeline and technology selections below.
> Where exact source-code function names were not available, this
> document defines a **recommended implementation contract** rather than
> pretending those functions already exist.

------------------------------------------------------------------------

# 1. Executive Architecture

The system is intentionally **modular** rather than one large AI model.

The core flow is:

``` text
Satellite SAR / EO
        |
        v
+-----------------------+
| Satellite Preprocess  |
+-----------+-----------+
            |
            v
+-----------------------+
| U-Net Segmentation    |
| Oil / Non-oil mask    |
+-----------+-----------+
            |
            v
+-----------------------+
| Spill Characterisation|
| Area / geometry /     |
| centroid / extent     |
+-----------+-----------+
            |
            +-----------------------------+
            |                             |
            v                             v
+-----------------------+       +-----------------------+
| Environmental Data    |       | Historical AIS        |
| Wind + currents       |       | Vessel trajectories   |
+-----------+-----------+       +-----------+-----------+
            |                             |
            v                             v
+-----------------------+       +-----------------------+
| Drift / Hindcast      |       | AIS Spatial/Temporal  |
| + Forecast Engine     |       | Filtering             |
+-----------+-----------+       +-----------+-----------+
            |                             |
            v                             v
+-----------------------+       +-----------------------+
| Probable Origin       |       | Candidate Vessels     |
| + uncertainty         |       | + trajectories        |
+-----------+-----------+       +-----------+-----------+
            |                             |
            +-------------+---------------+
                          |
                          v
              +------------------------+
              | Vessel Attribution     |
              | Evidence Features      |
              | + Weighted Scoring     |
              +-----------+------------+
                          |
                          v
              +------------------------+
              | Confidence & Evidence  |
              | Assessment             |
              +-----------+------------+
                          |
                          v
              +------------------------+
              | Authority Dashboard    |
              | Map + Mask + Origin    |
              | Vessels + Forecast      |
              +------------------------+
```

------------------------------------------------------------------------

# 2. Architectural Principles

## 2.1 Do not build one giant AI model

The platform is a pipeline of specialised computational components:

  Component                Primary method
  ------------------------ --------------------------------------
  Oil-spill detection      Deep learning / U-Net
  Spill characterisation   Computer vision + geometry
  Hindcasting              Geospatial drift model
  Forecasting              Geospatial drift model
  AIS correlation          Spatial + temporal analysis
  Vessel attribution       Evidence features + weighted scoring
  Confidence               Evidence/data-quality assessment
  Dashboard                Interactive geospatial visualisation

This is preferable because each stage can be independently tested,
replaced and improved.

## 2.2 Data contracts between stages

Every stage should have a defined input/output object.

For example:

``` text
SatelliteImage
      |
      v
SegmentationResult
      |
      v
SpillGeometry
      |
      v
DriftResult
      |
      v
CandidateVessels
      |
      v
AttributionResult
      |
      v
DashboardPayload
```

This prevents downstream components from depending on internal
implementation details.

## 2.3 Never invent evidence

If AIS is missing or incomplete:

``` text
AIS unavailable
      |
      v
Attribution unavailable
```

The system must not manufacture a vessel or an artificial confidence
score.

The correct output is:

> Attribution unavailable due to insufficient AIS/evidence coverage.

------------------------------------------------------------------------

# 3. Technology Stack

The project material identifies the following technical stack.

## 3.1 Programming

### Python

Primary language for:

-   Data ingestion
-   Data cleaning
-   Satellite processing
-   ML inference
-   Computer vision
-   Geospatial processing
-   Drift modelling
-   AIS analysis
-   Attribution scoring

## 3.2 Deep Learning

### PyTorch

Used for the oil-spill segmentation model.

Primary model:

``` text
U-Net
```

Purpose:

``` text
SAR image
   ↓
pixel-wise segmentation
   ↓
oil-spill mask
```

## 3.3 Data Processing

### Pandas

Used for:

-   AIS tables
-   Weather tables
-   Ocean-current tables
-   Feature engineering
-   Temporal filtering
-   Data validation

### NumPy

Used for:

-   Numerical operations
-   Raster arrays
-   Model inputs
-   Vector calculations
-   Mathematical drift calculations

## 3.4 Computer Vision

### OpenCV

Used where required for:

-   Image manipulation
-   Mask processing
-   Morphological operations
-   Contour extraction
-   Connected components
-   Image normalisation

## 3.5 Geospatial

### GeoPandas

Used for:

-   Spatial dataframes
-   Points, lines and polygons
-   Coordinate reference systems
-   Spatial joins
-   Vessel/spill geometry operations

### QGIS

Used primarily as a geospatial analysis/validation environment:

-   Inspecting layers
-   Validating geometries
-   Visualising spill masks
-   Inspecting AIS trajectories
-   Preparing/debugging geospatial outputs

### Folium / Leaflet

Used for interactive map rendering in the dashboard/prototype.

## 3.6 Dashboard

### Streamlit

Used as the selected rapid dashboard framework where applicable.

Responsibilities:

-   User controls
-   Map
-   Spill overlays
-   Vessel ranking
-   Environmental layers
-   Forecast layers
-   Evidence/confidence panels

### Folium / Leaflet

Provides the interactive map layer within the UI.

## 3.7 Environmental Data

### ERA5

Meteorological input, particularly:

-   Wind speed
-   Wind direction
-   Other relevant atmospheric variables

### Copernicus Marine / oceanographic sources

Oceanographic input, particularly:

-   Ocean currents
-   Sea-state variables where available

## 3.8 Satellite Data

### Sentinel-1 SAR

Primary satellite modality for oil-spill detection.

The labelled Sentinel-1 SAR oil-spill dataset identified in the project
material is used for segmentation training.

## 3.9 AIS

Historical AIS data provides:

-   MMSI
-   Timestamp
-   Latitude
-   Longitude
-   Speed
-   Course
-   Heading
-   Vessel metadata where available

Candidate sources discussed in the project include:

-   MarineCadastre
-   AISHub
-   Synthetic AIS for controlled prototyping when necessary

## 3.10 Google Earth Engine

**Important:** Google Earth Engine should not be described as a core
dependency unless it is actually present in the implementation.

It can be used as a **data-access/preprocessing option** for
satellite/environmental data, but the established architecture already
works with downloaded Sentinel-1 and environmental datasets plus Python
geospatial tooling.

------------------------------------------------------------------------

# 4. High-Level C4-Style Architecture

## 4.1 System Context

``` mermaid
flowchart TB
    Authority["Authority / Response Team"]
    Analyst["Analyst / Operator"]

    System["OILSPILL Intelligence Platform"]

    Sentinel["Sentinel-1 SAR / EO"]
    AIS["Historical AIS Sources"]
    Weather["ERA5 / Meteorological Data"]
    Ocean["Copernicus / Oceanographic Data"]
    QGIS["QGIS / GIS Validation"]

    Authority -->|"Investigate / respond"| System
    Analyst -->|"Analyse incident"| System

    Sentinel -->|"Satellite imagery"| System
    AIS -->|"Vessel trajectories"| System
    Weather -->|"Wind / weather"| System
    Ocean -->|"Currents / ocean state"| System

    System -->|"GIS layers / exports"| QGIS
```

------------------------------------------------------------------------

# 5. Container Architecture

``` mermaid
flowchart LR
    subgraph External["External Data Sources"]
        S1["Sentinel-1 SAR / EO"]
        AIS["Historical AIS"]
        ERA5["ERA5 Weather"]
        COP["Copernicus Ocean"]
    end

    subgraph App["OILSPILL Application"]
        UI["Streamlit Dashboard<br/>Folium / Leaflet"]

        API["Application / Orchestration Layer"]

        SAT["Satellite Processing"]
        SEG["U-Net Segmentation"]
        CHAR["Spill Characterisation"]

        ENV["Environmental Processing"]
        DRIFT["Hindcast / Forecast Engine"]

        AISPROC["AIS Processing"]
        ATTR["Vessel Attribution"]

        CONF["Confidence & Evidence"]

        STORE["Processed Data / Results"]
    end

    S1 --> SAT
    SAT --> SEG
    SEG --> CHAR

    ERA5 --> ENV
    COP --> ENV

    CHAR --> DRIFT
    ENV --> DRIFT

    AIS --> AISPROC

    DRIFT --> ATTR
    AISPROC --> ATTR
    CHAR --> ATTR

    ATTR --> CONF
    DRIFT --> CONF
    SEG --> CONF

    CONF --> STORE
    CHAR --> STORE
    DRIFT --> STORE
    AISPROC --> STORE

    STORE --> API
    API --> UI
```

------------------------------------------------------------------------

# 6. Detailed Component Architecture

## 6.1 Data Acquisition Layer

### Responsibilities

1.  Locate source files/API responses.
2.  Download or load data.
3.  Validate schema.
4.  Validate timestamps.
5.  Validate coordinate ranges.
6.  Record provenance.
7.  Store normalised intermediate data.

### Inputs

``` text
Satellite imagery
AIS
Weather
Ocean currents
Incident metadata
```

### Outputs

``` text
Normalised satellite records
Normalised AIS records
Normalised weather records
Normalised ocean records
```

### Function contract

``` python
load_satellite_image(path)
validate_satellite_metadata(metadata)
load_ais_data(path)
validate_ais_schema(df)
load_weather_data(path)
load_ocean_current_data(path)
validate_coordinates(df)
validate_timestamps(df)
normalise_ais_columns(df)
normalise_environment_columns(df)
record_data_provenance(source, metadata)
```

------------------------------------------------------------------------

# 7. Satellite Processing Layer

## 7.1 Objective

Convert raw Sentinel-1/EO imagery into a model-ready image.

``` text
Raw satellite scene
       |
       v
Metadata validation
       |
       v
Crop / AOI extraction
       |
       v
Band / channel selection
       |
       v
Normalisation
       |
       v
Model-ready tensor
```

## 7.2 Functions

``` python
load_sar_scene(path)
read_sar_metadata(path)
select_sar_bands(scene)
crop_to_aoi(scene, aoi)
clip_raster_to_bounds(raster, bounds)
reproject_raster(raster, target_crs)
normalise_sar_image(image)
standardise_model_input(image)
prepare_segmentation_tensor(image)
validate_satellite_scene(scene)
```

------------------------------------------------------------------------

# 8. U-Net Segmentation Layer

## 8.1 Objective

Identify pixels belonging to an oil slick.

``` text
Input:
    SAR image

Output:
    Probability mask
    Binary oil mask
```

## 8.2 Training pipeline

``` mermaid
flowchart LR
    Dataset["Sentinel-1<br/>image + mask"]
    Split["Train / Validation / Test"]
    Aug["Synchronized augmentation"]
    Tensor["Tensor conversion"]
    UNet["U-Net"]
    Loss["Segmentation loss"]
    Eval["IoU / Dice / pixel metrics"]
    Weights["Trained model weights"]

    Dataset --> Split
    Split --> Aug
    Aug --> Tensor
    Tensor --> UNet
    UNet --> Loss
    Loss --> UNet
    UNet --> Eval
    Eval --> Weights
```

## 8.3 Critical augmentation rule

The satellite image and segmentation mask must undergo the **same
spatial transformation**.

Valid:

``` text
Image + Mask
     |
     +--> same rotation
     +--> same crop
     +--> same flip
     |
     v
Augmented Image + Augmented Mask
```

Invalid:

``` text
Image -> crop A
Mask  -> crop B
```

because the labels no longer correspond to pixels.

## 8.4 Functions

``` python
build_unet()
load_segmentation_dataset()
split_segmentation_dataset()
apply_joint_augmentation(image, mask)
normalise_training_image(image)
train_unet(model, train_loader, val_loader, config)
validate_unet(model, val_loader)
calculate_iou(prediction, target)
calculate_dice_score(prediction, target)
calculate_pixel_accuracy(prediction, target)
save_model_weights(model, path)
load_model_weights(path)
predict_spill_mask(model, image)
postprocess_spill_mask(mask)
threshold_probability_mask(probability_mask, threshold)
```

------------------------------------------------------------------------

# 9. Spill Characterisation Layer

## 9.1 Objective

Convert a binary spill mask into structured geospatial information.

``` text
Oil mask
   |
   +--> Area
   +--> Perimeter
   +--> Bounding box
   +--> Centroid
   +--> Orientation
   +--> Polygon
   +--> Extent
```

## 9.2 Processing

``` mermaid
flowchart LR
    Mask["Binary Oil Mask"]
    Morph["Morphological cleanup"]
    CC["Connected Components"]
    Contour["Contour extraction"]
    Geo["Pixel → geographic coordinates"]
    Metrics["Geometry metrics"]
    Polygon["Spill polygon"]

    Mask --> Morph
    Morph --> CC
    CC --> Contour
    Contour --> Geo
    Geo --> Metrics
    Geo --> Polygon
```

## 9.3 Functions

``` python
clean_spill_mask(mask)
remove_small_components(mask, min_area)
extract_spill_components(mask)
extract_spill_contours(mask)
calculate_pixel_area(mask, pixel_resolution)
calculate_spill_area(mask, geotransform)
calculate_perimeter(contour)
calculate_bounding_box(contour)
calculate_centroid(contour)
calculate_orientation(contour)
mask_to_polygon(mask, transform)
simplify_spill_polygon(polygon, tolerance)
calculate_spill_extent(polygon)
calculate_shape_features(contour)
build_spill_geometry(mask, metadata)
validate_spill_geometry(geometry)
```

## 9.4 Output object

Recommended structure:

``` python
SpillGeometry(
    incident_id,
    centroid_lat,
    centroid_lon,
    area_km2,
    perimeter_km,
    bounding_box,
    orientation_deg,
    polygon,
    extent,
    confidence
)
```

------------------------------------------------------------------------

# 10. Environmental Data Processing Layer

## 10.1 Objective

Synchronise environmental data with the detected spill.

The data does not need to have exactly the same timestamp as the
satellite image. It must instead be aligned within a defensible temporal
and spatial window.

``` text
Spill:
    location = (lat, lon)
    time = T

Weather:
    nearby grid cells
    around T

Ocean:
    nearby grid cells
    around T
```

## 10.2 Processing

``` mermaid
flowchart TD
    Spill["Spill location + timestamp"]
    Weather["ERA5 weather"]
    Ocean["Copernicus ocean"]
    Spatial["Spatial interpolation / nearest grid"]
    Temporal["Temporal alignment"]
    Features["Environmental feature vector"]

    Weather --> Spatial
    Ocean --> Spatial
    Spill --> Spatial

    Spatial --> Temporal
    Spill --> Temporal
    Temporal --> Features
```

## 10.3 Functions

``` python
load_era5_data(path)
load_copernicus_data(path)
extract_wind_features(weather_df)
extract_current_features(ocean_df)
calculate_wind_components(speed, direction)
calculate_current_components(speed, direction)
align_environmental_timestamp(df, target_time)
select_spatial_environment_window(df, lat, lon, radius_km)
interpolate_environmental_values(df, lat, lon, timestamp)
build_environmental_feature_vector(weather, ocean)
validate_environmental_coverage(features)
calculate_environmental_quality_score(features)
```

------------------------------------------------------------------------

# 11. Drift / Hindcasting / Forecasting Layer

## 11.1 Objective

Estimate where the spill could have come from and where it may move.

Two modes:

``` text
Hindcast:
Observed spill
    ↓ backward in time
Probable origin

Forecast:
Observed spill
    ↓ forward in time
Predicted affected region
```

## 11.2 First implementation

The recommended prototype should use a **physics/geospatial
approximation**, rather than forcing a neural network into the task.

Conceptually:

``` text
Current position
+
Wind vector
+
Current vector
+
Time step
+
Drift coefficients
        |
        v
Next estimated position
```

## 11.3 Functions

``` python
build_wind_vector(speed, direction)
build_current_vector(speed, direction)
combine_drift_vectors(wind_vector, current_vector, coefficients)
propagate_particle(position, velocity, dt_hours)
propagate_trajectory(start_position, environmental_series, config)
run_hindcast(spill_geometry, environmental_data, config)
run_forecast(spill_geometry, environmental_data, horizon_hours, config)
estimate_probable_origin(hindcast_trajectory, observed_geometry)
estimate_future_spread(forecast_trajectory, spill_geometry)
generate_drift_path(trajectory)
calculate_drift_uncertainty(trajectory, environmental_quality)
build_origin_result(origin, uncertainty, timestamp)
validate_drift_result(result)
```

## 11.4 Important limitation

A prototype drift model is **not an industrial oil-spill simulator**.

Real oil behaviour can involve:

-   evaporation
-   emulsification
-   weathering
-   diffusion
-   wave effects
-   changing currents
-   oil type/properties

Therefore the system should communicate:

``` text
Probable origin
Confidence / uncertainty
```

rather than:

``` text
Exact spill origin
```

------------------------------------------------------------------------

# 12. AIS Processing Layer

## 12.1 Objective

Identify vessels that could plausibly have been associated with the
probable origin.

``` text
Probable origin
      +
Origin time
      |
      v
Spatial filter
      +
Temporal filter
      |
      v
Candidate vessels
```

## 12.2 Functions

``` python
load_ais_data(path)
clean_ais_data(df)
validate_ais_records(df)
filter_ais_by_time(df, start_time, end_time)
filter_ais_by_bbox(df, bbox)
filter_ais_by_radius(df, centre, radius_km)
sort_vessel_tracks(df)
group_records_by_mmsi(df)
build_vessel_trajectory(track)
interpolate_vessel_position(track, timestamp)
calculate_vessel_distance_to_origin(track, origin)
calculate_time_difference(track, origin_time)
calculate_track_length(track)
calculate_average_speed(track)
calculate_heading_change(track)
calculate_speed_change(track)
detect_course_anomalies(track)
detect_speed_anomalies(track)
calculate_path_proximity(track, spill_path)
```

------------------------------------------------------------------------

# 13. AIS Spatial and Temporal Correlation

## 13.1 Candidate search

A vessel is a candidate when it satisfies a set of conditions.

Example:

``` text
Distance to probable origin < search radius
AND
timestamp lies inside investigation window
```

Additional evidence can then be calculated.

## 13.2 Functions

``` python
build_ais_search_window(origin, origin_time, config)
find_candidate_vessels(ais_df, origin, origin_time, config)
calculate_spatial_match(vessel_track, origin)
calculate_temporal_match(vessel_track, origin_time)
calculate_trajectory_match(vessel_track, drift_path)
calculate_origin_intersection(track, origin_region)
calculate_behaviour_features(track)
build_candidate_vessel_features(track, origin, drift_result)
validate_candidate_coverage(candidates)
```

------------------------------------------------------------------------

# 14. Vessel Attribution / Ranking Layer

## 14.1 Principle

Do **not** use:

``` text
nearest vessel = culprit
```

Instead:

``` text
Candidate vessel
      |
      +--> Distance
      +--> Time difference
      +--> Trajectory match
      +--> Heading compatibility
      +--> Speed compatibility
      +--> Path proximity
      +--> Behavioural anomalies
      |
      v
Evidence vector
      |
      v
Weighted scoring
      |
      v
Ranked candidates
```

## 14.2 Evidence features

Recommended features:

  -----------------------------------------------------------------------
  Feature                             Meaning
  ----------------------------------- -----------------------------------
  `distance_score`                    How close the vessel was to the
                                      estimated origin

  `time_score`                        How closely vessel timing matches
                                      the inferred origin time

  `trajectory_score`                  Consistency between vessel route
                                      and spill drift

  `heading_score`                     Compatibility of vessel heading
                                      with the event

  `speed_score`                       Compatibility of vessel speed with
                                      the event

  `path_proximity_score`              How closely vessel path approaches
                                      the spill/origin

  `behaviour_score`                   Sudden speed/course changes or
                                      unusual behaviour

  `vessel_type_score`                 Contextual relevance of vessel type
  -----------------------------------------------------------------------

## 14.3 Weighted score

A prototype can use:

``` text
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

Weights must be configuration values, not hard-coded throughout the
application.

## 14.4 Functions

``` python
normalise_attribution_features(features)
calculate_distance_score(distance_km, config)
calculate_time_score(delta_minutes, config)
calculate_trajectory_score(track, drift_result)
calculate_heading_score(track, drift_result)
calculate_speed_score(track, expected_profile)
calculate_path_proximity_score(track, spill_geometry)
calculate_behaviour_score(track)
calculate_vessel_type_score(vessel_type, config)
calculate_evidence_score(features, weights)
calculate_data_quality_score(candidate)
calculate_attribution_confidence(ranked_candidates, data_quality)
rank_candidate_vessels(candidates, weights)
build_attribution_evidence(candidate)
build_attribution_result(ranked_candidates, confidence)
validate_attribution_result(result)
```

------------------------------------------------------------------------

# 15. Confidence and Data Availability Layer

This layer is critical.

## 15.1 States

``` text
FULL
PARTIAL
INSUFFICIENT
UNAVAILABLE
```

## 15.2 Decision flow

``` mermaid
flowchart TD
    Spill["Oil spill detected"]
    AISQ{"AIS coverage sufficient?"}
    ENVQ{"Environmental data sufficient?"}
    EVID{"Evidence sufficient?"}

    Full["Full attribution analysis"]
    Partial["Reduced-confidence analysis"]
    Unavailable["Attribution unavailable"]

    Spill --> AISQ

    AISQ -->|No| Unavailable
    AISQ -->|Partial| Partial
    AISQ -->|Yes| ENVQ

    ENVQ -->|No| Partial
    ENVQ -->|Yes| EVID

    EVID -->|No| Unavailable
    EVID -->|Yes| Full
```

## 15.3 Functions

``` python
assess_ais_coverage(ais_df, origin, time_window)
assess_environmental_coverage(environmental_data)
assess_satellite_quality(scene)
assess_evidence_quality(features)
calculate_overall_data_quality(quality_components)
determine_attribution_status(quality)
calculate_confidence_band(score, quality)
build_confidence_explanation(result)
```

## 15.4 Correct behaviour

### Full

``` text
AIS Coverage: Full
Attribution: Available
Confidence: High / Medium / Low
```

### Partial

``` text
AIS Coverage: Partial
Attribution: Available with reduced confidence
```

### Unavailable

``` text
AIS Coverage: Insufficient
Attribution: Unavailable
Reason: insufficient vessel evidence
```

------------------------------------------------------------------------

# 16. Application / Orchestration Layer

The orchestration layer coordinates the pipeline.

It should **not** contain all the algorithms itself.

Bad:

``` python
run_everything()
```

with 1,000 lines of code.

Better:

``` text
orchestrator
    |
    +--> acquisition service
    +--> satellite service
    +--> segmentation service
    +--> characterisation service
    +--> environmental service
    +--> drift service
    +--> AIS service
    +--> attribution service
    +--> confidence service
```

## Functions

``` python
create_incident(request)
validate_incident_request(request)
run_incident_pipeline(incident_id)
run_detection_stage(incident)
run_characterisation_stage(incident, mask)
run_environment_stage(incident, geometry)
run_hindcast_stage(incident, geometry, environment)
run_forecast_stage(incident, geometry, environment)
run_ais_stage(incident, origin)
run_attribution_stage(incident, origin, candidates)
run_confidence_stage(incident, result)
build_dashboard_result(incident)
persist_incident_result(result)
```

------------------------------------------------------------------------

# 17. End-to-End Pipeline

``` mermaid
sequenceDiagram
    actor User as Analyst / Authority
    participant UI as Streamlit Dashboard
    participant API as Application Layer
    participant SAT as Satellite Processor
    participant SEG as U-Net
    participant GEO as Characterisation
    participant ENV as Environmental Processor
    participant DRIFT as Drift Engine
    participant AIS as AIS Processor
    participant ATTR as Attribution Engine
    participant CONF as Confidence Engine
    participant STORE as Result Store

    User->>UI: Select incident / upload scene
    UI->>API: create_incident()

    API->>SAT: load_sar_scene()
    SAT-->>API: model-ready satellite image

    API->>SEG: predict_spill_mask()
    SEG-->>API: probability + binary mask

    API->>GEO: build_spill_geometry()
    GEO-->>API: area + polygon + centroid + extent

    API->>ENV: build_environmental_feature_vector()
    ENV-->>API: wind + current features

    API->>DRIFT: run_hindcast()
    DRIFT-->>API: probable origin + uncertainty

    API->>DRIFT: run_forecast()
    DRIFT-->>API: future trajectory / affected region

    API->>AIS: find_candidate_vessels()
    AIS-->>API: candidate tracks

    API->>ATTR: rank_candidate_vessels()
    ATTR-->>API: ranked candidates + evidence

    API->>CONF: calculate_attribution_confidence()
    CONF-->>API: confidence + availability status

    API->>STORE: persist_incident_result()
    STORE-->>API: saved result

    API-->>UI: build_dashboard_result()
    UI-->>User: map + spill + origin + vessels + forecast
```

------------------------------------------------------------------------

# 18. Dashboard Architecture

The dashboard should expose the **results of the pipeline**, not the
internal implementation.

## 18.1 Main screen

``` text
+-----------------------------------------------------------+
| OILSPILL INTELLIGENCE                                     |
+-----------------------------------------------------------+
| Incident | Date | Location | Data Quality | Confidence   |
+-----------------------------------------------------------+
|                                                           |
|                    INTERACTIVE MAP                        |
|                                                           |
|  Spill Mask       Probable Origin       Vessel Tracks    |
|  Forecast Region  Hindcast Path         Search Radius    |
|                                                           |
+---------------------------+-------------------------------+
| Spill Metrics             | Attribution                   |
| Area                      | Rank  Vessel  Score  Evidence |
| Perimeter                 | 1     A       0.87   Strong   |
| Centroid                  | 2     B       0.61   Moderate |
| Orientation               | 3     C       0.34   Weak     |
+---------------------------+-------------------------------+
| Environmental Conditions  | Confidence / Data Status    |
| Wind                      | AIS: FULL                   |
| Current                   | Weather: GOOD               |
| Drift                     | Ocean: GOOD                 |
+-----------------------------------------------------------+
```

## 18.2 Dashboard functions

``` python
render_dashboard()
render_incident_selector()
render_incident_summary()
render_spill_map()
render_spill_mask_layer()
render_hindcast_layer()
render_forecast_layer()
render_vessel_tracks()
render_origin_marker()
render_search_radius()
render_spill_metrics()
render_environmental_panel()
render_vessel_ranking_table()
render_attribution_evidence()
render_confidence_panel()
render_data_availability_status()
export_incident_report()
```

------------------------------------------------------------------------

# 19. Map Layer Architecture

The map should contain independent layers.

``` mermaid
flowchart TB
    Map["Interactive Map"]

    Base["Base Map"]
    Spill["Detected Spill Polygon"]
    Origin["Probable Origin"]
    Hind["Hindcast Path"]
    Forecast["Forecast Path / Region"]
    AIS["AIS Vessel Tracks"]
    Candidates["Candidate Vessel Markers"]
    Search["AIS Search Area"]
    Env["Optional Environmental Layers"]

    Base --> Map
    Spill --> Map
    Origin --> Map
    Hind --> Map
    Forecast --> Map
    AIS --> Map
    Candidates --> Map
    Search --> Map
    Env --> Map
```

## Functions

``` python
create_base_map(center, zoom)
add_spill_polygon(map_obj, polygon)
add_origin_marker(map_obj, origin)
add_hindcast_layer(map_obj, trajectory)
add_forecast_layer(map_obj, trajectory)
add_forecast_region(map_obj, polygon)
add_ais_track_layer(map_obj, tracks)
add_candidate_markers(map_obj, candidates)
add_search_radius(map_obj, centre, radius_km)
add_environmental_layer(map_obj, layer)
configure_map_legend(map_obj)
```

------------------------------------------------------------------------

# 20. Data Model

A relational or structured persistence layer should maintain the
relationship between an incident and its derived artefacts.

## 20.1 Incident

``` text
Incident
--------
incident_id
created_at
event_timestamp
latitude
longitude
source_scene
status
```

## 20.2 SatelliteScene

``` text
SatelliteScene
--------------
scene_id
incident_id
source
acquisition_time
file_path
crs
bounds
quality_score
```

## 20.3 SpillDetection

``` text
SpillDetection
--------------
detection_id
incident_id
model_version
mask_path
probability_threshold
detection_confidence
```

## 20.4 SpillGeometry

``` text
SpillGeometry
-------------
geometry_id
incident_id
area_km2
perimeter_km
centroid_lat
centroid_lon
orientation_deg
bounding_box
polygon
```

## 20.5 EnvironmentalObservation

``` text
EnvironmentalObservation
------------------------
observation_id
incident_id
timestamp
latitude
longitude
wind_speed
wind_direction
current_speed
current_direction
data_source
quality_score
```

## 20.6 DriftResult

``` text
DriftResult
-----------
drift_id
incident_id
mode
start_time
end_time
origin_lat
origin_lon
trajectory
uncertainty
model_version
```

## 20.7 Vessel

``` text
Vessel
------
mmsi
name
vessel_type
flag
length
other_metadata
```

## 20.8 VesselTrack

``` text
VesselTrack
-----------
track_id
incident_id
mmsi
start_time
end_time
trajectory
record_count
coverage_score
```

## 20.9 AttributionResult

``` text
AttributionResult
-----------------
attribution_id
incident_id
mmsi
rank
score
confidence
distance_score
time_score
trajectory_score
heading_score
speed_score
path_proximity_score
behaviour_score
vessel_type_score
evidence_summary
```

------------------------------------------------------------------------

# 21. Recommended Data Relationships

``` mermaid
erDiagram
    INCIDENT ||--o{ SATELLITE_SCENE : contains
    INCIDENT ||--o{ SPILL_DETECTION : produces
    INCIDENT ||--|| SPILL_GEOMETRY : has
    INCIDENT ||--o{ ENVIRONMENTAL_OBSERVATION : uses
    INCIDENT ||--o{ DRIFT_RESULT : produces
    INCIDENT ||--o{ VESSEL_TRACK : analyses
    VESSEL ||--o{ VESSEL_TRACK : owns
    INCIDENT ||--o{ ATTRIBUTION_RESULT : produces
    VESSEL ||--o{ ATTRIBUTION_RESULT : candidate

    INCIDENT {
        string incident_id PK
        datetime event_timestamp
        float latitude
        float longitude
        string status
    }

    SATELLITE_SCENE {
        string scene_id PK
        string incident_id FK
        string source
        datetime acquisition_time
        string file_path
    }

    SPILL_DETECTION {
        string detection_id PK
        string incident_id FK
        string model_version
        float confidence
        string mask_path
    }

    SPILL_GEOMETRY {
        string geometry_id PK
        string incident_id FK
        float area_km2
        float perimeter_km
        float centroid_lat
        float centroid_lon
    }

    VESSEL {
        string mmsi PK
        string name
        string vessel_type
    }

    VESSEL_TRACK {
        string track_id PK
        string incident_id FK
        string mmsi FK
        datetime start_time
        datetime end_time
    }

    ATTRIBUTION_RESULT {
        string attribution_id PK
        string incident_id FK
        string mmsi FK
        int rank
        float score
        string confidence
    }
```

------------------------------------------------------------------------

# 22. API Contract

If the system is exposed through a Python API layer, the following
endpoints provide a clean contract.

## 22.1 Incident management

``` http
POST /api/v1/incidents
GET  /api/v1/incidents
GET  /api/v1/incidents/{incident_id}
DELETE /api/v1/incidents/{incident_id}
```

Functions:

``` python
create_incident_endpoint()
list_incidents_endpoint()
get_incident_endpoint(incident_id)
delete_incident_endpoint(incident_id)
```

## 22.2 Detection

``` http
POST /api/v1/incidents/{incident_id}/detect
GET  /api/v1/incidents/{incident_id}/detection
```

Functions:

``` python
detect_spill_endpoint(incident_id)
get_detection_endpoint(incident_id)
```

## 22.3 Characterisation

``` http
POST /api/v1/incidents/{incident_id}/characterise
GET  /api/v1/incidents/{incident_id}/geometry
```

Functions:

``` python
characterise_spill_endpoint(incident_id)
get_spill_geometry_endpoint(incident_id)
```

## 22.4 Drift

``` http
POST /api/v1/incidents/{incident_id}/hindcast
POST /api/v1/incidents/{incident_id}/forecast
GET  /api/v1/incidents/{incident_id}/drift
```

Functions:

``` python
run_hindcast_endpoint(incident_id)
run_forecast_endpoint(incident_id)
get_drift_endpoint(incident_id)
```

## 22.5 AIS

``` http
POST /api/v1/incidents/{incident_id}/ais/search
GET  /api/v1/incidents/{incident_id}/vessels
```

Functions:

``` python
search_ais_endpoint(incident_id)
get_candidate_vessels_endpoint(incident_id)
```

## 22.6 Attribution

``` http
POST /api/v1/incidents/{incident_id}/attribute
GET  /api/v1/incidents/{incident_id}/attribution
```

Functions:

``` python
run_attribution_endpoint(incident_id)
get_attribution_endpoint(incident_id)
```

## 22.7 Dashboard

``` http
GET /api/v1/incidents/{incident_id}/dashboard
GET /api/v1/incidents/{incident_id}/map
```

Functions:

``` python
get_dashboard_payload_endpoint(incident_id)
get_map_payload_endpoint(incident_id)
```

------------------------------------------------------------------------

# 23. Complete Function Catalogue

This is the consolidated function-level implementation contract.

## Data ingestion

``` python
load_satellite_image()
load_sar_scene()
load_ais_data()
load_weather_data()
load_ocean_current_data()
validate_satellite_metadata()
validate_ais_schema()
validate_coordinates()
validate_timestamps()
normalise_ais_columns()
normalise_environment_columns()
record_data_provenance()
```

## Satellite

``` python
read_sar_metadata()
select_sar_bands()
crop_to_aoi()
clip_raster_to_bounds()
reproject_raster()
normalise_sar_image()
standardise_model_input()
prepare_segmentation_tensor()
validate_satellite_scene()
```

## U-Net

``` python
build_unet()
load_segmentation_dataset()
split_segmentation_dataset()
apply_joint_augmentation()
normalise_training_image()
train_unet()
validate_unet()
calculate_iou()
calculate_dice_score()
calculate_pixel_accuracy()
save_model_weights()
load_model_weights()
predict_spill_mask()
postprocess_spill_mask()
threshold_probability_mask()
```

## Spill geometry

``` python
clean_spill_mask()
remove_small_components()
extract_spill_components()
extract_spill_contours()
calculate_pixel_area()
calculate_spill_area()
calculate_perimeter()
calculate_bounding_box()
calculate_centroid()
calculate_orientation()
mask_to_polygon()
simplify_spill_polygon()
calculate_spill_extent()
calculate_shape_features()
build_spill_geometry()
validate_spill_geometry()
```

## Environmental processing

``` python
load_era5_data()
load_copernicus_data()
extract_wind_features()
extract_current_features()
calculate_wind_components()
calculate_current_components()
align_environmental_timestamp()
select_spatial_environment_window()
interpolate_environmental_values()
build_environmental_feature_vector()
validate_environmental_coverage()
calculate_environmental_quality_score()
```

## Drift

``` python
build_wind_vector()
build_current_vector()
combine_drift_vectors()
propagate_particle()
propagate_trajectory()
run_hindcast()
run_forecast()
estimate_probable_origin()
estimate_future_spread()
generate_drift_path()
calculate_drift_uncertainty()
build_origin_result()
validate_drift_result()
```

## AIS

``` python
clean_ais_data()
validate_ais_records()
filter_ais_by_time()
filter_ais_by_bbox()
filter_ais_by_radius()
sort_vessel_tracks()
group_records_by_mmsi()
build_vessel_trajectory()
interpolate_vessel_position()
calculate_vessel_distance_to_origin()
calculate_time_difference()
calculate_track_length()
calculate_average_speed()
calculate_heading_change()
calculate_speed_change()
detect_course_anomalies()
detect_speed_anomalies()
calculate_path_proximity()
```

## AIS correlation

``` python
build_ais_search_window()
find_candidate_vessels()
calculate_spatial_match()
calculate_temporal_match()
calculate_trajectory_match()
calculate_origin_intersection()
calculate_behaviour_features()
build_candidate_vessel_features()
validate_candidate_coverage()
```

## Attribution

``` python
normalise_attribution_features()
calculate_distance_score()
calculate_time_score()
calculate_trajectory_score()
calculate_heading_score()
calculate_speed_score()
calculate_path_proximity_score()
calculate_behaviour_score()
calculate_vessel_type_score()
calculate_evidence_score()
calculate_data_quality_score()
calculate_attribution_confidence()
rank_candidate_vessels()
build_attribution_evidence()
build_attribution_result()
validate_attribution_result()
```

## Confidence

``` python
assess_ais_coverage()
assess_environmental_coverage()
assess_satellite_quality()
assess_evidence_quality()
calculate_overall_data_quality()
determine_attribution_status()
calculate_confidence_band()
build_confidence_explanation()
```

## Orchestration

``` python
create_incident()
validate_incident_request()
run_incident_pipeline()
run_detection_stage()
run_characterisation_stage()
run_environment_stage()
run_hindcast_stage()
run_forecast_stage()
run_ais_stage()
run_attribution_stage()
run_confidence_stage()
build_dashboard_result()
persist_incident_result()
```

## Dashboard

``` python
render_dashboard()
render_incident_selector()
render_incident_summary()
render_spill_map()
render_spill_mask_layer()
render_hindcast_layer()
render_forecast_layer()
render_vessel_tracks()
render_origin_marker()
render_search_radius()
render_spill_metrics()
render_environmental_panel()
render_vessel_ranking_table()
render_attribution_evidence()
render_confidence_panel()
render_data_availability_status()
export_incident_report()
```

------------------------------------------------------------------------

# 24. Training-Time vs Inference-Time Architecture

This distinction is important.

## 24.1 Training

``` mermaid
flowchart LR
    Dataset["Labelled Sentinel-1 Dataset"]
    Prep["Preprocessing"]
    Aug["Joint Augmentation"]
    Train["U-Net Training"]
    Eval["Validation"]
    Weights["Versioned Model Weights"]

    Dataset --> Prep
    Prep --> Aug
    Aug --> Train
    Train --> Eval
    Eval --> Weights
```

Training is an offline process.

## 24.2 Inference

``` mermaid
flowchart LR
    Scene["New Satellite Scene"]
    Prep["Preprocess"]
    Model["Loaded U-Net"]
    Mask["Spill Mask"]
    Geo["Geometry"]
    Drift["Drift"]
    AIS["AIS"]
    Rank["Attribution"]
    UI["Dashboard"]

    Scene --> Prep --> Model --> Mask --> Geo
    Geo --> Drift
    Drift --> AIS
    AIS --> Rank
    Rank --> UI
    Geo --> UI
    Drift --> UI
    Mask --> UI
```

The model is **not retrained for every incident**.

------------------------------------------------------------------------

# 25. Complete Incident Execution

``` mermaid
flowchart TD
    A["Incident created"] --> B["Validate metadata"]
    B --> C["Load Sentinel-1 scene"]
    C --> D["Preprocess SAR"]
    D --> E["U-Net inference"]
    E --> F["Oil probability mask"]
    F --> G["Binary mask"]
    G --> H["Spill geometry"]

    H --> I["Area / perimeter / centroid / polygon"]

    I --> J["Load environmental data"]
    J --> K["Temporal + spatial alignment"]
    K --> L["Hindcast"]
    K --> M["Forecast"]

    L --> N["Probable origin"]
    M --> O["Future affected region"]

    N --> P["AIS spatial + temporal search"]
    P --> Q["Candidate vessels"]
    Q --> R["Feature engineering"]
    R --> S["Weighted evidence scoring"]
    S --> T["Ranked vessels"]

    N --> U["Confidence assessment"]
    T --> U
    K --> U
    E --> U

    U --> V["Final incident result"]
    V --> W["Dashboard"]
```

------------------------------------------------------------------------

# 26. Error Handling

Every pipeline stage should fail explicitly.

## Example

``` python
try:
    mask = predict_spill_mask(model, image)
except ModelInferenceError:
    return {
        "status": "detection_failed",
        "reason": "segmentation inference failed"
    }
```

Do not silently continue with invalid data.

## Required error categories

``` text
DATA_NOT_FOUND
INVALID_SCHEMA
INVALID_COORDINATES
INVALID_TIMESTAMP
SATELLITE_PROCESSING_FAILED
MODEL_LOAD_FAILED
MODEL_INFERENCE_FAILED
EMPTY_SPILL_DETECTION
GEOMETRY_PROCESSING_FAILED
ENVIRONMENT_DATA_UNAVAILABLE
DRIFT_MODEL_FAILED
AIS_DATA_UNAVAILABLE
AIS_DATA_INSUFFICIENT
ATTRIBUTION_INSUFFICIENT_EVIDENCE
RESULT_PERSISTENCE_FAILED
```

------------------------------------------------------------------------

# 27. Logging

Every incident should produce an audit trail.

Example:

``` text
2026-09-11T10:15:00Z INFO  incident_created id=INC-001
2026-09-11T10:15:03Z INFO  satellite_loaded scene=S1-...
2026-09-11T10:15:06Z INFO  segmentation_complete confidence=0.91
2026-09-11T10:15:07Z INFO  geometry_complete area_km2=14.7
2026-09-11T10:15:08Z INFO  environmental_alignment_complete
2026-09-11T10:15:10Z INFO  hindcast_complete
2026-09-11T10:15:11Z INFO  ais_candidates count=17
2026-09-11T10:15:12Z INFO  attribution_complete top_score=0.82
2026-09-11T10:15:12Z INFO  incident_complete
```

Sensitive or unnecessary raw data should not be logged.

------------------------------------------------------------------------

# 28. Model Versioning

Every result should identify the model version used.

Example:

``` text
model:
    name: oilspill-unet
    version: 1.0.0
    weights: unet_sentinel1_v1.pt
```

This matters because if the model is retrained later, historical results
must remain interpretable.

Recommended:

``` python
get_model_version()
load_model_registry()
validate_model_compatibility()
record_model_version()
```

------------------------------------------------------------------------

# 29. Configuration

Weights, thresholds and search windows should be configurable.

Example:

``` yaml
segmentation:
  probability_threshold: 0.50
  minimum_component_area: 100

hindcast:
  hours_back: 24
  timestep_hours: 1

forecast:
  hours_forward: 24
  timestep_hours: 1

ais:
  spatial_radius_km: 25
  temporal_window_hours: 12

attribution:
  weights:
    distance: 0.20
    time: 0.20
    trajectory: 0.20
    heading: 0.10
    speed: 0.10
    path_proximity: 0.10
    behaviour: 0.05
    vessel_type: 0.05
```

Functions:

``` python
load_config()
validate_config()
get_segmentation_config()
get_drift_config()
get_ais_config()
get_attribution_weights()
```

------------------------------------------------------------------------

# 30. Testing Strategy

## 30.1 Unit tests

Test every deterministic component independently.

Examples:

``` python
test_calculate_centroid()
test_calculate_spill_area()
test_build_wind_vector()
test_build_current_vector()
test_calculate_time_score()
test_calculate_distance_score()
test_filter_ais_by_radius()
```

## 30.2 Model tests

``` python
test_unet_output_shape()
test_unet_mask_range()
test_segmentation_threshold()
test_iou_calculation()
test_dice_calculation()
```

## 30.3 Integration tests

``` text
Satellite
 -> U-Net
 -> Geometry
 -> Drift
 -> AIS
 -> Attribution
```

The objective is to ensure the data contract between stages is correct.

## 30.4 Failure-path tests

Explicitly test:

``` text
No satellite image
No spill detected
Bad coordinates
Missing wind data
Missing current data
No AIS data
Partial AIS data
No candidate vessels
Insufficient evidence
```

------------------------------------------------------------------------

# 31. Security and Integrity

Even though this is primarily a scientific/geospatial system, integrity
is essential.

## Requirements

-   Validate uploaded files.
-   Restrict accepted file types.
-   Validate raster dimensions.
-   Validate coordinate ranges.
-   Never trust client-provided metadata blindly.
-   Keep configuration separate from source code.
-   Keep credentials/API keys outside Git.
-   Record provenance for external datasets.
-   Keep model weights versioned.
-   Make attribution outputs auditable.

Most importantly:

> A model score must never be presented as legal proof of
> responsibility.

------------------------------------------------------------------------

# 32. Explainability

The final attribution should show **why** a vessel was ranked highly.

Example:

``` text
Rank: 1
MMSI: 123456789
Score: 0.82
Confidence: Medium

Evidence:
✓ 2.1 km from probable origin
✓ Strong temporal match
✓ Trajectory intersects inferred drift corridor
✓ Heading compatible
✓ Moderate behavioural anomaly

Data quality:
AIS: Partial
Weather: Good
Ocean: Good
```

This is substantially more defensible than:

``` text
Vessel A caused the spill: 82%
```

------------------------------------------------------------------------

# 33. What Each Technology Actually Does

  ---------------------------------------------------------------------------
  Technology              Used for                    Not used for
  ----------------------- --------------------------- -----------------------
  Python                  Main application/data/ML    ---
                          language                    

  PyTorch                 U-Net segmentation          AIS database

  U-Net                   Pixel-level oil detection   Vessel identification

  Pandas                  Tabular data processing     Deep learning

  NumPy                   Numerical/raster            Dashboard
                          calculations                

  OpenCV                  Image/mask processing       AIS attribution by
                                                      itself

  GeoPandas               Geospatial analysis         Model training itself

  QGIS                    GIS inspection/validation   Production inference
                                                      engine

  Streamlit               Dashboard/UI                Model training

  Folium/Leaflet          Interactive maps            Segmentation

  ERA5                    Weather/wind inputs         AIS

  Copernicus              Oceanographic inputs        Vessel identity

  Sentinel-1              Satellite observation       Attribution

  AIS                     Vessel trajectories         Oil detection

  Google Earth Engine     Optional                    Required core runtime
                          data-access/preprocessing   dependency
                          route                       
  ---------------------------------------------------------------------------

------------------------------------------------------------------------

# 34. What Happens When AIS Is Missing?

``` mermaid
flowchart TD
    Detect["Oil spill detected"]
    Origin["Probable origin estimated"]
    Check{"AIS available?"}

    Full["Run vessel correlation"]
    Partial["Run reduced analysis"]
    Stop["Attribution unavailable"]

    Detect --> Origin --> Check
    Check -->|Full| Full
    Check -->|Partial| Partial
    Check -->|None| Stop

    Full --> Rank["Rank candidates"]
    Partial --> Low["Lower confidence"]
```

This is not a failure of the system.

It is an **explicit evidence-quality state**.

------------------------------------------------------------------------

# 35. What Happens When No Oil Is Detected?

``` mermaid
flowchart TD
    Scene["Satellite scene"] --> Model["U-Net"]
    Model --> Mask["Probability mask"]
    Mask --> Threshold{"Spill above threshold?"}

    Threshold -->|No| NoSpill["No confirmed spill"]
    Threshold -->|Yes| Continue["Continue pipeline"]

    NoSpill --> End["Stop incident processing"]
    Continue --> Geometry["Characterise spill"]
```

There is no reason to run AIS attribution if there is no credible spill.

------------------------------------------------------------------------

# 36. What Happens If Environmental Data Is Missing?

``` text
Spill detected
     |
     v
Environmental data?
   /          \
 YES           NO
 |             |
 v             v
Hindcast      Hindcast unavailable
Forecast      Forecast unavailable
 |             |
 v             v
Origin        Attribution may have
estimate      reduced/insufficient confidence
```

The system should distinguish:

``` text
No environmental data
```

from:

``` text
Environmental data exists but has low quality.
```

------------------------------------------------------------------------

# 37. Recommended Repository Structure

``` text
oilspill/
│
├── app/
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   └── orchestrator.py
│
├── data/
│   ├── raw/
│   │   ├── satellite/
│   │   ├── ais/
│   │   ├── weather/
│   │   └── ocean/
│   │
│   ├── processed/
│   │   ├── satellite/
│   │   ├── ais/
│   │   ├── weather/
│   │   └── ocean/
│   │
│   └── outputs/
│
├── models/
│   └── segmentation/
│       ├── unet.py
│       ├── dataset.py
│       ├── train.py
│       ├── evaluate.py
│       └── weights/
│
├── services/
│   ├── satellite_service.py
│   ├── segmentation_service.py
│   ├── geometry_service.py
│   ├── environment_service.py
│   ├── drift_service.py
│   ├── ais_service.py
│   ├── attribution_service.py
│   ├── confidence_service.py
│   └── report_service.py
│
├── geospatial/
│   ├── projections.py
│   ├── geometry.py
│   └── mapping.py
│
├── dashboard/
│   ├── app.py
│   ├── components/
│   ├── maps/
│   └── charts/
│
├── api/
│   ├── incidents.py
│   ├── detection.py
│   ├── geometry.py
│   ├── drift.py
│   ├── ais.py
│   └── attribution.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── configs/
│   └── default.yaml
│
├── notebooks/
│   ├── data_exploration/
│   ├── segmentation/
│   ├── drift/
│   └── ais/
│
├── scripts/
│   ├── download_data.py
│   ├── preprocess_data.py
│   └── evaluate_pipeline.py
│
├── requirements.txt
├── README.md
└── SYSTEM_ARCHITECTURE.md
```

------------------------------------------------------------------------

# 38. Recommended Dependency Direction

A major engineering rule:

``` text
dashboard
    ↓
api
    ↓
orchestrator
    ↓
services
    ↓
domain/geospatial/model utilities
```

Do not allow:

``` text
dashboard
    ↓
directly manipulates
    ↓
U-Net internals
```

or:

``` text
AIS service
    ↓
directly modifies
    ↓
dashboard state
```

Instead:

``` text
AIS service
    ↓
CandidateVesselResult
    ↓
orchestrator
    ↓
DashboardPayload
```

------------------------------------------------------------------------

# 39. Dependency Graph

``` mermaid
flowchart TD
    UI["Dashboard"]

    API["API Layer"]
    ORCH["Orchestrator"]

    SAT["Satellite Service"]
    SEG["Segmentation Service"]
    GEO["Geometry Service"]
    ENV["Environment Service"]
    DRIFT["Drift Service"]
    AIS["AIS Service"]
    ATTR["Attribution Service"]
    CONF["Confidence Service"]
    STORE["Persistence"]

    UI --> API
    API --> ORCH

    ORCH --> SAT
    ORCH --> SEG
    ORCH --> GEO
    ORCH --> ENV
    ORCH --> DRIFT
    ORCH --> AIS
    ORCH --> ATTR
    ORCH --> CONF
    ORCH --> STORE

    SEG --> GEO
    GEO --> DRIFT
    ENV --> DRIFT
    DRIFT --> ATTR
    AIS --> ATTR
    ATTR --> CONF
```

------------------------------------------------------------------------

# 40. Core Domain Objects

The following objects are recommended as the stable contracts between
services.

``` python
SatelliteScene
SegmentationResult
SpillGeometry
EnvironmentalFeatures
DriftResult
VesselTrack
CandidateVessel
AttributionEvidence
AttributionResult
ConfidenceAssessment
IncidentResult
DashboardPayload
```

Example:

``` python
class SegmentationResult:
    incident_id: str
    mask_path: str
    probability_map_path: str
    confidence: float
    model_version: str
```

``` python
class SpillGeometry:
    incident_id: str
    area_km2: float
    perimeter_km: float
    centroid_lat: float
    centroid_lon: float
    orientation_deg: float
    polygon: object
```

``` python
class AttributionResult:
    incident_id: str
    ranked_vessels: list
    status: str
    confidence: str
    evidence_quality: float
```

------------------------------------------------------------------------

# 41. End-to-End Output Contract

The dashboard should ultimately receive a single structured result.

Conceptually:

``` json
{
  "incident": {
    "id": "INC-001",
    "timestamp": "...",
    "location": {
      "lat": 15.21,
      "lon": 65.42
    }
  },

  "spill": {
    "detected": true,
    "confidence": 0.91,
    "area_km2": 14.7,
    "polygon": "...",
    "centroid": [15.21, 65.42]
  },

  "origin": {
    "available": true,
    "location": [15.12, 65.18],
    "time": "...",
    "uncertainty": "medium"
  },

  "forecast": {
    "available": true,
    "trajectory": "...",
    "affected_region": "..."
  },

  "ais": {
    "status": "PARTIAL",
    "candidate_count": 8
  },

  "attribution": {
    "status": "AVAILABLE_WITH_REDUCED_CONFIDENCE",
    "confidence": "MEDIUM",
    "ranked_vessels": []
  }
}
```

------------------------------------------------------------------------

# 42. Engineering Decisions

## Decision 1 --- U-Net rather than classification

**Reason:** The problem requires the location and shape of the spill,
not merely whether oil exists.

``` text
Classification:
Image -> oil/no oil

Segmentation:
Image -> exact oil pixels
```

## Decision 2 --- Geometry rather than another ML model

Area, perimeter, centroid and polygon extraction are deterministic and
interpretable.

No reason to introduce another neural network.

## Decision 3 --- Physics/geospatial drift before deep learning

The project needs a credible prototype and explainable movement model.

A deep-learning drift model would require substantial labelled
trajectory data and introduces unnecessary complexity.

## Decision 4 --- AIS + evidence scoring

Vessel attribution is an evidence-ranking problem.

The system should expose contributing evidence instead of outputting a
black-box accusation.

## Decision 5 --- Confidence is a first-class object

Confidence is not merely the segmentation model probability.

Overall confidence depends on:

``` text
Satellite quality
+
Segmentation quality
+
Environmental data quality
+
AIS coverage
+
Evidence consistency
```

------------------------------------------------------------------------

# 43. Critical Data Leakage Considerations

When training the segmentation model:

**Do not randomly split nearly identical patches from the same satellite
scene across train and test.**

Otherwise:

``` text
Same scene
  ├── train patch
  └── test patch
```

can produce artificially high performance.

Prefer scene-level or geographically separated splits where practical.

Likewise, if evaluating historical incidents, avoid allowing information
from the same incident to appear in both training and evaluation.

------------------------------------------------------------------------

# 44. Critical Geospatial Considerations

Do not calculate physical area from latitude/longitude degrees directly.

Bad:

``` python
area = width_degrees * height_degrees
```

Better:

``` text
Raster coordinates
    ↓
appropriate projected/geodesic calculation
    ↓
m² / km²
```

Likewise, ensure all datasets use an explicitly known CRS.

Functions:

``` python
get_crs()
transform_coordinates()
project_geometry()
calculate_geodesic_distance()
calculate_projected_area()
```

------------------------------------------------------------------------

# 45. Critical Temporal Considerations

All timestamps should be normalised.

Recommended:

``` text
UTC internally
```

Convert only for display.

Functions:

``` python
parse_timestamp()
normalise_timestamp_to_utc()
align_timestamp_window()
calculate_time_delta()
```

This is particularly important when correlating:

``` text
Satellite acquisition time
Weather time
Ocean current time
AIS timestamp
```

------------------------------------------------------------------------

# 46. Performance Strategy

The expensive operations are:

1.  Satellite preprocessing
2.  U-Net inference
3.  Large AIS filtering
4.  Spatial joins
5.  Drift propagation

Optimisations:

``` text
Pre-index AIS
Cache environmental grids
Process satellite scenes once
Cache segmentation results
Use vectorised NumPy/Pandas operations
Use GeoPandas spatial indexing
Avoid repeated full AIS scans
```

Recommended functions:

``` python
build_ais_spatial_index()
build_environmental_index()
cache_segmentation_result()
cache_environmental_window()
cache_drift_result()
```

------------------------------------------------------------------------

# 47. Caching Strategy

A deterministic pipeline stage should not be recomputed unnecessarily.

Example:

``` text
Same satellite scene
+
same model version
+
same preprocessing configuration
        |
        v
reuse segmentation result
```

Cache key:

``` text
hash(
    scene_id,
    model_version,
    preprocessing_version,
    threshold
)
```

Functions:

``` python
build_cache_key()
get_cached_result()
set_cached_result()
invalidate_cache()
```

------------------------------------------------------------------------

# 48. Observability

Track:

``` text
pipeline duration
stage duration
data coverage
model inference time
AIS candidate count
failure rate
confidence distribution
```

Functions:

``` python
start_stage_timer()
record_stage_duration()
record_pipeline_metric()
record_data_quality_metric()
record_model_metric()
record_pipeline_failure()
```

------------------------------------------------------------------------

# 49. Minimum Viable Demonstration

For an SIH demonstration, the complete path should be:

``` text
1. Select/upload Sentinel-1 scene
2. Run U-Net
3. Show oil mask
4. Calculate spill area/centroid
5. Load wind/current data
6. Run hindcast
7. Show probable origin
8. Load AIS
9. Show candidate vessels
10. Rank vessels
11. Show evidence
12. Show confidence
13. Show future forecast
```

The strongest demonstration is therefore not:

> "Here is our U-Net."

It is:

> **"Here is an observed spill. The system detects it, estimates where
> it originated, reconstructs its movement, correlates vessels that were
> in the relevant place and time, and ranks candidates based on multiple
> pieces of evidence."**

------------------------------------------------------------------------

# 50. Future Extensions

These should remain clearly labelled as future scope.

## 50.1 Incident Cause Analysis

Potential inputs:

``` text
AIS behaviour
+
spill geometry
+
environment
+
trajectory
```

Possible outputs:

``` text
Probable scenario:
collision
operational discharge
accidental release
unknown
```

This should remain probabilistic and evidence-based.

## 50.2 Marine Ecosystem Impact

Potential inputs:

``` text
spill extent
exposure duration
wind/current
distance to coast
sensitive ecological areas
```

Output:

``` text
environmental exposure / ecological risk score
```

Do not claim exact numbers of affected animals without a validated
ecological model.

------------------------------------------------------------------------

# 51. Final Architecture Summary

``` mermaid
flowchart TB
    subgraph INPUT["1. DATA INPUT"]
        S["Sentinel-1 SAR / EO"]
        A["Historical AIS"]
        W["ERA5 Weather"]
        O["Copernicus Ocean"]
    end

    subgraph DETECT["2. DETECT"]
        SP["Satellite preprocessing"]
        UNET["U-Net segmentation"]
        MASK["Oil spill mask"]
    end

    subgraph CHARACTERISE["3. CHARACTERISE"]
        GEO["Geometry extraction"]
        MET["Area / perimeter / centroid / polygon"]
    end

    subgraph TRACE["4. TRACE"]
        ENV["Environmental alignment"]
        HC["Hindcast"]
        FC["Forecast"]
        ORIGIN["Probable origin"]
        FUTURE["Future spread"]
    end

    subgraph ATTR["5. ATTRIBUTE"]
        AF["AIS spatial/temporal filtering"]
        CF["Candidate vessels"]
        FE["Evidence feature engineering"]
        SCORE["Weighted scoring"]
        RANK["Ranked vessels"]
    end

    subgraph CONF["6. VALIDATE"]
        CQ["Data quality"]
        CONFID["Confidence"]
        STATUS["Availability status"]
    end

    subgraph OUTPUT["7. VISUALISE"]
        MAP["Interactive map"]
        REPORT["Incident report"]
        DASH["Authority dashboard"]
    end

    S --> SP
    SP --> UNET
    UNET --> MASK
    MASK --> GEO
    GEO --> MET

    W --> ENV
    O --> ENV
    MET --> ENV
    ENV --> HC
    ENV --> FC
    GEO --> HC
    GEO --> FC

    HC --> ORIGIN
    FC --> FUTURE

    A --> AF
    ORIGIN --> AF
    AF --> CF
    CF --> FE
    ORIGIN --> FE
    HC --> FE
    FE --> SCORE
    SCORE --> RANK

    MASK --> CQ
    ENV --> CQ
    A --> CQ
    RANK --> CQ
    CQ --> CONFID
    CONFID --> STATUS

    MASK --> MAP
    MET --> MAP
    ORIGIN --> MAP
    HC --> MAP
    FUTURE --> MAP
    RANK --> MAP

    STATUS --> DASH
    MAP --> DASH
    CONFID --> DASH
    DASH --> REPORT
```

------------------------------------------------------------------------

# 52. Final Engineering Mental Model

The entire application can be understood as seven layers:

``` text
┌──────────────────────────────────────────────┐
│ 7. PRESENTATION                              │
│ Streamlit + Folium / Leaflet                 │
├──────────────────────────────────────────────┤
│ 6. DECISION / EVIDENCE                       │
│ Attribution + Confidence                     │
├──────────────────────────────────────────────┤
│ 5. CORRELATION                               │
│ AIS + Trajectory Analysis                    │
├──────────────────────────────────────────────┤
│ 4. PHYSICAL MODELLING                        │
│ Hindcast + Forecast + Environmental Data     │
├──────────────────────────────────────────────┤
│ 3. GEOSPATIAL ANALYSIS                       │
│ Spill geometry + coordinates + polygons      │
├──────────────────────────────────────────────┤
│ 2. AI / COMPUTER VISION                      │
│ PyTorch + U-Net                              │
├──────────────────────────────────────────────┤
│ 1. DATA                                      │
│ Sentinel-1 + AIS + ERA5 + Copernicus         │
└──────────────────────────────────────────────┘
```

The dependency chain is:

``` text
DATA
  ↓
DETECTION
  ↓
GEOMETRY
  ↓
ENVIRONMENT + DRIFT
  ↓
PROBABLE ORIGIN
  ↓
AIS CORRELATION
  ↓
EVIDENCE FEATURES
  ↓
ATTRIBUTION
  ↓
CONFIDENCE
  ↓
DASHBOARD
```

## The single most important architectural rule

> **Every downstream conclusion must be traceable back to the data and
> intermediate evidence that produced it.**

That gives the system:

-   modularity
-   explainability
-   testability
-   replaceability
-   reproducibility
-   better failure handling
-   defensible vessel attribution

And most importantly, it prevents the system from turning an uncertain
geospatial inference into an unjustified claim of responsibility.

------------------------------------------------------------------------

# 53. Implementation Status Convention

When this document is used alongside the project code, each component
should be marked as one of:

``` text
[IMPLEMENTED]
[PARTIALLY IMPLEMENTED]
[PROTOTYPE]
[PLANNED]
[FUTURE]
```

Do **not** label a function `[IMPLEMENTED]` merely because it appears in
this architecture document.

The function catalogue in this document is the **target interface and
engineering blueprint** unless the corresponding source code confirms
otherwise.

------------------------------------------------------------------------

# 54. One-Line System Definition

> **SIH26143 is a modular geospatial intelligence platform that combines
> Sentinel-1 SAR segmentation, spill geometry, environmental drift
> modelling, historical AIS trajectory analysis and evidence-based
> vessel ranking to transform an observed oil spill into an explainable
> investigation result.**
