# OASIS: Marine Oil Spill Intelligence & Vessel Attribution Platform

**Smart India Hackathon 2026 | Problem Statement ID: SIH26143**  
**Organization:** National Technical Research Organisation (NTRO) / Indian Coast Guard (ICG)  
**Framework Alignment:** National Oil Spill Disaster Contingency Plan (NOS-DCP)  
**Team:** Team DDOS  

---

## 1. Executive Summary

OASIS (Oil-spill Attribution & Satellite Intelligence System) is a defense-grade geospatial intelligence platform designed to detect marine hydrocarbon slicks from satellite radar imagery, trace their probable point of origin using hydrodynamic leeway physics, and identify responsible vessels through spatiotemporal AIS trajectory correlation and behavioral anomaly scoring.

Rather than relying on an unexplainable, monolithic black-box neural network, OASIS implements a 7-layer modular pipeline. Every downstream forensic conclusion is deterministically traceable to physical radar backscatter contrast, standard oceanic leeway dynamics, and auditable vessel movement data.

---

## 2. Core Architectural Principles

* **Modular Decoupling:** Every computational stage (detection, geometry, drift, AIS filtering, attribution) has a strictly typed data contract. Components can be independently inspected, tested, and upgraded.
* **Deterministic Physics Over Black-Box AI:** Deep learning is restricted strictly to visual perception (SAR segmentation and patch verification). Drift modeling uses proven hydrodynamic equations, not uncalibrated recurrent networks.
* **Truth in Engineering (Never Fabricate Evidence):** If AIS coverage is missing or vessel transponders were disabled, the system never invents a suspect. It flags an explicit "Dark Vessel / Attribution Unavailable" status and calculates tactical intercept coordinates for Indian Coast Guard aerial reconnaissance.
* **Legal and Forensic Defensibility:** The platform produces court-admissible dossiers complete with SHA-256 chain-of-custody hashes, physical decibel contrast proof, and calibrated multi-factor attribution matrices.

---

## 3. The 7-Layer System Architecture

```text
Layer 1: Raw Data Ingestion
  - Sentinel-1 SAR Dual-Pol (VV/VH, C-band)
  - ECMWF / ERA5 10m Atmospheric Wind Vectors
  - Copernicus Marine (CMEMS) Surface Ocean Currents
  - Historical & Streaming AIS Records (MarineCadastre / Coastal Feeds)

Layer 2: Preprocessing & Spatial Indexing
  - 512x512 SAR Tiling with dB Clipping [-30.0, 0.0] dB and Normalization
  - Bilinear 2D Spatial & Linear Temporal Metocean Interpolation
  - DuckDB / SQLite Spatiotemporal AIS Indexing (5-minute uniform resampling)

Layer 3: Dual-AI Perception Engine
  - Model 1: UNet++ Dual-Pol SAR Segmentation (Outputs Binary Mask & Heatmap)
  - Task 2: OpenCV Metric Geometry Engine (Area in km2, Centroid, Elongation Angle)
  - Model 2: Radiometric Forensic Verifier (Annulus Delta-dB Contrast & Boundary Sharpness)

Layer 4: Deterministic Physics Drift Engine (SlickTrace)
  - Lagrangian Leeway Advection (Current + 0.03*Wind + Coriolis Deflection)
  - Backward Hindcasting to Probable Origin (P_0) with Expanding Uncertainty Buffer
  - Forward Forecasting (12 to 24-hour coastal threat dispersion cone)

Layer 5: AIS Correlation & Behavioral Attribution
  - Spatiotemporal Cylinder Query: [(P_0 +/- Radius), (T_0 +/- 1 hour)]
  - Model 3: Unsupervised Kinematic Anomaly Classifier (Detecting <5 kt tank-washing maneuvers)
  - Task 5: Multi-Factor Utility Scoring (CPA Distance, Heading Match, Speed Drops)
  - Dark Vessel Protocol (Aerial interdiction coordinates if AIS = 0)

Layer 6: Forensic Evidence & Integrity
  - Tamper-Evident SHA-256 Chain of Custody
  - Multi-Dimensional Data Quality Index (Satellite, Weather, AIS completeness)

Layer 7: Application & Command Delivery
  - FastAPI Orchestration Layer (Asynchronous REST API)
  - Tactical Command Center (React 19, TypeScript, MapLibre GL, Three.js 3D Globe)
  - Official Court-Admissible ICG / NOS-DCP Forensic PDF Report Generator
