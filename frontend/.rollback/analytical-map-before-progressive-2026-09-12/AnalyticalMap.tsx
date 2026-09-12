import { useEffect, useRef } from 'react';
import maplibregl, { type Map, type Popup } from 'maplibre-gl';
import type { DashboardPayload, GeoFeature } from '../types/domain';
import { useUiStore } from '../store/uiStore';
import 'maplibre-gl/dist/maplibre-gl.css';

const colors: Record<string, string> = { spill:'#f06b60', centroid:'#f5534b', origin:'#ffc15b', 'origin-zone':'#e9b154', hindcast:'#b6bfd8', forecast:'#62dca0', 'forecast-region':'#4fd485', ais:'#aebbd6', vessels:'#ffc15b' };
const interactiveLayers = ['sar-footprint','spill','origin-zone','forecast-region','hindcast','forecast','ais','origin'];

function featureLabel(feature: maplibregl.MapGeoJSONFeature) {
  const title = String(feature.properties?.title ?? feature.properties?.mmsi ?? 'Investigation layer');
  const area = feature.properties?.areaKm2;
  const perimeter = feature.properties?.perimeterKm;
  const uncertainty = feature.properties?.uncertaintyKm;
  const rows = [area ? `Area: <b>${area} km²</b>` : '', perimeter ? `Perimeter: <b>${perimeter} km</b>` : '', uncertainty ? `Uncertainty: <b>±${uncertainty} km</b>` : ''].filter(Boolean);
  return `<strong>${title}</strong>${rows.length ? `<br/><span>${rows.join(' · ')}</span>` : '<br/><span>Demo / simulated evidence</span>'}`;
}

export function AnalyticalMap({ data }: { data: DashboardPayload }) {
  const element = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const markerElements = useRef<Record<string, HTMLElement>>({});
  const layers = useUiStore((state) => state.layers);
  const select = useUiStore((state) => state.selectFeature);

  useEffect(() => {
    if (!element.current) return;
    const map = new maplibregl.Map({
      container: element.current,
      style: { version:8, sources:{ satellite:{ type:'raster', tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize:256, attribution:'Tiles © Esri' } }, layers:[{ id:'satellite', type:'raster', source:'satellite', paint:{ 'raster-brightness-max':.68, 'raster-saturation':-.25, 'raster-contrast':.18 } }] },
      center: data.incident.location, zoom: 7,
    });
    const markers: maplibregl.Marker[] = [];
    let hoverPopup: Popup | null = null;
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.FullscreenControl(), 'top-right');
    map.on('load', () => {
      map.addSource('investigation', { type:'geojson', data:data.map as GeoJSON.FeatureCollection });
      map.addLayer({ id:'sar-footprint', type:'fill', source:'investigation', filter:['==',['get','layer'],'sar-footprint'], paint:{ 'fill-color':'#cad7db', 'fill-opacity':.18 } });
      map.addLayer({ id:'sar-footprint-outline', type:'line', source:'investigation', filter:['==',['get','layer'],'sar-footprint'], paint:{ 'line-color':'#e4f1f3', 'line-width':1.3, 'line-dasharray':[2,2] } });
      (['origin-zone','spill','forecast-region'] as const).forEach((id) => {
        map.addLayer({ id, type:'fill', source:'investigation', filter:['==',['get','layer'],id], paint:{ 'fill-color':colors[id], 'fill-opacity':id==='spill'?.5:id==='origin-zone'?.34:.2 } });
        map.addLayer({ id:`${id}-outline`, type:'line', source:'investigation', filter:['==',['get','layer'],id], paint:{ 'line-color':colors[id], 'line-width':id==='forecast-region'?2.3:1.5, 'line-dasharray':id==='forecast-region'?[2,1]:[1,0] } });
      });
      (['hindcast','forecast','ais'] as const).forEach((id) => map.addLayer({ id, type:'line', source:'investigation', filter:['==',['get','layer'],id], paint:{ 'line-color':colors[id], 'line-width':id==='ais'?2:3, 'line-dasharray':id==='ais'?[2,2]:[1,0] } }));
      map.addLayer({ id:'origin', type:'circle', source:'investigation', filter:['==',['get','layer'],'origin'], paint:{ 'circle-color':colors.origin, 'circle-radius':7, 'circle-stroke-color':'#fff6d6', 'circle-stroke-width':1.4 } });

      data.map.features.filter((feature): feature is Extract<GeoFeature, { geometry: { type:'Point' } }> => feature.geometry.type === 'Point').forEach((feature) => {
        const layer = String(feature.properties.layer);
        if (layer !== 'centroid' && layer !== 'vessels') return;
        const node = document.createElement('button');
        node.type = 'button'; node.className = layer === 'centroid' ? 'critical-incident-marker' : 'ship-marker';
        node.setAttribute('aria-label', layer === 'centroid' ? 'Detected spill incident' : `Candidate vessel ${String(feature.properties.title ?? '')}`);
        node.innerHTML = layer === 'centroid' ? '<span></span>' : '<span>⛴</span>';
        node.addEventListener('click', () => select(String(feature.properties.title ?? feature.properties.mmsi ?? layer)));
        markerElements.current[layer === 'centroid' ? 'centroid' : String(feature.properties.mmsi)] = node;
        markers.push(new maplibregl.Marker({ element:node, anchor:'center' }).setLngLat(feature.geometry.coordinates).addTo(map));
      });
      map.on('mousemove', interactiveLayers, (event) => {
        const feature = event.features?.[0]; if (!feature) return;
        map.getCanvas().style.cursor = 'crosshair'; hoverPopup?.remove();
        hoverPopup = new maplibregl.Popup({ closeButton:false, closeOnClick:false, offset:10, className:'intel-map-popup' }).setLngLat(event.lngLat).setHTML(featureLabel(feature)).addTo(map);
      });
      map.on('mouseleave', interactiveLayers, () => { map.getCanvas().style.cursor = ''; hoverPopup?.remove(); hoverPopup = null; });
      map.on('click', (event) => { const feature = map.queryRenderedFeatures(event.point, { layers:interactiveLayers })[0]; if (feature) select(String(feature.properties?.title ?? feature.properties?.mmsi ?? feature.properties?.layer)); });
      map.fitBounds([[64.6,14.6],[66.1,15.8]], { padding:36, duration:0 });
    });
    mapRef.current = map;
    return () => { markers.forEach((marker) => marker.remove()); map.remove(); markerElements.current = {}; };
  }, [data, select]);

  useEffect(() => {
    const map = mapRef.current; if (!map) return;
    Object.entries(layers).forEach(([id, shown]) => {
      const visibility = shown ? 'visible' : 'none';
      [id, `${id}-outline`].forEach((layerId) => { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', visibility); });
    });
    const centroid = markerElements.current.centroid; if (centroid) centroid.style.display = layers.centroid ? '' : 'none';
    Object.entries(markerElements.current).filter(([id]) => id !== 'centroid').forEach(([, node]) => { node.style.display = layers.vessels ? '' : 'none'; });
  }, [layers]);

  return <div className="map" ref={element} />;
}
