import { motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, Download, FileWarning, Plus, ShieldAlert, Activity, Anchor, Crosshair, MapPin, Radar, Search, Wind, Waves, CloudSun, MousePointer2, SquareDashedMousePointer, Trash2 } from 'lucide-react';
import { BarChart, Bar, ResponsiveContainer, Tooltip, XAxis, YAxis, RadarChart, PolarGrid, PolarAngleAxis, Radar as RadarLine } from 'recharts';
import { Link, useNavigate } from 'react-router-dom';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { AnalyticalMap } from '../map/AnalyticalMap';
import { Globe } from '../globe/Globe';
import { useDashboard } from '../hooks/useDashboard';
import { Badge, EmptyState, FeaturePanel, LayerControl, Metric, Pipeline, Shell } from '../components/Ui';
import { scenarios, dashboardScenario } from '../mock/scenarios';
import { useUiStore } from '../store/uiStore';
import { analyzeSpill, ApiError, fetchLiveMetocean, fetchScenario, downloadForensicPdf } from '../services/api';
import { mapBackendToDashboard } from '../services/mapper';
import type { DashboardPayload, PipelineStage } from '../types/domain';

// ─── Shared layout wrappers ────────────────────────────────────────────

type DraftCoordinate = { latitude: string; longitude: string };

function Loading(){return <Shell><div className="loading">Establishing data connection.</div></Shell>}
function Content({children}:{children:(data:NonNullable<ReturnType<typeof useDashboard>['data']>)=>React.ReactNode}){const q=useDashboard();if(q.isLoading||!q.data)return <Loading/>;return <Shell>{children(q.data)}</Shell>}

// ─── Coordinate picker (inline mini-map) ──────────────────────────────

function CoordinatePicker({value,onChange}:{value:DraftCoordinate;onChange:(v:DraftCoordinate)=>void}){
  const el=useRef<HTMLDivElement>(null);
  const map=useRef<MapLibreMap|null>(null);
  const marker=useRef<maplibregl.Marker|null>(null);
  useEffect(()=>{
    if(!el.current)return;
    const m=new maplibregl.Map({container:el.current,style:'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',center:[65.42,15.21],zoom:4,attributionControl:false});
    m.addControl(new maplibregl.NavigationControl(),'top-right');
    const mk=new maplibregl.Marker({draggable:true}).setLngLat([65.42,15.21]).addTo(m);
    mk.on('dragend',()=>{const ll=mk.getLngLat();onChange({latitude:ll.lat.toFixed(5),longitude:ll.lng.toFixed(5)})});
    m.on('click',e=>{mk.setLngLat(e.lngLat);onChange({latitude:e.lngLat.lat.toFixed(5),longitude:e.lngLat.lng.toFixed(5)})});
    map.current=m;marker.current=mk;
    return()=>{m.remove()};
  },[]);// eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{
    const lat=Number(value.latitude),lon=Number(value.longitude);
    if(Number.isFinite(lat)&&Number.isFinite(lon)&&marker.current){marker.current.setLngLat([lon,lat])}
  },[value.latitude,value.longitude]);
  return <div ref={el} style={{width:'100%',height:'100%',minHeight:260,borderRadius:'var(--radius)'}}/>;
}

// ─── Landing Page ─────────────────────────────────────────────────────

export function LandingPage(){return <div className="landing"><header className="landing-nav"><span className="brand"><span>OILSPILL</span><small>INTELLIGENCE</small></span><Link to="/dashboard">Open operations center <ArrowRight size={16}/></Link></header><section className="hero"><div><span className="eyebrow">SATELLITE-DRIVEN MARITIME INVESTIGATION</span><h1>See the evidence<br/><em>move across the sea.</em></h1><p>A demonstration command center for oil-spill detection, drift tracing, and responsible vessel-attribution analysis.</p><div className="actions"><Link className="button" to="/create">Analyze incident <ArrowRight/></Link><Link className="button quiet" to="/dashboard">Open operations center</Link></div><div className="modules">
{[['Sentinel-1 SAR','Satellite radar detection','satellite'],['U-Net Segmentation','Deep learning oil mask','detection'],['SlickTrace Drift','Physics hindcast engine','drift'],['AIS Attribution','Vessel evidence scoring','attribution']].map(([t,d,k])=><article key={k} className="module panel"><h3>{t}</h3><p>{d}</p></article>)}
</div></div><Globe/></section></div>}

