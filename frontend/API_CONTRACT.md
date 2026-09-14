# OILSPILL Intelligence — Frontend API Contract

**STATUS: FRONTEND CONTRACT**  
**BACKEND IMPLEMENTATION: PENDING**

The current adapter is mock-only (`VITE_USE_MOCK_API=true`). UI components consume typed hooks, never fixtures directly.

| Method | Endpoint | Response |
|---|---|---|
| `GET` | `/api/v1/incidents` | `Incident[]` |
| `POST` | `/api/v1/incidents` | `Incident` |
| `GET` | `/api/v1/incidents/{id}` | `Incident` |
| `GET` | `/api/v1/incidents/{id}/dashboard` | `DashboardPayload` |
| `GET` | `/api/v1/incidents/{id}/map` | `GeoFeatureCollection` |
| `GET` | `/api/v1/incidents/{id}/detection` | `SpillDetection` |
| `GET` | `/api/v1/incidents/{id}/geometry` | `SpillGeometry` |
| `GET` | `/api/v1/incidents/{id}/drift` | `DriftResult` |
| `GET` | `/api/v1/incidents/{id}/vessels` | `CandidateVessel[]` |
| `GET` | `/api/v1/incidents/{id}/attribution` | `AttributionResult` |

`POST /detect`, `/characterise`, `/hindcast`, `/forecast`, `/ais/search`, and `/attribute` may trigger the respective pipeline stages later. Return `202` with `{ jobId, status }` while processing.

All GeoJSON is RFC 7946-shaped: longitude/latitude coordinates, `FeatureCollection`, and layer properties (`spill`, `origin`, `hindcast`, `forecast`, `forecast-region`, `ais`, `vessels`). Errors use `{ "code": "AIS_UNAVAILABLE", "message": "…", "retryable": false }`.

`DashboardPayload` composes `Incident`, `SatelliteScene`, `SpillDetection`, optional `SpillGeometry`, `EnvironmentalFeatures`, `DriftResult`, `AttributionResult`, `ConfidenceAssessment`, `PipelineStage[]`, and a GeoJSON map payload. An unavailable AIS response must produce no candidate vessels and `attribution.status: "UNAVAILABLE"`.
