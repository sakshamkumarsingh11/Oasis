# Frontend Presentation Architecture Amendment

This amendment is intended for `SIH26143_OILSPILL_SYSTEM_ARCHITECTURE.md` and supersedes its historic Streamlit and Folium/Leaflet presentation references.

The active presentation layer is a standalone React + TypeScript + Vite frontend. React Router owns routing; TanStack Query owns API/server state; Zustand owns UI-only state. MapLibre GL JS supplies the analytical, GeoJSON-driven investigation map, while Three.js supplies the landing/global overview globe. Recharts visualizes confidence/evidence, and Framer Motion supplies restrained motion.

The boundary is deliberately:

```text
React UI → feature hooks → typed API abstraction → mock adapter (now)
                                                → REST adapter (future)
```

No ML, drift, AIS, or attribution logic is implemented in this frontend. It presents strongly typed outputs only. `VITE_USE_MOCK_API=true` supports the complete frontend with no backend. Synthetic mock data is hidden behind API modules and clearly labeled as demo data; it must never be presented as live intelligence.

The seven supported demo states are full investigation, partial AIS, no AIS, unavailable environmental data, no oil detected, processing, and pipeline error. No-AIS states deliberately show no candidate vessels; no-oil states suppress downstream investigation artifacts.

Three.js only serves the global overview and loads its geographic asset locally from `public/geo/ne_50m_land.json`. The MapLibre surface handles spill, centroid, origin, hindcast, forecast, forecast region, AIS tracks, candidate vessels, controls, selection, popups, legend, and contextual evidence.

Stable TypeScript contracts are `Incident`, `SatelliteScene`, `SpillDetection`, `SpillGeometry`, `EnvironmentalFeatures`, `DriftResult`, `Vessel`, `CandidateVessel`, `AttributionEvidence`, `AttributionResult`, `ConfidenceAssessment`, `PipelineStage`, and `DashboardPayload`. The proposed future REST contract lives in `API_CONTRACT.md`.