// ─── Dashboard ────────────────────────────────────────────────────────

export function DashboardPage(){return <Content>{d=>{const hasRealData=!d.demo;return <><section className="page-head"><div><span className="eyebrow">{hasRealData?'LIVE OPERATIONS CENTER':'OPERATIONS CENTER / DEMO SCENARIO'}</span><h1>Investigation dashboard</h1></div>{hasRealData?<Badge tone="green">LIVE</Badge>:<Badge>{d.scenario.replace(/-/g,' ').toUpperCase()}</Badge>}</section><div className="metrics">{[['Detection',d.detection.detected?`${Math.round((d.detection.confidence??0)*100)}%`:'None',d.detection.detected?'Oil confirmed':'No oil'],['Area',d.spill?`${d.spill.areaKm2} km²`:'—',d.spill?'Spill extent':'N/A'],['AIS',d.incident.aisCoverage,d.attribution.candidates.length?`${d.attribution.candidates.length} vessels`:'None'],['Confidence',d.confidence.overall,d.confidence.score?`${d.confidence.score}/100`:'']].map(([l,v,det])=><Metric key={l} label={l as string} value={v as string} detail={det as string}/>)}</div><Pipeline stages={d.pipeline} live={hasRealData}/><div className="dash-grid"><DataQuality data={d}/><Confidence data={d}/></div></>}}</Content>}

// ─── Incidents ────────────────────────────────────────────────────────

export function IncidentsPage(){return <Content>{d=><><section className="page-head"><div><span className="eyebrow">INCIDENT REGISTRY</span><h1>Tracked incidents</h1></div><Link className="button" to="/create"><Plus size={16}/> New investigation</Link></section>{d.demo?<div className="incident-grid">{scenarios.map(s=>{const inc=require_scenario(s.id);return <Link to="/dashboard" key={s.id} onClick={()=>useUiStore.getState().setScenario(s.id)} className="incident panel"><Badge tone={inc.status==='COMPLETE'?'green':inc.status==='NO_OIL'?'muted':inc.status==='FAILED'?'red':'amber'}>{inc.status}</Badge><h3>{inc.id}</h3><small>{inc.region}</small></Link>})}</div>:<div className="incident-grid"><div className="incident panel"><Badge tone={d.incident.status==='COMPLETE'?'green':d.incident.status==='NO_OIL'?'muted':'amber'}>{d.incident.status}</Badge><h3>{d.incident.id}</h3><small>{d.incident.region}</small><small>Confidence: {d.confidence.overall}</small></div></div>}</>}</Content>}

function require_scenario(id: string) {
  return dashboardScenario(id as any).incident;
}

// ─── Create Incident (REAL API INTEGRATION) ───────────────────────────

export function CreateIncidentPage(){return <Shell><CreateIncidentWorkflow/></Shell>}

