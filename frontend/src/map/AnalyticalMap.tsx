import { useEffect, useRef, useState } from 'react';
import maplibregl, { type Map, type Popup } from 'maplibre-gl';
import type { DashboardPayload, GeoFeature, LngLat } from '../types/domain';
import { useUiStore } from '../store/uiStore';
import 'maplibre-gl/dist/maplibre-gl.css';

const interactiveLayers = ['sar-footprint','spill','origin-zone','forecast-region','hindcast','forecast','ais','origin'];
const pointAt = (path: LngLat[], progress: number): LngLat => {
  const length = path.length - 1; const value = Math.min(length, progress * length); const index = Math.floor(value); const remainder = value - index;
  const from = path[index]; const to = path[Math.min(index + 1, length)];
  return [from[0] + (to[0] - from[0]) * remainder, from[1] + (to[1] - from[1]) * remainder];
};
function featureLabel(feature: maplibregl.MapGeoJSONFeature) {
  const title = String(feature.properties?.title ?? feature.properties?.mmsi ?? 'Investigation layer');
  const rows = [feature.properties?.areaKm2 ? `Area: <b>${feature.properties.areaKm2} km²</b>` : '', feature.properties?.perimeterKm ? `Perimeter: <b>${feature.properties.perimeterKm} km</b>` : '', feature.properties?.uncertaintyKm ? `Uncertainty: <b>±${feature.properties.uncertaintyKm} km</b>` : ''].filter(Boolean);
  return `<strong>${title}</strong>${rows.length ? `<br/><span>${rows.join(' · ')}</span>` : '<br/><span>Demo / simulated evidence</span>'}`;
}

