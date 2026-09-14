export type ISODate = string;
export type LngLat = [number, number];
export type ScenarioId = 'full'|'partial-ais'|'no-ais'|'no-environment'|'no-oil'|'processing'|'error';
export type Availability = 'GOOD'|'LOW_QUALITY'|'UNAVAILABLE';
export type PipelineStatus = 'pending'|'running'|'complete'|'failed'|'unavailable';
export type ConfidenceLevel = 'HIGH'|'MEDIUM'|'LOW'|'UNAVAILABLE';
export type AisCoverage = 'FULL'|'PARTIAL'|'NONE';
export type AttributionStatus = 'AVAILABLE'|'AVAILABLE_WITH_REDUCED_CONFIDENCE'|'UNAVAILABLE';
export interface PointFeature { type:'Feature'; properties: Record<string, unknown>; geometry:{type:'Point';coordinates:LngLat} }
export interface LineFeature { type:'Feature'; properties: Record<string, unknown>; geometry:{type:'LineString';coordinates:LngLat[]} }
export interface PolygonFeature { type:'Feature'; properties: Record<string, unknown>; geometry:{type:'Polygon';coordinates:LngLat[][]} }
export type GeoFeature = PointFeature|LineFeature|PolygonFeature;
export interface GeoCollection { type:'FeatureCollection'; features:GeoFeature[] }
export interface Incident { id:string; eventTimestamp:ISODate; location:LngLat; region:string; status:'DETECTED'|'PROCESSING'|'COMPLETE'|'FAILED'|'NO_OIL'; detectionConfidence:number|null; aisCoverage:AisCoverage; attributionStatus:AttributionStatus; }
export interface SatelliteScene { id:string; source:'Sentinel-1 SAR'; acquisitionTime:ISODate; qualityScore:number; resolutionM:number; }
export interface SpillDetection { detected:boolean; confidence:number|null; modelVersion:string; maskAvailable:boolean; }
export interface SpillGeometry { areaKm2:number; perimeterKm:number; centroid:LngLat; orientationDeg:number; polygon:PolygonFeature; }
export interface EnvironmentalFeatures { weather:Availability; ocean:Availability; windSpeedKn:number|null; windDirectionDeg:number|null; currentSpeedKn:number|null; currentDirectionDeg:number|null; timestamp:ISODate|null; }
export interface DriftResult { available:boolean; origin:PointFeature|null; originTime:ISODate|null; uncertainty:ConfidenceLevel; hindcast:LineFeature|null; forecast:LineFeature|null; affectedRegion:PolygonFeature|null; }
export interface Vessel { mmsi:string; name:string; type:string; flag:string; }
export interface CandidateVessel { vessel:Vessel; rank:number; score:number; confidence:ConfidenceLevel; distanceKm:number; temporalMatch:'Strong'|'Moderate'|'Weak'; trajectoryMatch:ConfidenceLevel; track:LineFeature; position:PointFeature; }
export interface AttributionEvidence { candidateMmsi:string; findings:{label:string; status:'positive'|'neutral'|'negative'}[]; dimensions:{name:string;score:number}[]; }
export interface AttributionResult { status:AttributionStatus; confidence:ConfidenceLevel; candidates:CandidateVessel[]; evidence:AttributionEvidence[]; }
export interface ConfidenceAssessment { overall:ConfidenceLevel; score:number|null; dimensions:{name:string; score:number|null; availability:Availability}[]; }
export interface PipelineStage { id:string; label:string; status:PipelineStatus; detail?:string; }
export interface DashboardPayload { demo:boolean; scenario:ScenarioId; incident:Incident; scene:SatelliteScene; detection:SpillDetection; spill:SpillGeometry|null; environment:EnvironmentalFeatures; drift:DriftResult; attribution:AttributionResult; confidence:ConfidenceAssessment; pipeline:PipelineStage[]; map:GeoCollection; }
export interface ApiError { code:string; message:string; retryable:boolean; }
