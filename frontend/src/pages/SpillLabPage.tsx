import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import * as turf from '@turf/turf';
import { ScanSearch, Activity, Waves, Droplet, MapPin, Ship, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

interface AnalysisResult {
  spill_id: string;
  segmentation_confidence: number;
  geometry: {
    centroid: { lat: number; lon: number };
    area_km2: number;
    perimeter_km: number;
    bbox: [number, number, number, number];
    orientation_degrees: number;
  };
  status_message: string;
  drift: {
    hindcast_origin: {
      centroid: { lat: number; lon: number };
      time_window_start: string;
      time_window_end: string;
      uncertainty_radius_km: number;
    };
    forecast_trajectory: Array<{
      timestamp: string;
      location: { lat: number; lon: number };
    }>;
  };
  ais_status: string;
  ranked_vessels: Array<{
    mmsi: string;
    vessel_name: string;
    vessel_type: string;
    attribution_score: number;
    confidence: string;
    evidence: {
      cpa_distance_km: number;
      speed_anomaly: boolean;
      trajectory_match: string;
    };
    track_history: Array<{
      location: { lat: number; lon: number };
      timestamp: string;
      sog_knots: number;
      cog_degrees: number;
    }>;
  }>;
}

function DonutChart({ metrics, overall }: { metrics: any[], overall: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const total = metrics.reduce((s, m) => s + m.value, 0) || 1;
  const R = 36;
  const C = 2 * Math.PI * R;
  let offset = 0;

  const hoveredMetric = metrics.find(m => m.id === hover);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
      {/* SVG */}
      <div style={{ position: 'relative', width: 100, height: 100 }}>
        <svg width="100" height="100" viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)' }}>
          {metrics.map(m => {
            const sliceLength = (m.value / total) * C;
            const strokeDasharray = `${sliceLength} ${C}`;
            const strokeDashoffset = -offset;
            offset += sliceLength;
            const isHovered = hover === m.id;

            return (
              <circle
                key={m.id}
                cx="50" cy="50" r={R}
                fill="none"
                stroke={m.color}
                strokeWidth={isHovered ? 14 : 10}
                strokeDasharray={strokeDasharray}
                strokeDashoffset={strokeDashoffset}
                style={{ transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)', cursor: 'pointer' }}
                onMouseEnter={() => setHover(m.id)}
                onMouseLeave={() => setHover(null)}
              />
            );
          })}
        </svg>
        {/* Center text */}
        <div style={{
          position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none'
        }}>
          <strong style={{ fontSize: 24, color: '#fff', lineHeight: 1, letterSpacing: '-0.02em' }}>
            {hoveredMetric ? hoveredMetric.value : overall}
          </strong>
          <span style={{ font: '10px "DM Mono"', color: '#8ba4b1', marginTop: 4 }}>
            {hoveredMetric ? 'Score' : 'Overall'}
          </span>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {metrics.map(m => (
          <div key={m.id}
            onMouseEnter={() => setHover(m.id)}
            onMouseLeave={() => setHover(null)}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 16, fontSize: 12, color: hover === m.id ? '#fff' : '#8ba4b1',
              cursor: 'pointer', transition: 'color 0.2s', fontFamily: 'system-ui, sans-serif'
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%', background: m.color,
                transform: hover === m.id ? 'scale(1.3)' : 'scale(1)', transition: 'transform 0.2s'
              }} />
              {m.label}
            </div>
            <strong style={{ color: hover === m.id ? '#fff' : '#d9f0f4', font: '11px "DM Mono"' }}>{m.value}%</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SpillLabPage() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [obsDate, setObsDate] = useState('2026-01-01');
  const [obsTime, setObsTime] = useState('06:00');
  const [windSpeed, setWindSpeed] = useState('7.5');
  const [windDir, setWindDir] = useState('220');
  const [currSpeed, setCurrSpeed] = useState('0.35');
  const [currDir, setCurrDir] = useState('45');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noOil, setNoOil] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [spillBoxHovered, setSpillBoxHovered] = useState(false);
  const [suspectsOpen, setSuspectsOpen] = useState(false);


  // Initialize map
  useEffect(() => {
    if (!mapContainer.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: { version: 8, sources: { satellite: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, attribution: 'Tiles © Esri' } }, layers: [{ id: 'satellite', type: 'raster', source: 'satellite' }] },
      center: [20, 0],
      zoom: 2,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('click', (e) => {
      const { lng, lat: clickLat } = e.lngLat;
      setLat(clickLat.toFixed(5));
      setLon(lng.toFixed(5));
      if (markerRef.current) {
        markerRef.current.setLngLat([lng, clickLat]);
      } else {
        const mk = new maplibregl.Marker({ color: '#73d5e0' })
          .setLngLat([lng, clickLat])
          .addTo(map);
        markerRef.current = mk;
      }
    });

    mapRef.current = map;
    return () => { map.remove(); };
  }, []);

  // Update marker when lat/lon typed manually
  useEffect(() => {
    const latN = Number(lat);
    const lonN = Number(lon);
    if (!Number.isFinite(latN) || !Number.isFinite(lonN) || !mapRef.current) return;
    if (markerRef.current) {
      markerRef.current.setLngLat([lonN, latN]);
    } else {
      const mk = new maplibregl.Marker({ color: '#73d5e0' })
        .setLngLat([lonN, latN])
        .addTo(mapRef.current);
      markerRef.current = mk;
    }
  }, [lat, lon]);

  const animFrameRef = useRef<number | null>(null);
  const pathAnimRef = useRef<number | null>(null);
  const customMarkersRef = useRef<maplibregl.Marker[]>([]);
  const vesselMarkersRef = useRef<maplibregl.Marker[]>([]);
  const vesselPopupRef = useRef<maplibregl.Popup | null>(null);

  const clearMapLayers = () => {
    const map = mapRef.current;
    if (!map) return;
    // Cancel any running vessel animation
    if (animFrameRef.current) { cancelAnimationFrame(animFrameRef.current); animFrameRef.current = null; }
    if (pathAnimRef.current) { cancelAnimationFrame(pathAnimRef.current); pathAnimRef.current = null; }
    const layers = ['spill-fill', 'spill-outline', 'centroid-point', 'drift-origin-fill', 'drift-origin-outline', 'drift-path-line', 'drift-forecast-points'];
    layers.forEach(l => { if (map.getLayer(l)) map.removeLayer(l); });
    const sources = ['spill-polygon', 'spill-centroid', 'drift-origin', 'drift-path', 'drift-forecast'];
    sources.forEach(s => { if (map.getSource(s)) map.removeSource(s); });
    customMarkersRef.current.forEach(m => m.remove());
    customMarkersRef.current = [];
    vesselMarkersRef.current.forEach(m => m.remove());
    vesselMarkersRef.current = [];
    if (vesselPopupRef.current) {
      vesselPopupRef.current.remove();
      vesselPopupRef.current = null;
    }
    // Clean vessel trajectory layers (up to 5 vessels)
    for (let i = 0; i < 5; i++) {
      [`vessel-trail-${i}`, `vessel-trail-line-${i}`, `vessel-trail-hit-${i}`, `vessel-icon-${i}`].forEach(l => { if (map.getLayer(l)) map.removeLayer(l); });
      [`vessel-trail-src-${i}`, `vessel-trail-line-src-${i}`, `vessel-icon-src-${i}`].forEach(s => { if (map.getSource(s)) map.removeSource(s); });
    }
  };

  function calculateBearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const y = Math.sin(dLon) * Math.cos((lat2 * Math.PI) / 180);
    const x =
      Math.cos((lat1 * Math.PI) / 180) * Math.sin((lat2 * Math.PI) / 180) -
      Math.sin((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.cos(dLon);
    const brng = (Math.atan2(y, x) * 180) / Math.PI;
    return (brng + 360) % 360;
  }

  function renderVesselInfoHtml(vessel: NonNullable<AnalysisResult['ranked_vessels']>[number], color: string): string {
    return `
      <div style="
        background: rgba(8, 24, 38, 0.95);
        backdrop-filter: blur(18px);
        -webkit-backdrop-filter: blur(18px);
        border: 1px solid ${color};
        box-shadow: 0 12px 32px rgba(0,0,0,0.65), 0 0 18px ${color}55;
        border-radius: 9px;
        padding: 12px 14px;
        min-width: 200px;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e0f4f7;
      ">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="width: 8px; height: 8px; border-radius: 50%; background: ${color}; box-shadow: 0 0 8px ${color};"></span>
            <strong style="font-size: 14px; color: #fff; letter-spacing: 0.02em; font-weight: 700;">${vessel.vessel_name}</strong>
          </div>
          <span style="
            background: ${color}25;
            color: ${color};
            border: 1px solid ${color}65;
            padding: 2px 7px;
            border-radius: 8px;
            font-size: 10px;
            font-weight: 800;
            font-family: 'DM Mono', monospace;
          ">${Math.round(vessel.attribution_score * 100)}% MATCH</span>
        </div>

        <div style="
          background: rgba(255, 255, 255, 0.06);
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 5px;
          padding: 6px 10px;
          margin-bottom: 8px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        ">
          <span style="font-size: 10px; color: #8aaab9; font-family: 'DM Mono', monospace; letter-spacing: 0.08em; font-weight: 600;">MMSI NUMBER</span>
          <strong style="font-size: 12px; color: #73d5e0; font-family: 'DM Mono', monospace; letter-spacing: 0.08em;">${vessel.mmsi}</strong>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-family: 'DM Mono', monospace; font-size: 10px;">
          <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); padding: 5px 7px; border-radius: 4px;">
            <div style="color: #7292a1; font-size: 8px; text-transform: uppercase;">TYPE</div>
            <div style="color: #e0f4f7; font-weight: 600; margin-top: 1px;">${vessel.vessel_type || 'Unknown'}</div>
          </div>
          <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); padding: 5px 7px; border-radius: 4px;">
            <div style="color: #7292a1; font-size: 8px; text-transform: uppercase;">CPA DIST</div>
            <div style="color: #e0f4f7; font-weight: 600; margin-top: 1px;">${vessel.evidence.cpa_distance_km.toFixed(1)} km</div>
          </div>
        </div>

        <div style="margin-top: 7px; padding-top: 7px; border-top: 1px solid rgba(255, 255, 255, 0.08); display: flex; justify-content: space-between; font-size: 9px; color: #7aa0af; font-family: 'DM Mono', monospace;">
          <span>Trajectory: <strong style="color: #73d5e0;">${vessel.evidence.trajectory_match}</strong></span>
          <span>AIS Points: ${vessel.track_history?.length || 0}</span>
        </div>
      </div>
    `;
  }

  const drawSpillOnMap = (res: AnalysisResult) => {
    const map = mapRef.current;
    if (!map) return;
    clearMapLayers();

    const [minLat, minLon, maxLat, maxLon] = res.geometry.bbox;
    const polygon: GeoJSON.Feature<GeoJSON.Polygon> = {
      type: 'Feature',
      properties: { area_km2: res.geometry.area_km2 },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [minLon, minLat],
          [maxLon, minLat],
          [maxLon, maxLat],
          [minLon, maxLat],
          [minLon, minLat],
        ]],
      },
    };

    const centroidPt: GeoJSON.Feature<GeoJSON.Point> = {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'Point',
        coordinates: [res.geometry.centroid.lon, res.geometry.centroid.lat],
      },
    };

    // 1. Draw Hindcast Origin (Pixel-based circle so it never vanishes at global zoom)
    let originPt: GeoJSON.Feature<GeoJSON.Point> | null = null;
    let driftPathCoords: number[][] = [];
    let allBoundsCoords: number[][] = [];
    let forecastPts: GeoJSON.Feature<GeoJSON.MultiPoint> | null = null;

    if (res.drift) {
      const origin = res.drift.hindcast_origin;

      originPt = {
        type: 'Feature',
        properties: { radius_km: origin.uncertainty_radius_km },
        geometry: {
          type: 'Point',
          coordinates: [origin.centroid.lon, origin.centroid.lat]
        }
      };

      // 2. Build the full path: Origin -> Current Centroid -> Forecast Trajectory
      driftPathCoords.push([origin.centroid.lon, origin.centroid.lat]);
      driftPathCoords.push([res.geometry.centroid.lon, res.geometry.centroid.lat]);

      allBoundsCoords.push([origin.centroid.lon, origin.centroid.lat]);
      allBoundsCoords.push([res.geometry.centroid.lon, res.geometry.centroid.lat]);

      const fCoords: number[][] = [];
      if (res.drift.forecast_trajectory) {
        res.drift.forecast_trajectory.forEach(pt => {
          driftPathCoords.push([pt.location.lon, pt.location.lat]);
          allBoundsCoords.push([pt.location.lon, pt.location.lat]);
          fCoords.push([pt.location.lon, pt.location.lat]);
        });
      }

      forecastPts = {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'MultiPoint',
          coordinates: fCoords
        }
      };
    }

    const driftPath: GeoJSON.Feature<GeoJSON.LineString> = {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: driftPathCoords
      }
    };

    const emptyFc = { type: 'FeatureCollection', features: [] };
    map.addSource('spill-polygon', { type: 'geojson', data: emptyFc as any });
    map.addSource('spill-centroid', { type: 'geojson', data: emptyFc as any });

    if (originPt) {
      map.addSource('drift-origin', { type: 'geojson', data: emptyFc as any });
      map.addSource('drift-path', { type: 'geojson', data: emptyFc as any });
      if (forecastPts) map.addSource('drift-forecast', { type: 'geojson', data: emptyFc as any });

      // Always-visible pixel circle for origin
      map.addLayer({
        id: 'drift-origin-fill',
        type: 'circle',
        source: 'drift-origin',
        paint: {
          'circle-color': '#ff766b',
          'circle-opacity': 0.15,
          'circle-radius': 35 // Always 35 pixels on screen!
        }
      });
      map.addLayer({
        id: 'drift-origin-outline',
        type: 'circle',
        source: 'drift-origin',
        paint: {
          'circle-color': 'transparent',
          'circle-stroke-color': '#ff766b',
          'circle-stroke-width': 2,
          'circle-radius': 35
        }
      });
      map.addLayer({
        id: 'drift-path-line',
        type: 'line',
        source: 'drift-path',
        paint: { 'line-color': '#91dce8', 'line-width': 2, 'line-dasharray': [4, 2] }
      });
      // Add explicit MultiPoint for forecast dots so MapLibre renders them!
      map.addLayer({
        id: 'drift-forecast-points',
        type: 'circle',
        source: 'drift-forecast',
        paint: { 'circle-color': '#91dce8', 'circle-radius': 4 }
      });
    }

    map.addLayer({
      id: 'spill-fill',
      type: 'fill',
      source: 'spill-polygon',
      paint: {
        'fill-color': '#f6a623',
        'fill-opacity': 0.35,
      },
    });
    map.addLayer({
      id: 'spill-outline',
      type: 'line',
      source: 'spill-polygon',
      paint: {
        'line-color': '#ff6b4a',
        'line-width': 2.5,
      },
    });
    map.addLayer({
      id: 'centroid-point',
      type: 'circle',
      source: 'spill-centroid',
      paint: {
        'circle-radius': 7,
        'circle-color': '#ff3d2e',
        'circle-stroke-color': '#fff',
        'circle-stroke-width': 2,
      },
    });

    // ─── VESSEL TRAJECTORY ANIMATION ───
    const VESSEL_COLORS = ['#f5c542', '#e07bff', '#42f5a7', '#ff7b7b', '#7bc8ff'];
    const topVessels = (res.ranked_vessels || [])
      .sort((a, b) => b.attribution_score - a.attribution_score)
      .slice(0, 5)
      .filter(v => v.track_history && v.track_history.length >= 2);

    // For each vessel: draw dashed trail + interactive click path + directional vessel marker
    const vesselAnimStates: { coords: number[][]; marker: maplibregl.Marker; svgHull: SVGElement | null; id: string }[] = [];

    topVessels.forEach((vessel, i) => {
      const coords = vessel.track_history.map(pt => [pt.location.lon, pt.location.lat]);
      const color = VESSEL_COLORS[i % VESSEL_COLORS.length];

      // 1. Dashed trajectory line
      map.addSource(`vessel-trail-line-src-${i}`, {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }
      });
      map.addLayer({
        id: `vessel-trail-line-${i}`,
        type: 'line',
        source: `vessel-trail-line-src-${i}`,
        paint: {
          'line-color': color,
          'line-width': 2,
          'line-dasharray': [4, 4],
          'line-opacity': 0.75,
        }
      });

      // 2. Wide hit area layer for smooth and easy clicking on the ship path
      map.addLayer({
        id: `vessel-trail-hit-${i}`,
        type: 'line',
        source: `vessel-trail-line-src-${i}`,
        paint: {
          'line-color': '#000000',
          'line-opacity': 0,
          'line-width': 18,
        }
      });

      // Cursor pointer and glow highlight on path hover
      map.on('mouseenter', `vessel-trail-hit-${i}`, () => {
        map.getCanvas().style.cursor = 'pointer';
        if (map.getLayer(`vessel-trail-line-${i}`)) {
          map.setPaintProperty(`vessel-trail-line-${i}`, 'line-width', 3.5);
          map.setPaintProperty(`vessel-trail-line-${i}`, 'line-opacity', 1.0);
        }
      });
      map.on('mouseleave', `vessel-trail-hit-${i}`, () => {
        map.getCanvas().style.cursor = '';
        if (map.getLayer(`vessel-trail-line-${i}`)) {
          map.setPaintProperty(`vessel-trail-line-${i}`, 'line-width', 2);
          map.setPaintProperty(`vessel-trail-line-${i}`, 'line-opacity', 0.75);
        }
      });

      // Click on the ship path to display vessel MMSI & intelligence popup
      map.on('click', `vessel-trail-hit-${i}`, (e) => {
        vesselPopupRef.current?.remove();
        const popup = new maplibregl.Popup({
          closeButton: true,
          closeOnClick: true,
          offset: 14,
          className: 'vessel-glass-popup'
        })
          .setLngLat(e.lngLat)
          .setHTML(renderVesselInfoHtml(vessel, color))
          .addTo(map);
        vesselPopupRef.current = popup;
      });

      // 3. Directional Tactical Vessel Icon Marker (heading oriented along track)
      const initBearing = coords.length >= 2 ? calculateBearing(coords[0][1], coords[0][0], coords[1][1], coords[1][0]) : 0;

      const node = document.createElement('div');
      node.className = 'ship-radar-token';
      node.style.cssText = `
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: radial-gradient(circle at 35% 35%, rgba(18, 48, 72, 0.95), rgba(6, 20, 32, 0.95));
        border: 2px solid ${color};
        box-shadow: 0 0 16px ${color}88, inset 0 1px 1px rgba(255,255,255,0.4), 0 4px 12px rgba(0,0,0,0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        position: relative;
      `;
      node.innerHTML = `
        <span style="
          position: absolute;
          inset: -5px;
          border-radius: 50%;
          border: 1.5px solid ${color};
          animation: vessel-pulse 2.4s infinite ease-out;
          pointer-events: none;
        "></span>
        <svg class="vessel-svg-hull" width="20" height="20" viewBox="0 0 32 32" fill="none" style="transform: rotate(${initBearing}deg); transition: transform 0.25s ease; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.6)); pointer-events: none;">
          <path d="M16 2 C19.5 7 23.5 15.5 23.5 25.5 C23.5 28.5 20 30 16 30 C12 30 8.5 28.5 8.5 25.5 C8.5 15.5 12.5 7 16 2 Z" fill="${color}" fill-opacity="0.32" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
          <path d="M11 23 C13 24 19 24 21 23" stroke="${color}" stroke-width="1.2" stroke-linecap="round"/>
          <rect x="12.5" y="16" width="7" height="6.5" rx="1.5" fill="${color}" fill-opacity="0.85" stroke="#ffffff" stroke-width="1"/>
          <line x1="16" y1="5" x2="16" y2="13" stroke="#ffffff" stroke-width="1.6" stroke-linecap="round"/>
          <circle cx="16" cy="19" r="1.3" fill="#ffffff"/>
        </svg>
      `;

      const marker = new maplibregl.Marker({ element: node, anchor: 'center' })
        .setLngLat(coords[0] as [number, number])
        .addTo(map);

      vesselMarkersRef.current.push(marker);

      // Clicking the ship icon itself also reveals the info popup
      node.addEventListener('click', (e) => {
        e.stopPropagation();
        vesselPopupRef.current?.remove();
        const popup = new maplibregl.Popup({
          closeButton: true,
          closeOnClick: true,
          offset: 16,
          className: 'vessel-glass-popup'
        })
          .setLngLat(marker.getLngLat())
          .setHTML(renderVesselInfoHtml(vessel, color))
          .addTo(map);
        vesselPopupRef.current = popup;
      });

      // Include vessel coords in the bounds (NOT in driftPathCoords)
      coords.forEach(c => allBoundsCoords.push(c));

      const svgHull = node.querySelector('.vessel-svg-hull') as SVGElement | null;

      vesselAnimStates.push({
        coords,
        marker,
        svgHull,
        id: vessel.mmsi,
      });
    });

    // Animation loop: smoothly move each vessel ship marker along its track
    if (vesselAnimStates.length > 0) {
      const ANIM_DURATION_MS = 6000; // 6 seconds to travel the full track
      let startTime: number | null = null;

      const animateVessels = (timestamp: number) => {
        if (!startTime) startTime = timestamp;
        const elapsed = timestamp - startTime;
        const t = Math.min(elapsed / ANIM_DURATION_MS, 1); // 0→1

        vesselAnimStates.forEach((state) => {
          const { coords, marker, svgHull } = state;
          if (coords.length < 2) return;

          // Interpolate position along the polyline
          const totalSegments = coords.length - 1;
          const floatIndex = t * totalSegments;
          const segIndex = Math.min(Math.floor(floatIndex), totalSegments - 1);
          const segT = floatIndex - segIndex;

          const p1 = coords[segIndex];
          const p2 = coords[Math.min(segIndex + 1, coords.length - 1)];

          const lng = p1[0] + (p2[0] - p1[0]) * segT;
          const lat = p1[1] + (p2[1] - p1[1]) * segT;

          marker.setLngLat([lng, lat]);

          // Dynamically orient the vessel along heading
          if (svgHull && (p2[0] !== p1[0] || p2[1] !== p1[1])) {
            const bearing = calculateBearing(p1[1], p1[0], p2[1], p2[0]);
            svgHull.style.transform = `rotate(${bearing}deg)`;
          }
        });

        if (t < 1) {
          animFrameRef.current = requestAnimationFrame(animateVessels);
        } else {
          // Loop: restart after a 1s pause
          setTimeout(() => {
            startTime = null;
            animFrameRef.current = requestAnimationFrame(animateVessels);
          }, 1000);
        }
      };

      // Start after a short delay to let the map fly first
      setTimeout(() => {
        animFrameRef.current = requestAnimationFrame(animateVessels);
      }, 2200);
    }

    // Cinematic Zoom & Plot Sequence
    if (originPt && driftPathCoords.length > 0) {
      const originCoords = originPt.geometry.coordinates as [number, number];
      const destCoords = [res.geometry.centroid.lon, res.geometry.centroid.lat];

      // 1. Zoom into the Origin first
      map.flyTo({ center: originCoords, zoom: 11.5, duration: 2000 });

      // 2. Wait for flyTo to finish, then reveal origin and start the dynamic plotting
      setTimeout(() => {
        (map.getSource('drift-origin') as maplibregl.GeoJSONSource).setData(originPt);
        
        const originEl = document.createElement('div');
        originEl.innerHTML = 'Probable Origin';
        Object.assign(originEl.style, {
          background: 'rgba(255, 118, 107, 0.15)', border: '1px solid #ff766b',
          color: '#ff766b', padding: '4px 8px', borderRadius: '4px',
          fontFamily: 'DM Mono, monospace', fontSize: '10px',
          backdropFilter: 'blur(4px)', pointerEvents: 'none', whiteSpace: 'nowrap'
        });
        const m1 = new maplibregl.Marker({ element: originEl, anchor: 'left', offset: [20, 0] })
          .setLngLat(originCoords).addTo(map);
        customMarkersRef.current.push(m1);
        
        // 3. Pan out to reveal the whole path smoothly while plotting
        const bounds = new maplibregl.LngLatBounds();
        (allBoundsCoords.length > 0 ? allBoundsCoords : driftPathCoords).forEach(c => bounds.extend(c as [number, number]));
        map.fitBounds(bounds, { padding: 80, duration: 2500 });
        
        // 4. Smooth progressive plotting of the blue line
        let startT = performance.now();
        const animatePath = (now: number) => {
          let progress = (now - startT) / 2500; // Matches fitBounds duration (2.5s)
          if (progress > 1) progress = 1;
          
          // Smooth easing (easeOutCubic) for natural movement
          const t = 1 - Math.pow(1 - progress, 3);
          
          const currentLon = originCoords[0] + (destCoords[0] - originCoords[0]) * t;
          const currentLat = originCoords[1] + (destCoords[1] - originCoords[1]) * t;
          
          (map.getSource('drift-path') as maplibregl.GeoJSONSource).setData({
            type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [originCoords, [currentLon, currentLat]] }
          });
          
          if (progress < 1) {
            pathAnimRef.current = requestAnimationFrame(animatePath);
          } else {
            // Animation complete: reveal spill polygon, centroid, and full forecast path
            (map.getSource('spill-polygon') as maplibregl.GeoJSONSource).setData(polygon);
            (map.getSource('spill-centroid') as maplibregl.GeoJSONSource).setData(centroidPt);
            (map.getSource('drift-path') as maplibregl.GeoJSONSource).setData(driftPath);
            if (forecastPts) (map.getSource('drift-forecast') as maplibregl.GeoJSONSource).setData(forecastPts);
            
            const spillEl = document.createElement('div');
            spillEl.innerHTML = 'SAR Spill Boundary';
            Object.assign(spillEl.style, {
              background: 'rgba(246, 166, 35, 0.15)', border: '1px solid #f6a623',
              color: '#f6a623', padding: '4px 8px', borderRadius: '4px',
              fontFamily: 'DM Mono, monospace', fontSize: '10px',
              backdropFilter: 'blur(4px)', pointerEvents: 'none', whiteSpace: 'nowrap'
            });
            const m2 = new maplibregl.Marker({ element: spillEl, anchor: 'left', offset: [15, 0] })
              .setLngLat([res.geometry.centroid.lon, res.geometry.centroid.lat]).addTo(map);
            customMarkersRef.current.push(m2);
          }
        };
        pathAnimRef.current = requestAnimationFrame(animatePath);
      }, 2100);

    } else {
      // Fallback if no drift/origin data: just fly to the spill
      map.flyTo({
        center: [res.geometry.centroid.lon, res.geometry.centroid.lat],
        zoom: 10,
        duration: 2000,
      });
      setTimeout(() => {
        (map.getSource('spill-polygon') as maplibregl.GeoJSONSource).setData(polygon);
        (map.getSource('spill-centroid') as maplibregl.GeoJSONSource).setData(centroidPt);
        
        const spillEl = document.createElement('div');
        spillEl.innerHTML = 'SAR Spill Boundary';
        Object.assign(spillEl.style, {
          background: 'rgba(246, 166, 35, 0.15)', border: '1px solid #f6a623',
          color: '#f6a623', padding: '4px 8px', borderRadius: '4px',
          fontFamily: 'DM Mono, monospace', fontSize: '10px',
          backdropFilter: 'blur(4px)', pointerEvents: 'none', whiteSpace: 'nowrap'
        });
        const m2 = new maplibregl.Marker({ element: spillEl, anchor: 'left', offset: [15, 0] })
          .setLngLat([res.geometry.centroid.lon, res.geometry.centroid.lat]).addTo(map);
        customMarkersRef.current.push(m2);
      }, 2100);
    }
  };

  const resetForm = () => {
    setFile(null);
    setLat('');
    setLon('');
    setObsDate('');
    setObsTime('');
    setWindSpeed('');
    setWindDir('');
    setCurrSpeed('');
    setCurrDir('');
    setResult(null);
    setError(null);
    setNoOil(false);
    clearMapLayers();
    if (fileInput.current) fileInput.current.value = '';
  };

  const analyze = async () => {
    if (!file) return;
    const latN = Number(lat);
    const lonN = Number(lon);
    if (!Number.isFinite(latN) || !Number.isFinite(lonN)) {
      setError('Enter valid latitude and longitude.');
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setNoOil(false);
    clearMapLayers();

    try {
      const form = new FormData();
      form.append('file', file);
      form.append('approx_lat', String(latN));
      form.append('approx_lon', String(lonN));

      try {
        const isoString = new Date(`${obsDate}T${obsTime}:00Z`).toISOString();
        form.append('observation_time', isoString);
      } catch (e) {
        // Fallback or ignore if invalid
      }

      if (windSpeed) form.append('wind_speed_ms', windSpeed);
      if (windDir) form.append('wind_dir_from', windDir);
      if (currSpeed) form.append('current_speed_ms', currSpeed);
      if (currDir) form.append('current_dir_to', currDir);

      const resp = await fetch(`${BASE_URL}/api/v1/analyze`, {
        method: 'POST',
        body: form,
        signal: AbortSignal.timeout(120_000),
      });

      if (!resp.ok) {
        let detail = `Server error (${resp.status})`;
        try { const b = await resp.json(); detail = b.detail ?? detail; } catch { }
        throw new Error(detail);
      }

      const data: AnalysisResult = await resp.json();

      if (data.segmentation_confidence > 0.3 && data.geometry.area_km2 > 0.01) {
        setResult(data);
        setNoOil(false);
        drawSpillOnMap(data);
        if (data.ranked_vessels && data.ranked_vessels.length > 0) {
          setSuspectsOpen(true);
        }
      } else {
        setNoOil(true);
        setResult(null);
        setSuspectsOpen(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed.');
    } finally {
      setLoading(false);
    }
  };

  const handleFocusVessel = (v: NonNullable<AnalysisResult['ranked_vessels']>[number]) => {
    if (!mapRef.current || !v.track_history || v.track_history.length === 0) return;
    const lastPt = v.track_history[v.track_history.length - 1];
    mapRef.current.flyTo({
      center: [lastPt.location.lon, lastPt.location.lat],
      zoom: Math.max(mapRef.current.getZoom(), 10),
      duration: 1200,
    });
  };

  const getSuspectTierStyle = (v: NonNullable<AnalysisResult['ranked_vessels']>[number]) => {
    const isHigh = v.confidence === 'HIGH' || v.attribution_score >= 0.6;
    const isMed = !isHigh && (v.confidence === 'MEDIUM' || v.attribution_score >= 0.35);

    if (isHigh) {
      return {
        cardBg: 'rgba(239, 68, 68, 0.09)',
        cardBorder: '1px solid rgba(239, 68, 68, 0.35)',
        cardShadow: '0 4px 18px rgba(239, 68, 68, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
        nameColor: '#fff1f1',
        metaColor: '#fca5a5',
        badgeBg: 'rgba(239, 68, 68, 0.22)',
        badgeBorder: '1px solid rgba(239, 68, 68, 0.55)',
        badgeText: '#ff6b6b',
        chipBg: 'rgba(239, 68, 68, 0.08)',
        chipBorder: '1px solid rgba(239, 68, 68, 0.22)',
        chipLabel: '#f87171',
        chipValue: '#fecaca',
        accentDot: '#ff4d4d',
      };
    }
    if (isMed) {
      return {
        cardBg: 'rgba(245, 158, 11, 0.09)',
        cardBorder: '1px solid rgba(245, 158, 11, 0.32)',
        cardShadow: '0 4px 18px rgba(245, 158, 11, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
        nameColor: '#fffbeb',
        metaColor: '#fde68a',
        badgeBg: 'rgba(245, 158, 11, 0.20)',
        badgeBorder: '1px solid rgba(245, 158, 11, 0.50)',
        badgeText: '#fbbf24',
        chipBg: 'rgba(245, 158, 11, 0.07)',
        chipBorder: '1px solid rgba(245, 158, 11, 0.20)',
        chipLabel: '#fbbf24',
        chipValue: '#fef3c7',
        accentDot: '#f59e0b',
      };
    }
    return {
      cardBg: 'rgba(56, 189, 248, 0.08)',
      cardBorder: '1px solid rgba(56, 189, 248, 0.25)',
      cardShadow: '0 4px 18px rgba(56, 189, 248, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.06)',
      nameColor: '#f0f9ff',
      metaColor: '#bae6fd',
      badgeBg: 'rgba(56, 189, 248, 0.18)',
      badgeBorder: '1px solid rgba(56, 189, 248, 0.42)',
      badgeText: '#38bdf8',
      chipBg: 'rgba(56, 189, 248, 0.06)',
      chipBorder: '1px solid rgba(56, 189, 248, 0.18)',
      chipLabel: '#38bdf8',
      chipValue: '#e0f2fe',
      accentDot: '#0ea5e9',
    };
  };


  const validInput = file && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))
    && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lon)) <= 180;

  // Derived Metrics for the Confidence Donut Chart
  const satScore = result ? Math.min(98, Math.round(70 + result.geometry.area_km2 * 5)) : 0;
  const segScore = result ? Math.round(result.segmentation_confidence * 100) : 0;
  const envScore = Number(windSpeed) > 0 ? 88 : 70;
  const aisScore = result?.ais_status === 'AVAILABLE' ? Math.min(98, 60 + (result.ranked_vessels?.length || 0) * 4) : 30;
  const evdScore = (result?.ranked_vessels && result.ranked_vessels.length > 0)
    ? Math.round(result.ranked_vessels[0].attribution_score * 100)
    : 45;
  const overallScore = Math.round((satScore + segScore + envScore + aisScore + evdScore) / 5);

  const chartMetrics = [
    { id: 'sat', label: 'Satellite Quality', value: satScore, color: '#4cc9f0' },
    { id: 'seg', label: 'Segmentation Quality', value: segScore, color: '#4361ee' },
    { id: 'env', label: 'Environmental Data', value: envScore, color: '#f7b801' },
    { id: 'ais', label: 'AIS Coverage', value: aisScore, color: '#06d6a0' },
    { id: 'evd', label: 'Evidence Consistency', value: evdScore, color: '#8d99ae' },
  ];

  return (
    <div style={{ width: '100%', height: '100vh', position: 'relative', background: '#061523' }}>
      {/* Full-screen map */}
      <div ref={mapContainer} style={{ width: '100%', height: '100%' }} />

      {/* Floating Confidence Breakdown (Task 2 / UI) */}
      {result && (
        <div style={{
          position: 'absolute', bottom: 30, right: 30, zIndex: 10,
          background: '#071827e6', backdropFilter: 'blur(12px)',
          border: '1px solid #1b3445', borderRadius: 12, padding: '20px 24px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)'
        }}>
          <h4 style={{ margin: '0 0 20px', fontSize: 13, letterSpacing: '0.08em', color: '#73d5e0', fontWeight: 700 }}>
            CONFIDENCE BREAKDOWN
          </h4>
          <DonutChart metrics={chartMetrics} overall={overallScore} />
        </div>
      )}

      {/* Floating Oil Spill Detection Button & Glassmorphed Popout below Navigation Panel */}
      <div
        style={{
          position: 'absolute',
          top: 110,
          right: 10,
          zIndex: 15,
          display: 'flex',
          alignItems: 'flex-start',
          flexDirection: 'row-reverse',
          pointerEvents: 'none',
        }}
      >
        {/* Small button below Navigation Panel */}
        <button
          onMouseEnter={() => setSpillBoxHovered(true)}
          onMouseLeave={() => setSpillBoxHovered(false)}
          style={{
            pointerEvents: 'auto',
            width: 30,
            height: 30,
            borderRadius: 6,
            border: spillBoxHovered
              ? '1px solid rgba(111, 202, 214, 0.5)'
              : '1px solid rgba(111, 202, 214, 0.2)',
            background: spillBoxHovered
              ? 'rgba(13, 38, 56, 0.65)'
              : 'rgba(13, 38, 56, 0.4)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            boxShadow: '0 4px 15px rgba(0, 0, 0, 0.15)',
            color: '#73d5e0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            padding: 0,
            transition: 'all 0.2s ease',
            position: 'relative',
          }}
          title="Oil Spill Detected Info"
        >
          <Droplet
            size={16}
            color="#73d5e0"
            fill={result ? 'rgba(115, 213, 224, 0.35)' : 'none'}
          />
          {result && (
            <span
              style={{
                position: 'absolute',
                top: -2,
                right: -2,
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: '#73d5e0',
                boxShadow: '0 0 6px #73d5e0',
              }}
            />
          )}
        </button>

        {/* Glassmorphed Oil Spill Detected Box */}
        <div
          style={{
            pointerEvents: 'none',
            marginRight: 10,
            width: 320,
            background: 'rgba(13, 38, 56, 0.4)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            border: '1px solid rgba(111, 202, 214, 0.2)',
            borderRadius: 8,
            padding: 16,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
            opacity: spillBoxHovered ? 1 : 0,
            transform: spillBoxHovered ? 'translateX(0) scale(1)' : 'translateX(10px) scale(0.96)',
            transition: 'opacity 0.28s cubic-bezier(0.16, 1, 0.3, 1), transform 0.28s cubic-bezier(0.16, 1, 0.3, 1)',
            transformOrigin: 'top right',
          }}
        >
          {result ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                <div style={{
                  background: 'rgba(111, 202, 214, 0.1)',
                  border: '1px solid rgba(111, 202, 214, 0.25)',
                  padding: 6,
                  borderRadius: 6,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <Droplet size={18} color="#73d5e0" />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: 15, color: '#e8f7fa', fontWeight: 700 }}>Oil Spill Detected</h3>
                  <span style={{ font: '10px "DM Mono"', color: '#76aabd' }}>{result.spill_id}</span>
                </div>
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 10px',
              }}>
                {[
                  ['Confidence', `${Math.round(result.segmentation_confidence * 100)}%`],
                  ['Area', `${result.geometry.area_km2} km²`],
                  ['Perimeter', `${result.geometry.perimeter_km} km`],
                  ['Orientation', `${result.geometry.orientation_degrees}°`],
                  ['Centroid Lat', result.geometry.centroid.lat.toFixed(5)],
                  ['Centroid Lon', result.geometry.centroid.lon.toFixed(5)],
                ].map(([label, value]) => (
                  <div key={label} style={{
                    background: 'rgba(8, 29, 43, 0.5)',
                    border: '1px solid rgba(111, 202, 214, 0.12)',
                    borderRadius: 5,
                    padding: '7px 9px',
                  }}>
                    <span style={{ font: '9px "DM Mono"', color: '#7aa0af', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</span>
                    <strong style={{ display: 'block', fontSize: 14, color: '#d9f0f4', marginTop: 2, fontWeight: 700 }}>{value}</strong>
                  </div>
                ))}
              </div>

              <div style={{
                marginTop: 12, padding: '8px 10px',
                background: 'rgba(115, 213, 224, 0.05)',
                border: '1px dashed rgba(115, 213, 224, 0.3)',
                borderRadius: 5, font: '10px "DM Mono"', color: '#73d5e0',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <MapPin size={12} /> Spill polygon plotted on the map
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '10px 4px' }}>
              <div style={{
                display: 'inline-flex',
                background: 'rgba(115, 213, 224, 0.1)',
                border: '1px solid rgba(111, 202, 214, 0.2)',
                padding: 8,
                borderRadius: '50%',
                marginBottom: 8,
              }}>
                <Droplet size={20} color="#73d5e0" />
              </div>
              <h4 style={{ margin: '0 0 6px', fontSize: 14, color: '#e8f7fa' }}>No Active Spill Detected</h4>
              <p style={{ margin: 0, fontSize: 11, color: '#7aa0af', lineHeight: 1.4 }}>
                Upload a SAR image and click <strong>Analyze Image</strong> to detect oil spill boundaries, area, perimeter, and drift tracks.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Floating Possible Suspects Button & Glassmorphic Suspects Panel */}
      <div
        style={{
          position: 'absolute',
          top: 148,
          right: 10,
          zIndex: 14,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          pointerEvents: 'none',
        }}
      >
        <button
          onClick={() => setSuspectsOpen((prev) => !prev)}
          style={{
            pointerEvents: 'auto',
            height: 32,
            padding: '0 13px',
            borderRadius: 7,
            border: suspectsOpen
              ? '1px solid rgba(115, 213, 224, 0.7)'
              : '1px solid rgba(111, 202, 214, 0.28)',
            background: suspectsOpen
              ? 'rgba(12, 38, 58, 0.88)'
              : 'rgba(10, 30, 48, 0.58)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            boxShadow: suspectsOpen
              ? '0 6px 20px rgba(0, 0, 0, 0.35), 0 0 14px rgba(115, 213, 224, 0.28)'
              : '0 4px 15px rgba(0, 0, 0, 0.2)',
            color: '#e0f4f7',
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            cursor: 'pointer',
            transition: 'all 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.02em',
          }}
          title="Toggle Possible Suspects"
        >
          <Ship size={15} color="#73d5e0" />
          <span>Possible Suspects</span>
          {result?.ranked_vessels && result.ranked_vessels.length > 0 && (
            <span
              style={{
                background: 'rgba(239, 68, 68, 0.25)',
                color: '#ff6b6b',
                border: '1px solid rgba(239, 68, 68, 0.45)',
                padding: '1px 6px',
                borderRadius: 9,
                fontSize: 10,
                fontWeight: 700,
                fontFamily: '"DM Mono", monospace',
              }}
            >
              {Math.min(5, result.ranked_vessels.length)}
            </span>
          )}
        </button>

        {/* Completely Glassmorphic Suspects Box */}
        <div
          style={{
            pointerEvents: suspectsOpen ? 'auto' : 'none',
            marginTop: 8,
            width: 370,
            maxHeight: 'calc(100vh - 200px)',
            background: 'rgba(8, 24, 38, 0.82)',
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
            border: '1px solid rgba(115, 213, 224, 0.22)',
            borderRadius: 10,
            boxShadow: '0 16px 40px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            opacity: suspectsOpen ? 1 : 0,
            transform: suspectsOpen ? 'translateY(0) scale(1)' : 'translateY(-10px) scale(0.96)',
            transition: 'opacity 0.28s cubic-bezier(0.16, 1, 0.3, 1), transform 0.28s cubic-bezier(0.16, 1, 0.3, 1)',
            transformOrigin: 'top right',
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: '12px 14px 10px',
              borderBottom: '1px solid rgba(115, 213, 224, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'rgba(255, 255, 255, 0.02)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <div
                style={{
                  background: 'rgba(115, 213, 224, 0.12)',
                  border: '1px solid rgba(115, 213, 224, 0.28)',
                  padding: 5,
                  borderRadius: 6,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Ship size={16} color="#73d5e0" />
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <h3 style={{ margin: 0, fontSize: 14, color: '#e0f4f7', fontWeight: 700, letterSpacing: '0.02em' }}>
                    AIS Suspects
                  </h3>
                  {result?.ranked_vessels && result.ranked_vessels.length > 0 && (
                    <span
                      style={{
                        fontFamily: '"DM Mono", monospace',
                        fontSize: 10,
                        fontWeight: 700,
                        color: '#73d5e0',
                        background: 'rgba(115, 213, 224, 0.14)',
                        border: '1px solid rgba(115, 213, 224, 0.28)',
                        padding: '1px 6px',
                        borderRadius: 8,
                      }}
                    >
                      {Math.min(5, result.ranked_vessels.length)} found
                    </span>
                  )}
                </div>
                <span style={{ font: '10px "DM Mono", monospace', color: '#76aabd', display: 'block', marginTop: 1 }}>
                  {result?.ranked_vessels && result.ranked_vessels.length > 0
                    ? `Top ${Math.min(5, result.ranked_vessels.length)} ranked by spatiotemporal score`
                    : 'Correlated vessel intelligence'}
                </span>
              </div>
            </div>

            <button
              onClick={() => setSuspectsOpen(false)}
              style={{
                background: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                borderRadius: 5,
                color: '#76aabd',
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.18s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = '#e0f4f7';
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.12)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = '#76aabd';
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)';
              }}
              title="Close suspects panel"
            >
              <X size={15} />
            </button>
          </div>

          {/* Body */}
          <div
            className="glass-scroll"
            style={{
              padding: '12px 14px 14px',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            {!result ? (
              <div style={{ textAlign: 'center', padding: '22px 10px' }}>
                <div
                  style={{
                    display: 'inline-flex',
                    background: 'rgba(115, 213, 224, 0.08)',
                    border: '1px solid rgba(111, 202, 214, 0.2)',
                    padding: 9,
                    borderRadius: '50%',
                    marginBottom: 8,
                  }}
                >
                  <Ship size={20} color="#73d5e0" />
                </div>
                <h4 style={{ margin: '0 0 5px', fontSize: 13, color: '#e8f7fa', fontWeight: 600 }}>
                  No Suspects Analyzed Yet
                </h4>
                <p style={{ margin: 0, fontSize: 11, color: '#7aa0af', lineHeight: 1.45 }}>
                  Upload a SAR image and click <strong>Analyze Image</strong> to cross-correlate AIS vessel tracks with the spill envelope.
                </p>
              </div>
            ) : !result.ranked_vessels || result.ranked_vessels.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '18px 10px' }}>
                <p style={{ fontSize: 12, color: '#7aa0af', margin: 0 }}>
                  No vessels matched the spatiotemporal envelope for this incident.
                </p>
              </div>
            ) : (
              [...result.ranked_vessels]
                .sort((a, b) => b.attribution_score - a.attribution_score)
                .slice(0, 5)
                .map((v) => {
                  const tier = getSuspectTierStyle(v);
                  const matchPercent = Math.round(v.attribution_score * 100);
                  return (
                    <div
                      key={v.mmsi}
                      onClick={() => handleFocusVessel(v)}
                      style={{
                        background: tier.cardBg,
                        backdropFilter: 'blur(14px)',
                        WebkitBackdropFilter: 'blur(14px)',
                        border: tier.cardBorder,
                        boxShadow: tier.cardShadow,
                        borderRadius: 8,
                        padding: '11px 12px',
                        cursor: v.track_history?.length ? 'pointer' : 'default',
                        transition: 'transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.transform = 'translateY(-2px)';
                        e.currentTarget.style.borderColor = tier.accentDot;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.transform = 'translateY(0)';
                        e.currentTarget.style.border = tier.cardBorder;
                      }}
                      title={v.track_history?.length ? 'Click to focus vessel track on map' : undefined}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span
                            style={{
                              width: 7,
                              height: 7,
                              borderRadius: '50%',
                              background: tier.accentDot,
                              boxShadow: `0 0 6px ${tier.accentDot}`,
                              flexShrink: 0,
                            }}
                          />
                          <strong style={{ color: tier.nameColor, fontSize: 13, letterSpacing: '0.02em', fontWeight: 700 }}>
                            {v.vessel_name}
                          </strong>
                        </div>
                        <span
                          style={{
                            background: tier.badgeBg,
                            border: tier.badgeBorder,
                            color: tier.badgeText,
                            padding: '2px 7px',
                            borderRadius: 10,
                            fontSize: 10,
                            fontWeight: 800,
                            fontFamily: '"DM Mono", monospace',
                            letterSpacing: '0.04em',
                            flexShrink: 0,
                          }}
                        >
                          {matchPercent}% MATCH
                        </span>
                      </div>

                      <div
                        style={{
                          display: 'flex',
                          gap: 12,
                          fontSize: 11,
                          color: tier.metaColor,
                          fontFamily: '"DM Mono", monospace',
                          marginBottom: 8,
                        }}
                      >
                        <span>Type: {v.vessel_type || 'Unknown'}</span>
                        <span>MMSI: {v.mmsi}</span>
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                        <div
                          style={{
                            background: tier.chipBg,
                            border: tier.chipBorder,
                            borderRadius: 5,
                            padding: '6px 8px',
                          }}
                        >
                          <div style={{ fontSize: 9, color: tier.chipLabel, fontFamily: '"DM Mono", monospace', letterSpacing: '0.06em', marginBottom: 2 }}>
                            CPA DISTANCE
                          </div>
                          <div style={{ color: tier.chipValue, fontSize: 12, fontWeight: 700, fontFamily: '"DM Mono", monospace' }}>
                            {v.evidence.cpa_distance_km.toFixed(1)} km
                          </div>
                        </div>

                        <div
                          style={{
                            background: tier.chipBg,
                            border: tier.chipBorder,
                            borderRadius: 5,
                            padding: '6px 8px',
                          }}
                        >
                          <div style={{ fontSize: 9, color: tier.chipLabel, fontFamily: '"DM Mono", monospace', letterSpacing: '0.06em', marginBottom: 2 }}>
                            TRAJECTORY MATCH
                          </div>
                          <div style={{ color: tier.chipValue, fontSize: 12, fontWeight: 700, fontFamily: '"DM Mono", monospace' }}>
                            {v.evidence.trajectory_match}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })
            )}
          </div>
        </div>
      </div>

      {/* Open button (visible only when panel is closed) */}
      {!panelOpen && (
        <button
          onClick={() => setPanelOpen(true)}
          style={{
            position: 'absolute', top: 20, left: 20, zIndex: 5,
            background: 'rgba(10, 40, 64, 0.9)', border: '1px solid #357395', borderRadius: 6,
            color: '#c7edf6', padding: '8px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backdropFilter: 'blur(4px)'
          }}
          title="Open Spill Lab"
        >
          <PanelLeftOpen size={20} />
        </button>
      )}

      {/* Input panel */}
      {panelOpen && (
        <div style={{
          position: 'absolute', top: 0, left: 0, width: 360, height: '100%',
          background: 'rgba(7, 24, 39, 0.35)', borderRight: '1px solid rgba(27, 52, 69, 0.5)',
          padding: '20px 18px', overflowY: 'auto', zIndex: 4,
          backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)', display: 'flex', flexDirection: 'column', gap: 14,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ font: '10px "DM Mono"', color: '#76aabd', letterSpacing: '0.15em' }}>SPILL LAB</span>
              <h2 style={{ margin: '6px 0 0', fontSize: 22, letterSpacing: '-0.03em' }}>Detection Test</h2>
            </div>
            <button
              onClick={() => setPanelOpen(false)}
              style={{
                background: 'transparent', border: 'none', color: '#76aabd', cursor: 'pointer',
                padding: 4, display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'color 0.2s'
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = '#c7edf6'}
              onMouseLeave={(e) => e.currentTarget.style.color = '#76aabd'}
              title="Hide panel"
            >
              <PanelLeftClose size={20} />
            </button>
          </div>

          {/* Image upload */}
          <div style={{
            background: 'rgba(13, 38, 56, 0.4)', backdropFilter: 'blur(8px)',
            border: '1px solid rgba(111, 202, 214, 0.15)', boxShadow: '0 4px 15px rgba(0, 0, 0, 0.1)',
            borderRadius: 8, padding: 16,
          }}>
            <label style={{ font: '10px "DM Mono"', color: '#7aa0af', letterSpacing: '0.06em' }}>SAR IMAGE</label>
            <input
              ref={fileInput}
              type="file"
              accept="image/*,.tif,.tiff"
              hidden
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <button
              onClick={() => fileInput.current?.click()}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                width: '100%', marginTop: 8,
                border: '1px dashed rgba(115, 213, 224, 0.4)', background: 'rgba(115, 213, 224, 0.05)',
                color: '#73d5e0', padding: '14px 0', borderRadius: 6,
                cursor: 'pointer', fontSize: 12, fontWeight: 700,
              }}
            >
              {file ? file.name : '+ Select or drop SAR image'}
            </button>
            {file && (
              <p style={{ font: '10px "DM Mono"', color: '#68d7a7', margin: '6px 0 0' }}>
                {(file.size / 1024).toFixed(1)} KB ready
              </p>
            )}
          </div>

          {/* Coordinates */}
          <div style={{
            background: 'rgba(13, 38, 56, 0.4)', backdropFilter: 'blur(8px)',
            border: '1px solid rgba(111, 202, 214, 0.15)', boxShadow: '0 4px 15px rgba(0, 0, 0, 0.1)',
            borderRadius: 8, padding: 16,
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10,
          }}>
            <div>
              <label style={{ font: '10px "DM Mono"', color: '#7aa0af', letterSpacing: '0.06em' }}>LATITUDE</label>
              <input
                value={lat} onChange={(e) => setLat(e.target.value)}
                placeholder="e.g. 19.076"
                style={{
                  display: 'block', width: '100%', marginTop: 6,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 5,
                  color: '#d9f0f4', padding: '9px 8px',
                  font: '12px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
            <div>
              <label style={{ font: '10px "DM Mono"', color: '#7aa0af', letterSpacing: '0.06em' }}>LONGITUDE</label>
              <input
                value={lon} onChange={(e) => setLon(e.target.value)}
                placeholder="e.g. 72.877"
                style={{
                  display: 'block', width: '100%', marginTop: 6,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 5,
                  color: '#d9f0f4', padding: '9px 8px',
                  font: '12px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
            <p style={{ gridColumn: '1/-1', font: '9px "DM Mono"', color: '#638aa1', margin: '4px 0 0' }}>
              Click anywhere on the map to auto-fill coordinates.
            </p>
          </div>

          {/* Time & Date */}
          <div style={{
            background: 'rgba(13, 38, 56, 0.4)', backdropFilter: 'blur(8px)',
            border: '1px solid rgba(111, 202, 214, 0.15)', boxShadow: '0 4px 15px rgba(0, 0, 0, 0.1)',
            borderRadius: 8, padding: 16,
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10,
          }}>
            <div>
              <label style={{ font: '10px "DM Mono"', color: '#7aa0af', letterSpacing: '0.06em' }}>OBS. DATE</label>
              <input
                type="date"
                value={obsDate} onChange={(e) => setObsDate(e.target.value)}
                style={{
                  display: 'block', width: '100%', marginTop: 6,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 5,
                  color: '#d9f0f4', padding: '9px 8px',
                  font: '12px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
            <div>
              <label style={{ font: '10px "DM Mono"', color: '#7aa0af', letterSpacing: '0.06em' }}>OBS. TIME (UTC)</label>
              <input
                type="time"
                value={obsTime} onChange={(e) => setObsTime(e.target.value)}
                style={{
                  display: 'block', width: '100%', marginTop: 6,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 5,
                  color: '#d9f0f4', padding: '9px 8px',
                  font: '12px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
          </div>

          {/* Metocean Conditions */}
          <div style={{
            background: 'rgba(13, 38, 56, 0.4)', backdropFilter: 'blur(8px)',
            border: '1px solid rgba(111, 202, 214, 0.15)', boxShadow: '0 4px 15px rgba(0, 0, 0, 0.1)',
            borderRadius: 8, padding: 16,
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10,
          }}>
            <p style={{ gridColumn: '1/-1', font: '10px "DM Mono"', color: '#7aa0af', margin: '0 0 4px', letterSpacing: '0.06em' }}>
              METOCEAN (PHYSICS) INPUTS
            </p>
            <div>
              <label style={{ font: '9px "DM Mono"', color: '#638aa1' }}>WIND SPEED (m/s)</label>
              <input
                value={windSpeed} onChange={(e) => setWindSpeed(e.target.value)}
                style={{
                  display: 'block', width: '100%', marginTop: 2,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 4,
                  color: '#d9f0f4', padding: '6px', font: '11px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
            <div>
              <label style={{ font: '9px "DM Mono"', color: '#638aa1' }}>WIND DIR (°)</label>
              <input
                value={windDir} onChange={(e) => setWindDir(e.target.value)}
                style={{
                  display: 'block', width: '100%', marginTop: 2,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 4,
                  color: '#d9f0f4', padding: '6px', font: '11px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
            <div>
              <label style={{ font: '9px "DM Mono"', color: '#638aa1' }}>CURR SPEED (m/s)</label>
              <input
                value={currSpeed} onChange={(e) => setCurrSpeed(e.target.value)}
                style={{
                  display: 'block', width: '100%', marginTop: 2,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 4,
                  color: '#d9f0f4', padding: '6px', font: '11px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
            <div>
              <label style={{ font: '9px "DM Mono"', color: '#638aa1' }}>CURR DIR (°)</label>
              <input
                value={currDir} onChange={(e) => setCurrDir(e.target.value)}
                style={{
                  display: 'block', width: '100%', marginTop: 2,
                  background: '#081d2b', border: '1px solid #315b6d', borderRadius: 4,
                  color: '#d9f0f4', padding: '6px', font: '11px "DM Mono", monospace', outline: 'none',
                }}
              />
            </div>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              onClick={resetForm}
              disabled={loading}
              style={{
                width: '30%', padding: '13px 0', borderRadius: 7,
                border: '1px solid #29475a',
                background: 'rgba(13, 38, 56, 0.4)',
                color: '#7aa0af',
                fontSize: 13, fontWeight: 800, cursor: loading ? 'not-allowed' : 'pointer',
                letterSpacing: '0.02em',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s',
              }}
            >
              Clear
            </button>
            <button
              onClick={analyze}
              disabled={!validInput || loading}
              style={{
                flex: 1, padding: '13px 0', borderRadius: 7,
                border: validInput && !loading ? '1px solid #6fcad6' : '1px solid #29475a',
                background: validInput && !loading ? '#77cfda' : '#1a3344',
                color: validInput && !loading ? '#041523' : '#5c7f8e',
                fontSize: 13, fontWeight: 800, cursor: validInput && !loading ? 'pointer' : 'not-allowed',
                letterSpacing: '0.02em',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              }}
            >
              {loading ? <Activity size={16} /> : <ScanSearch size={16} />}
              {loading ? 'Running U-Net inference…' : 'Analyze Image'}
            </button>
          </div>

          {/* Error */}
          {error && (
            <div style={{
              background: '#3b1c20', border: '1px solid #804039', borderRadius: 8,
              padding: '12px 14px', color: '#ffaaa1', fontSize: 12,
            }}>
              <strong>Error:</strong> {error}
              <button
                onClick={() => setError(null)}
                style={{
                  display: 'block', marginTop: 8, background: 'transparent',
                  border: '1px solid #804039', color: '#ffaaa1', padding: '4px 10px',
                  borderRadius: 4, cursor: 'pointer', fontSize: 11,
                }}
              >Dismiss</button>
            </div>
          )}

          {/* No oil result */}
          {noOil && (
            <div style={{
              background: '#382913', border: '1px solid #755a34', borderRadius: 8,
              padding: '18px 16px', textAlign: 'center',
            }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
                <Waves size={36} color="#ffce83" />
              </div>
              <h3 style={{ margin: '0 0 6px', fontSize: 16, color: '#ffce83' }}>No Oil Spill Detected</h3>
              <p style={{ fontSize: 12, color: '#c4a46e', margin: 0 }}>
                The U-Net model did not identify significant oil spill features in the provided image. This may be clean water, a look-alike, or a non-SAR image.
              </p>
            </div>
          )}



        </div>
      )}
    </div>
  );
}
