import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

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
}

export function SpillLabPage() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noOil, setNoOil] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
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

  const clearMapLayers = () => {
    const map = mapRef.current;
    if (!map) return;
    if (map.getLayer('spill-fill')) map.removeLayer('spill-fill');
    if (map.getLayer('spill-outline')) map.removeLayer('spill-outline');
    if (map.getLayer('centroid-point')) map.removeLayer('centroid-point');
    if (map.getSource('spill-polygon')) map.removeSource('spill-polygon');
    if (map.getSource('spill-centroid')) map.removeSource('spill-centroid');
  };

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

    map.addSource('spill-polygon', { type: 'geojson', data: polygon });
    map.addSource('spill-centroid', { type: 'geojson', data: centroidPt });

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

    // Fly to the spill
    map.flyTo({
      center: [res.geometry.centroid.lon, res.geometry.centroid.lat],
      zoom: 10,
      duration: 2000,
    });
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

      const resp = await fetch(`${BASE_URL}/api/v1/analyze`, {
        method: 'POST',
        body: form,
        signal: AbortSignal.timeout(120_000),
      });

      if (!resp.ok) {
        let detail = `Server error (${resp.status})`;
        try { const b = await resp.json(); detail = b.detail ?? detail; } catch {}
        throw new Error(detail);
      }

      const data: AnalysisResult = await resp.json();

      if (data.segmentation_confidence > 0.3 && data.geometry.area_km2 > 0.01) {
        setResult(data);
        setNoOil(false);
        drawSpillOnMap(data);
      } else {
        setNoOil(true);
        setResult(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed.');
    } finally {
      setLoading(false);
    }
  };

  const validInput = file && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))
    && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lon)) <= 180;

  return (
    <div style={{ width: '100%', height: '100vh', position: 'relative', background: '#061523' }}>
      {/* Full-screen map */}
      <div ref={mapContainer} style={{ width: '100%', height: '100%' }} />

      {/* Toggle button */}
      <button
        onClick={() => setPanelOpen(!panelOpen)}
        style={{
          position: 'absolute', top: 14, left: panelOpen ? 374 : 14, zIndex: 5,
          background: '#0a2840e8', border: '1px solid #357395', borderRadius: 6,
          color: '#c7edf6', padding: '8px 12px', cursor: 'pointer', fontSize: 12,
          fontFamily: 'DM Mono, monospace', transition: 'left 0.3s',
        }}
      >
        {panelOpen ? '◀ Hide' : '▶ SpillLab'}
      </button>

      {/* Input panel */}
      {panelOpen && (
        <div style={{
          position: 'absolute', top: 0, left: 0, width: 360, height: '100%',
          background: '#071827f0', borderRight: '1px solid #1b3445',
          padding: '20px 18px', overflowY: 'auto', zIndex: 4,
          backdropFilter: 'blur(12px)', display: 'flex', flexDirection: 'column', gap: 14,
        }}>
          <div>
            <span style={{ font: '10px "DM Mono"', color: '#76aabd', letterSpacing: '0.15em' }}>SPILL LAB</span>
            <h2 style={{ margin: '6px 0 4px', fontSize: 22, letterSpacing: '-0.03em' }}>Detection Test</h2>
            <p style={{ fontSize: 12, color: '#8ba4b1', margin: 0 }}>Upload a SAR image and set the observation coordinates. The U-Net model will segment oil spills and plot them on the map.</p>
          </div>

          {/* Image upload */}
          <div style={{
            background: '#0d2638', border: '1px solid #29475a', borderRadius: 8, padding: 16,
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
                display: 'block', width: '100%', marginTop: 8,
                border: '1px dashed #3a6a7e', background: 'transparent',
                color: '#73d5e0', padding: '14px 0', borderRadius: 6,
                cursor: 'pointer', fontSize: 12, fontWeight: 700,
              }}
            >
              {file ? `📎 ${file.name}` : '+ Select or drop SAR image'}
            </button>
            {file && (
              <p style={{ font: '10px "DM Mono"', color: '#68d7a7', margin: '6px 0 0' }}>
                {(file.size / 1024).toFixed(1)} KB ready
              </p>
            )}
          </div>

          {/* Coordinates */}
          <div style={{
            background: '#0d2638', border: '1px solid #29475a', borderRadius: 8, padding: 16,
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

          {/* Analyze button */}
          <button
            onClick={analyze}
            disabled={!validInput || loading}
            style={{
              width: '100%', padding: '13px 0', borderRadius: 7,
              border: validInput && !loading ? '1px solid #6fcad6' : '1px solid #29475a',
              background: validInput && !loading ? '#77cfda' : '#1a3344',
              color: validInput && !loading ? '#041523' : '#5c7f8e',
              fontSize: 13, fontWeight: 800, cursor: validInput && !loading ? 'pointer' : 'not-allowed',
              letterSpacing: '0.02em',
            }}
          >
            {loading ? '⏳ Running U-Net inference…' : '🛰️ Analyze Image'}
          </button>

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
              <div style={{ fontSize: 36, marginBottom: 8 }}>🌊</div>
              <h3 style={{ margin: '0 0 6px', fontSize: 16, color: '#ffce83' }}>No Oil Spill Detected</h3>
              <p style={{ fontSize: 12, color: '#c4a46e', margin: 0 }}>
                The U-Net model did not identify significant oil spill features in the provided image. This may be clean water, a look-alike, or a non-SAR image.
              </p>
            </div>
          )}

          {/* Detection results */}
          {result && (
            <div style={{
              background: '#103525', border: '1px solid #39745a', borderRadius: 8,
              padding: '16px 14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <div style={{ fontSize: 20 }}>🛢️</div>
                <div>
                  <h3 style={{ margin: 0, fontSize: 15, color: '#99e2b8' }}>Oil Spill Detected</h3>
                  <span style={{ font: '9px "DM Mono"', color: '#6db89a' }}>{result.spill_id}</span>
                </div>
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 14px',
              }}>
                {[
                  ['Confidence', `${Math.round(result.segmentation_confidence * 100)}%`],
                  ['Area', `${result.geometry.area_km2} km²`],
                  ['Perimeter', `${result.geometry.perimeter_km} km`],
                  ['Orientation', `${result.geometry.orientation_degrees}°`],
                  ['Centroid Lat', result.geometry.centroid.lat.toFixed(5)],
                  ['Centroid Lon', result.geometry.centroid.lon.toFixed(5)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span style={{ font: '9px "DM Mono"', color: '#6db89a', letterSpacing: '0.08em' }}>{label}</span>
                    <strong style={{ display: 'block', fontSize: 16, color: '#e8fff0', marginTop: 2 }}>{value}</strong>
                  </div>
                ))}
              </div>

              <div style={{
                marginTop: 12, padding: '8px 10px', background: '#0a2e1f',
                borderRadius: 5, font: '10px "DM Mono"', color: '#7cc8a5',
              }}>
                📍 Spill polygon plotted on the map
              </div>
            </div>
          )}

          {/* Map legend */}
          <div style={{
            marginTop: 'auto', padding: '10px 0', borderTop: '1px solid #20394a',
            font: '9px "DM Mono"', color: '#6f8c9a',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '4px 0' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#73d5e0', display: 'inline-block' }} />
              Click location
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '4px 0' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#f6a623', display: 'inline-block' }} />
              Spill boundary
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '4px 0' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#ff3d2e', display: 'inline-block' }} />
              Spill centroid
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