function CreateIncidentWorkflow(){
  const navigate=useNavigate();
  const input=useRef<HTMLInputElement>(null);
  const [file,setFile]=useState<File|null>(null);
  const [coordinate,setCoordinate]=useState<DraftCoordinate>({latitude:'',longitude:''});
  const [eventDate,setEventDate]=useState('');
  const [eventTime,setEventTime]=useState('');
  const [windSpeed,setWindSpeed]=useState('7.5');
  const [windDir,setWindDir]=useState('220');
  const [currentSpeed,setCurrentSpeed]=useState('0.35');
  const [currentDir,setCurrentDir]=useState('45');
  const [showMetocean,setShowMetocean]=useState(false);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [stages,setStages]=useState<PipelineStage[]>([
    {id:'upload',label:'Uploading image',status:'pending'},
    {id:'segmentation',label:'Running U-Net segmentation',status:'pending'},
    {id:'verification',label:'Look-alike verification',status:'pending'},
    {id:'geometry',label:'Spill geometry extraction',status:'pending'},
    {id:'drift',label:'Physics drift analysis',status:'pending'},
    {id:'ais',label:'AIS vessel search',status:'pending'},
    {id:'attribution',label:'Vessel attribution',status:'pending'},
    {id:'done',label:'Generating report',status:'pending'},
  ]);

  const setAnalysisResult=useUiStore(s=>s.setAnalysisResult);
  const setAnalysisLoading=useUiStore(s=>s.setAnalysisLoading);
  const setAnalysisError=useUiStore(s=>s.setAnalysisError);

  const validCoordinates=Number.isFinite(Number(coordinate.latitude))&&Number.isFinite(Number(coordinate.longitude))&&Math.abs(Number(coordinate.latitude))<=90&&Math.abs(Number(coordinate.longitude))<=180;
  const ready=Boolean(file)&&validCoordinates&&!loading;

  const [fetchingMetocean,setFetchingMetocean]=useState(false);

  const useDemo=()=>{
    // Explicit demo mode: bypass the API completely and load mock data
    const mockData = dashboardScenario('full');
    useUiStore.getState().setAnalysisResult(mockData);
    navigate('/dashboard');
  };

  const loadScenario=async(scenarioId:string)=>{
    try {
      const resp=await fetchScenario(scenarioId);
      const dashboardData=mapBackendToDashboard(resp);
      setAnalysisResult(dashboardData, resp);
      navigate('/dashboard');
    } catch(err) {
      setError(err instanceof Error?err.message:'Failed to load scenario.');
    }
  };

  const autoFetchMetocean=async()=>{
    const lat=Number(coordinate.latitude),lon=Number(coordinate.longitude);
    if(!Number.isFinite(lat)||!Number.isFinite(lon)){setError('Set valid coordinates before fetching weather.');return;}
    setFetchingMetocean(true);
    try {
      const m=await fetchLiveMetocean(lat,lon);
      setWindSpeed(String(m.wind_speed_ms));
      setWindDir(String(m.wind_dir_from_deg));
      setCurrentSpeed(String(m.current_speed_ms));
      setCurrentDir(String(m.current_dir_to_deg));
      setShowMetocean(true);
    } catch(err) {
      setError(err instanceof Error?err.message:'Failed to fetch live metocean data.');
    } finally {
      setFetchingMetocean(false);
    }
  };

  // Animate pipeline stages while waiting for backend
  const animateStages=(stageIndex:number)=>{
    setStages(prev=>prev.map((s,i)=>{
      if(i<stageIndex)return {...s,status:'complete'};
      if(i===stageIndex)return {...s,status:'running'};
      return {...s,status:'pending'};
    }));
  };

  const run=async()=>{
    if(!file||!validCoordinates)return;
    setLoading(true);
    setError(null);
    setAnalysisLoading(true);

    // Animate stages on a timer while waiting for backend
    // This is honest: we don't know the real backend stage, so we animate
    // progressively and mark all complete when response arrives.
    const stageTimers=[500,2000,4000,6000,8000,10000,12000];
    const timers=stageTimers.map((ms,i)=>setTimeout(()=>animateStages(i),ms));

    try {
      animateStages(0);

      const observationTime=eventDate&&eventTime?`${eventDate}T${eventTime}:00Z`:undefined;

      const response=await analyzeSpill({
        file,
        approx_lat:Number(coordinate.latitude),
        approx_lon:Number(coordinate.longitude),
        observation_time:observationTime,
        wind_speed_ms:Number(windSpeed)||7.5,
        wind_dir_from:Number(windDir)||220,
        current_speed_ms:Number(currentSpeed)||0.35,
        current_dir_to:Number(currentDir)||45,
      });

      // Clear animated timers
      timers.forEach(clearTimeout);

      // Map backend response to DashboardPayload
      const dashboardData=mapBackendToDashboard(response);

      // Mark all stages complete
      setStages(prev=>prev.map(s=>({...s,status:'complete'})));

      // Store in Zustand
      setAnalysisResult(dashboardData, response);
      setAnalysisLoading(false);

      // Navigate to dashboard after a brief moment
      setTimeout(()=>navigate('/dashboard'),800);

    } catch(err) {
      timers.forEach(clearTimeout);
      setLoading(false);
      setAnalysisLoading(false);
      const message=err instanceof ApiError?err.message:(err instanceof Error?err.message:'Analysis failed. Please check that the backend is running.');
      setError(message);
      setAnalysisError(message);
      setStages(prev=>prev.map((s,i)=>{
        const firstRunning=prev.findIndex(x=>x.status==='running');
        if(firstRunning>=0&&i===firstRunning)return {...s,status:'failed'};
        if(i<firstRunning)return {...s,status:'complete'};
        return {...s,status:'pending'};
      }));
    }
  };

  return <section className="create incident-intake">
    <span className="eyebrow">NEW INVESTIGATION</span>
    <h1>Start from a satellite scene.</h1>
    <p className="intake-intro">Select a local SAR/EO image, define the incident position, then run the OASIS pipeline. The image is sent to the backend for analysis.</p>

    <div className="intake-grid">
      <article className="panel upload intake-upload">
        <FileWarning/>
        <h3>Select or upload scene</h3>
        <p>Accepted: TIFF, GeoTIFF, PNG, JPG. The image is sent to the backend for ML inference.</p>
        <input ref={input} type="file" accept="image/*,.tif,.tiff,.geotiff" hidden onChange={(e)=>setFile(e.target.files?.[0]??null)}/>
        <div className="upload-actions">
          <button className="button" onClick={()=>input.current?.click()}>Upload scene</button>
          <button className="button quiet" onClick={useDemo}>Use demo scene</button>
        </div>
        <div className="upload-actions" style={{marginTop:'0.5rem',gap:'0.4rem',flexWrap:'wrap'}}>
          <span style={{fontSize:'0.75rem',opacity:0.6,width:'100%'}}>Indian Maritime Scenarios:</span>
          <button className="button quiet" style={{fontSize:'0.75rem'}} onClick={()=>loadScenario('mumbai_high')}>Mumbai High</button>
          <button className="button quiet" style={{fontSize:'0.75rem'}} onClick={()=>loadScenario('kutch_dark_vessel')}>Kutch Dark Vessel</button>
          <button className="button quiet" style={{fontSize:'0.75rem'}} onClick={()=>loadScenario('bengal_lookalike')}>Bengal Look-Alike</button>
        </div>
        {file&&<p className="file-state">📎 {file.name} <small>{(file.size/1024).toFixed(1)} KB</small></p>}

        <div className="coordinate-inputs">
          <label>Latitude<input value={coordinate.latitude} inputMode="decimal" placeholder="e.g. 15.21000" onChange={(e)=>setCoordinate({...coordinate,latitude:e.target.value})}/></label>
          <label>Longitude<input value={coordinate.longitude} inputMode="decimal" placeholder="e.g. 65.42000" onChange={(e)=>setCoordinate({...coordinate,longitude:e.target.value})}/></label>
          <label>Incident date<input type="date" value={eventDate} onChange={(e)=>setEventDate(e.target.value)}/></label>
          <label>Incident time (UTC)<input type="time" value={eventTime} onChange={(e)=>setEventTime(e.target.value)}/></label>
        </div>

        <div style={{display:'flex',gap:'0.5rem',marginTop:'0.75rem'}}>
          <button className="button quiet" style={{fontSize:'0.8rem'}} onClick={()=>setShowMetocean(!showMetocean)}>
            {showMetocean?'Hide':'Show'} metocean parameters ▾
          </button>
          <button className="button quiet" style={{fontSize:'0.8rem'}} disabled={fetchingMetocean} onClick={autoFetchMetocean}>
            {fetchingMetocean?'Fetching…':'⚡ Auto-Fetch Live Weather'}
          </button>
        </div>
        {showMetocean&&<div className="coordinate-inputs" style={{marginTop:'0.5rem'}}>
          <label>Wind speed (m/s)<input value={windSpeed} inputMode="decimal" onChange={(e)=>setWindSpeed(e.target.value)}/></label>
          <label>Wind direction (° from)<input value={windDir} inputMode="decimal" onChange={(e)=>setWindDir(e.target.value)}/></label>
          <label>Current speed (m/s)<input value={currentSpeed} inputMode="decimal" onChange={(e)=>setCurrentSpeed(e.target.value)}/></label>
          <label>Current direction (° to)<input value={currentDir} inputMode="decimal" onChange={(e)=>setCurrentDir(e.target.value)}/></label>
        </div>}
      </article>

      <article className="panel validation-map">
        <div>
          <h3>Scene validation &amp; area of interest</h3>
          <p>Map selection synchronizes directly with longitude and latitude fields.</p>
        </div>
        <CoordinatePicker value={coordinate} onChange={setCoordinate}/>
      </article>
    </div>

    <section className="run-panel panel">
      <div>
        <span className="eyebrow">VALIDATION STATUS</span>
        <p>{file?'Scene selected':'Select a scene'} <b>·</b> {validCoordinates?'Coordinates valid':'Set valid coordinates'}</p>
      </div>
      <button className="button" disabled={!ready} onClick={run}>
        {loading?'Running OASIS pipeline…':'Run OASIS pipeline'} <ArrowRight/>
      </button>
    </section>

    {error&&<section className="panel" style={{borderLeft:'3px solid var(--red,#f06b60)',padding:'1rem'}}>
      <strong>Analysis error</strong>
      <p>{error}</p>
      <button className="button quiet" onClick={()=>{setError(null);setLoading(false)}}>Dismiss</button>
    </section>}

    {loading&&<Pipeline stages={stages} live={true}/>}
  </section>;
}