export function AnalyticalMap({ data, onPipelineStage, pipelineRunVersion = 0 }: { data: DashboardPayload; onPipelineStage?: (stage: number) => void; pipelineRunVersion?: number }) {
  const element = useRef<HTMLDivElement>(null); const mapRef = useRef<Map | null>(null); const markerElements = useRef<Record<string, HTMLElement>>({});
  const layers = useUiStore((state) => state.layers); const select = useUiStore((state) => state.selectFeature); const visualMode = useUiStore((state) => state.visualMode); const setVisualMode = useUiStore((state) => state.setVisualMode);
  const [runVersion, setRunVersion] = useState(0); const playedRun = useRef(0);
  useEffect(() => {
    if (!element.current) return;
    const forecast = visualMode === 'enhanced' ? '#5eb9df' : '#4da9ba';
    const map = new maplibregl.Map({ container:element.current, style:{ version:8, sources:{ satellite:{ type:'raster', tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize:256, attribution:'Tiles © Esri' } }, layers:[{ id:'satellite', type:'raster', source:'satellite', paint:{ 'raster-brightness-max':visualMode==='enhanced'?.74:.68, 'raster-saturation':visualMode==='enhanced'?-1:-.25, 'raster-contrast':visualMode==='enhanced'?.62:.18, 'raster-brightness-min':visualMode==='enhanced'?.08:0 } }] }, center:data.incident.location, zoom:7 });
    const markers: maplibregl.Marker[] = []; const shipMarkers: { marker:maplibregl.Marker; path:LngLat[]; node:HTMLElement }[] = []; const timers:ReturnType<typeof setTimeout>[] = [];
    let hoverPopup: Popup | null = null; let shipPopup: Popup | null = null; let animationFrame = 0;
    const visibility = (id:string, show:boolean) => [id, `${id}-outline`].forEach((layer) => { if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', show ? 'visible' : 'none'); });
    map.addControl(new maplibregl.NavigationControl(), 'top-right'); map.addControl(new maplibregl.FullscreenControl(), 'top-right');
    map.on('load', () => {
      map.addSource('investigation', { type:'geojson', data:data.map as GeoJSON.FeatureCollection });
      map.addLayer({ id:'sar-footprint', type:'fill', source:'investigation', filter:['==',['get','layer'],'sar-footprint'], paint:{ 'fill-color':'#cad7db', 'fill-opacity':.18 } });
      map.addLayer({ id:'sar-footprint-outline', type:'line', source:'investigation', filter:['==',['get','layer'],'sar-footprint'], paint:{ 'line-color':'#e4f1f3', 'line-width':1.3, 'line-dasharray':[2,2] } });
      (['origin-zone','spill','forecast-region'] as const).forEach((id) => {
        const color = id === 'origin-zone' ? '#e9b154' : id === 'spill' ? '#f06b60' : forecast;
        map.addLayer({ id, type:'fill', source:'investigation', filter:['==',['get','layer'],id], paint:{ 'fill-color':color, 'fill-opacity':id==='spill'?.52:id==='origin-zone'?.34:.2 } });
        map.addLayer({ id:`${id}-outline`, type:'line', source:'investigation', filter:['==',['get','layer'],id], paint:{ 'line-color':color, 'line-width':id==='forecast-region'?2.3:1.5, 'line-dasharray':id==='forecast-region'?[2,1]:[1,0] } });
      });
      (['hindcast','forecast','ais'] as const).forEach((id) => map.addLayer({ id, type:'line', source:'investigation', filter:['==',['get','layer'],id], paint:{ 'line-color':id==='forecast'?forecast:id==='hindcast'?'#b6bfd8':'#aebbd6', 'line-width':id==='ais'?2:3, 'line-dasharray':id==='ais'?[2,2]:[1,0] } }));
      map.addLayer({ id:'origin', type:'circle', source:'investigation', filter:['==',['get','layer'],'origin'], paint:{ 'circle-color':'#ffc15b', 'circle-radius':7, 'circle-stroke-color':'#fff6d6', 'circle-stroke-width':1.4 } });
      const tracks = new globalThis.Map<string, LngLat[]>();
      data.map.features.forEach((feature) => { if (feature.geometry.type === 'LineString' && feature.properties.layer === 'ais' && typeof feature.properties.mmsi === 'string') tracks.set(feature.properties.mmsi, feature.geometry.coordinates); });
      data.map.features.filter((feature): feature is Extract<GeoFeature, { geometry:{type:'Point'} }> => feature.geometry.type === 'Point').forEach((feature) => {
        const layer = String(feature.properties.layer); if (layer !== 'centroid' && layer !== 'vessels') return;
        const node = document.createElement('button'); node.type = 'button'; node.className = layer === 'centroid' ? 'critical-incident-marker' : 'ship-marker';
        node.setAttribute('aria-label', layer === 'centroid' ? 'Detected spill incident' : `Candidate vessel ${String(feature.properties.title ?? '')}`); node.innerHTML = layer === 'centroid' ? '<span></span>' : '<span>⛴</span>';
        node.addEventListener('click', () => select(String(feature.properties.title ?? feature.properties.mmsi ?? layer))); const id = layer === 'centroid' ? 'centroid' : String(feature.properties.mmsi); markerElements.current[id] = node;
        const path = tracks.get(id); const marker = new maplibregl.Marker({ element:node, anchor:'center' }).setLngLat(path?.[0] ?? feature.geometry.coordinates).addTo(map); markers.push(marker);
        if (path) {
          const candidate = data.attribution.candidates.find((item) => item.vessel.mmsi === id);
          const vesselName = candidate?.vessel.name ?? String(feature.properties.title ?? 'Candidate vessel');
          const hoverDetails = () => { const coordinates = marker.getLngLat(); return `<strong>${vesselName}</strong><br/><span>MMSI ${id} · ${coordinates.lat.toFixed(4)}° N / ${coordinates.lng.toFixed(4)}° E<br/>Rank #${candidate?.rank ?? '—'} · Evidence score ${candidate?.score.toFixed(2) ?? '—'}</span>`; };
          node.addEventListener('mouseenter', () => { shipPopup?.remove(); shipPopup = new maplibregl.Popup({ closeButton:false, closeOnClick:false, offset:18, className:'intel-map-popup vessel-hover-popup' }).setLngLat(marker.getLngLat()).setHTML(hoverDetails()).addTo(map); });
          node.addEventListener('mouseleave', () => { shipPopup?.remove(); shipPopup = null; });
          shipMarkers.push({ marker, path, node });
        }
      });
      map.on('mousemove', interactiveLayers, (event) => { const feature = event.features?.[0]; if (!feature) return; map.getCanvas().style.cursor = 'crosshair'; hoverPopup?.remove(); hoverPopup = new maplibregl.Popup({ closeButton:false, closeOnClick:false, offset:10, className:'intel-map-popup' }).setLngLat(event.lngLat).setHTML(featureLabel(feature)).addTo(map); });
      map.on('mouseleave', interactiveLayers, () => { map.getCanvas().style.cursor = ''; hoverPopup?.remove(); hoverPopup = null; });
      map.on('click', (event) => { const feature = map.queryRenderedFeatures(event.point, { layers:interactiveLayers })[0]; if (feature) select(String(feature.properties?.title ?? feature.properties?.mmsi ?? feature.properties?.layer)); });
      map.fitBounds([[64.6,14.6],[66.1,15.8]], { padding:36, duration:0 });
      const activeRunVersion = Math.max(runVersion, pipelineRunVersion);
      const shouldAnimatePipeline = activeRunVersion > playedRun.current;
      if (shouldAnimatePipeline) {
        playedRun.current = activeRunVersion;
        ['spill','origin-zone','origin','hindcast','forecast','forecast-region','ais'].forEach((id) => visibility(id, false)); shipMarkers.forEach(({node}) => { node.style.opacity = '0'; });
        onPipelineStage?.(0);
        timers.push(setTimeout(() => { visibility('spill', true); onPipelineStage?.(1); }, 380));
        timers.push(setTimeout(() => onPipelineStage?.(2), 780));
        timers.push(setTimeout(() => { visibility('origin-zone', true); visibility('origin', true); onPipelineStage?.(3); }, 1180));
        timers.push(setTimeout(() => { visibility('hindcast', true); onPipelineStage?.(4); }, 1580));
        timers.push(setTimeout(() => onPipelineStage?.(5), 1980));
        timers.push(setTimeout(() => { visibility('forecast', true); visibility('forecast-region', true); onPipelineStage?.(6); }, 2380));
        timers.push(setTimeout(() => onPipelineStage?.(7), 2780));
        timers.push(setTimeout(() => { visibility('ais', true); shipMarkers.forEach(({node}) => { node.style.opacity = '1'; }); onPipelineStage?.(8); const started = performance.now(); const travel = (time:number) => { const progress = Math.min(1, (time - started) / 4200); shipMarkers.forEach(({marker,path}) => marker.setLngLat(pointAt(path, progress))); if (progress < 1) animationFrame = requestAnimationFrame(travel); else onPipelineStage?.(9); }; animationFrame = requestAnimationFrame(travel); }, 3180));
      } else { visibility('origin-zone', false); }
    });
    mapRef.current = map;
    return () => { timers.forEach(clearTimeout); cancelAnimationFrame(animationFrame); hoverPopup?.remove(); shipPopup?.remove(); markers.forEach((marker) => marker.remove()); map.remove(); markerElements.current = {}; };
  }, [data, select, visualMode, runVersion, pipelineRunVersion]);
  useEffect(() => { const map = mapRef.current; if (!map) return; Object.entries(layers).forEach(([id, shown]) => { [id, `${id}-outline`].forEach((layer) => { if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', shown ? 'visible' : 'none'); }); }); const centroid = markerElements.current.centroid; if (centroid) centroid.style.display = layers.centroid ? '' : 'none'; Object.entries(markerElements.current).filter(([id]) => id !== 'centroid').forEach(([, node]) => { node.style.display = layers.vessels ? '' : 'none'; }); }, [layers]);
  return <div className={`map-frame ${visualMode}`}><div className="map" ref={element}/><div className="map-actions"><button className="map-visual-toggle" onClick={() => setVisualMode(visualMode === 'enhanced' ? 'classic' : 'enhanced')}>{visualMode === 'enhanced' ? 'Classic satellite' : 'Enhanced SAR'}</button><button className="run-pipeline-button" onClick={() => { onPipelineStage?.(0); setRunVersion((version) => version + 1); }}>Run pipeline</button></div></div>;
}