// ─── Map Page ─────────────────────────────────────────────────────────

export function MapPage(){return <Content>{d=><section className="map-page"><div className="map-heading"><div><span className="eyebrow">SCIENTIFIC INVESTIGATION SURFACE</span><h1>Analytical map</h1></div>{d.demo?<Badge>DEMO / SYNTHETIC</Badge>:<Badge tone="green">LIVE ANALYSIS</Badge>}</div>{!d.detection.detected?<EmptyState title="No analytical layers">No oil was detected; downstream map layers are deliberately unavailable.</EmptyState>:<div className="investigation"><AnalyticalMap data={d}/><LayerControl/></div>}</section>}</Content>}

// ─── Vessels Page ─────────────────────────────────────────────────────

export function VesselPage(){return <Content>{d=>{if(d.attribution.status==='UNAVAILABLE')return <><section className="page-head"><div><span className="eyebrow">VESSEL ATTRIBUTION</span><h1>Evidence unavailable</h1></div></section><EmptyState title="Attribution unavailable">Insufficient AIS/evidence coverage. The interface intentionally does not fabricate candidate vessels.</EmptyState></>;return <><section className="page-head"><div><span className="eyebrow">{d.demo?'VESSEL ATTRIBUTION / DEMO EVIDENCE':'VESSEL ATTRIBUTION / LIVE ANALYSIS'}</span><h1>Ranked candidates</h1><p>Evidence ranking is not a causation finding.</p></div><Badge tone="amber">{d.attribution.confidence} CONFIDENCE</Badge></section><div className="vessel-grid">{d.attribution.candidates.map(c=>{const e=d.attribution.evidence.find(x=>x.candidateMmsi===c.vessel.mmsi)!;return <article className="vessel panel" key={c.vessel.mmsi}><div className="rank">#{c.rank}</div><h2>{c.vessel.name}</h2><p>MMSI <code>{c.vessel.mmsi}</code> · {c.vessel.type}</p><strong>{Math.round(c.score*100)} <small>EVIDENCE SCORE</small></strong><div className="findings">{e.findings.map(f=><p key={f.label}><Check/> {f.label}</p>)}</div><Badge>{c.confidence}</Badge></article>})}</div></>}}</Content>}

// ─── Data Quality ─────────────────────────────────────────────────────

function DataQuality({data:d}:{data:NonNullable<ReturnType<typeof useDashboard>['data']>}){return <section className="panel quality"><span className="eyebrow">DATA AVAILABILITY</span><h2>Collection status</h2>{[['Satellite',d.scene.qualityScore>.8?'GOOD':'LOW_QUALITY'],['Weather',d.environment.weather],['Ocean',d.environment.ocean],['AIS',d.incident.aisCoverage]].map(([k,v])=><div className="quality-row" key={k}><span>{k}</span><Badge tone={v==='GOOD'||v==='FULL'?'green':v==='UNAVAILABLE'||v==='NONE'?'red':'amber'}>{v}</Badge></div>)}</section>}

// ─── Confidence ───────────────────────────────────────────────────────

function Confidence({data:d}:{data:NonNullable<ReturnType<typeof useDashboard>['data']>}){const chart=d.confidence.dimensions.filter(x=>x.score!==null).map(x=>({subject:x.name,value:x.score}));return <section className="panel confidence"><span className="eyebrow">CONFIDENCE ASSESSMENT</span><h2>{d.confidence.overall} {d.confidence.score&&<small>{d.confidence.score}/100 overall</small>}</h2>{chart.length?<ResponsiveContainer width="100%" height={210}><RadarChart data={chart}><PolarGrid stroke="#29485e"/><PolarAngleAxis dataKey="subject" tick={{fill:'#a7bac6',fontSize:10}}/><RadarLine dataKey="value" stroke="#73c7d5" fill="#73c7d5" fillOpacity={.28}/></RadarChart></ResponsiveContainer>:<p>Confidence cannot be assessed because required evidence is unavailable.</p>}</section>}

// ─── Report Page ──────────────────────────────────────────────────────

export function ReportPage(){const rawResult=useUiStore(s=>s.analysisResult);const handlePdf=async()=>{if(!rawResult||rawResult.demo)return window.print();try{const backendPayload=useUiStore.getState()._rawBackendResponse;if(backendPayload){const blob=await downloadForensicPdf(backendPayload);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`OASIS_Forensic_${rawResult.incident.id}.pdf`;a.click();URL.revokeObjectURL(url);}else{window.print();}}catch{window.print();}};return <Content>{d=><section className="report"><section className="page-head"><div><span className="eyebrow">{d.demo?'INCIDENT REPORT / FRONTEND DEMO':'INCIDENT REPORT / LIVE ANALYSIS'}</span><h1>{d.incident.id} investigation brief</h1>{d.demo&&<p>This is a simulated browser report, not a backend-generated authority record.</p>}</div><button className="button quiet" onClick={handlePdf}><Download/> {d.demo?'Print / export':'Download Forensic PDF'}</button></section><div className="report-grid"><article className="panel"><h2>Incident summary</h2><p><b>Event:</b> {new Date(d.incident.eventTimestamp).toUTCString()}</p><p><b>Location:</b> {d.incident.region}</p><p><b>Satellite:</b> {d.scene.id}</p></article><article className="panel"><h2>Detection &amp; characterisation</h2><p>{d.detection.detected?`Oil detected with ${Math.round((d.detection.confidence??0)*100)}% segmentation confidence. Area: ${d.spill?.areaKm2} km².`:'No oil spill detected; downstream analysis was not run.'}</p>{d.spill&&<p><b>Orientation:</b> {d.spill.orientationDeg}° · <b>Perimeter:</b> {d.spill.perimeterKm} km</p>}</article><article className="panel"><h2>Drift analysis</h2>{d.drift.available?<><p><b>Probable origin time:</b> {d.drift.originTime?new Date(d.drift.originTime).toUTCString():'N/A'}</p><p><b>Uncertainty:</b> {d.drift.uncertainty}</p></>:<p>Drift analysis unavailable.</p>}</article><article className="panel"><h2>AIS &amp; vessel attribution</h2><p>{d.attribution.status==='UNAVAILABLE'?'Attribution unavailable due to insufficient AIS/evidence coverage.':`${d.attribution.candidates.length} candidates ranked with ${d.attribution.confidence.toLowerCase()} confidence.`}</p>{d.attribution.candidates.length>0&&<ul>{d.attribution.candidates.map(c=><li key={c.vessel.mmsi}><b>#{c.rank} {c.vessel.name}</b> (MMSI {c.vessel.mmsi}) — Score: {Math.round(c.score*100)}, CPA: {c.distanceKm.toFixed(1)} km</li>)}</ul>}</article><article className="panel"><h2>Data quality</h2><p>Weather: {d.environment.weather}; Ocean: {d.environment.ocean}; AIS: {d.incident.aisCoverage}.</p></article></div></section>}</Content>}
