# SlickTrace — Physics-Based Oil Spill Drift Model

## Purpose

The SlickTrace drift engine estimates:

1. Probable spill origin using backward/hindcast particle trajectories.
2. Future spill movement using forward particle trajectories.
3. Spatial uncertainty using an ensemble of particles.
4. Potential landfall/beaching regions using coastline constraints.

### MVP inputs

- **Sentinel-1 + U-Net:** initial spill mask, geometry and timestamp
- **ERA5 / ECMWF:** 10 m wind components
- **Copernicus Marine:** surface ocean-current components
- **Geospatial coastline:** land/ocean constraints

> The model estimates a **probable source region**, not an exact source point. Environmental forcing, windage, oil properties, SAR segmentation and unresolved ocean processes introduce uncertainty.

---

# 1. Core Lagrangian Model

For each oil particle:

$$
\frac{d\mathbf{x}}{dt}
=
\mathbf{U}_{current}
+
\alpha\mathbf{U}_{wind}
+
\mathbf{U}_{diffusion}
$$

Discrete form:

$$
\boxed{
\mathbf{x}_{t+\Delta t}
=
\mathbf{x}_t+
(\mathbf{U}_{current}+\alpha\mathbf{U}_{wind})\Delta t+
\Delta\mathbf{X}_{diff}
}
$$

Where:

- `x` = particle position
- `U_current` = ocean-current velocity
- `U_wind` = wind velocity
- `alpha` = windage coefficient
- `dt` = timestep
- `DeltaX_diff` = stochastic diffusion displacement

---

# 2. Wind — ERA5

ERA5 supplies:

- `u_w` = eastward 10 m wind component
- `v_w` = northward 10 m wind component

Wind speed:

$$
V_w=\sqrt{u_w^2+v_w^2}
$$

Wind vector:

$$
\mathbf{U}_{wind}=
\begin{bmatrix}
u_w\\
v_w
\end{bmatrix}
$$

Use **time-varying** wind fields rather than a constant wind.

---

# 3. Ocean Current — Copernicus Marine

Copernicus Marine supplies:

- `u_c` = eastward surface-current velocity
- `v_c` = northward surface-current velocity

Current speed:

$$
V_c=\sqrt{u_c^2+v_c^2}
$$

Current vector:

$$
\mathbf{U}_{current}=
\begin{bmatrix}
u_c\\
v_c
\end{bmatrix}
$$

---

# 4. Windage

Oil does not move at the full wind velocity.

$$
\mathbf{U}_{windage}=\alpha\mathbf{U}_{wind}
$$

Therefore:

$$
u_{windage}=\alpha u_w
$$

$$
v_{windage}=\alpha v_w
$$

`alpha` must be treated as a **configurable/calibrated parameter**, not a universal constant.

---

# 5. Combined Drift Velocity

$$
\boxed{
\mathbf{U}_{drift}
=
\mathbf{U}_{current}
+
\alpha\mathbf{U}_{wind}
}
$$

Component form:

$$
u_{drift}=u_c+\alpha u_w
$$

$$
v_{drift}=v_c+\alpha v_w
$$

Drift speed:

$$
V_{drift}=\sqrt{u_{drift}^2+v_{drift}^2}
$$

---

# 6. Horizontal Stochastic Diffusion

Represent unresolved spreading using a random walk.

$$
\Delta x_{diff}
=
\sqrt{2K_x\Delta t}\;N_x
$$

$$
\Delta y_{diff}
=
\sqrt{2K_y\Delta t}\;N_y
$$

where:

- `Kx`, `Ky` = horizontal diffusivity
- `Nx`, `Ny` ~ Normal(0,1)
- `dt` = timestep

For isotropic diffusion:

$$
K_x=K_y=K
$$

---

# 7. Complete Particle Update

$$
\boxed{
x_{t+\Delta t}
=
x_t+
(u_c+\alpha u_w)\Delta t+
\sqrt{2K_x\Delta t}N_x
}
$$

$$
\boxed{
y_{t+\Delta t}
=
y_t+
(v_c+\alpha v_w)\Delta t+
\sqrt{2K_y\Delta t}N_y
}
$$

This is the core MVP equation.

---

# 8. Latitude / Longitude Conversion

Do not directly add metres to latitude/longitude.

For a local spherical-Earth approximation:

$$
\Delta lat=\frac{dy}{R}
$$

$$
\Delta lon=\frac{dx}{R\cos(lat)}
$$

where:

$$
R\approx6.371\times10^6\ m
$$

Then:

$$
lat_{t+1}=lat_t+\Delta lat
$$

$$
lon_{t+1}=lon_t+\Delta lon
$$

For large geographic regions, use a proper geodesic/projection library.

### Python

```python
import math

EARTH_RADIUS_M = 6_371_000.0


def move_particle(
    lat_deg: float,
    lon_deg: float,
    dx_m: float,
    dy_m: float,
):
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)

    dlat = dy_m / EARTH_RADIUS_M

    dlon = dx_m / (
        EARTH_RADIUS_M * math.cos(lat_rad)
    )

    return (
        math.degrees(lat_rad + dlat),
        math.degrees(lon_rad + dlon),
    )
```

---

# 9. Forward Drift Forecast

At every timestep:

$$
\mathbf{U}_{drift}(t)
=
\mathbf{U}_{current}(x,y,t)
+
\alpha\mathbf{U}_{wind}(x,y,t)
$$

Then:

$$
\boxed{
\mathbf{x}_{t+\Delta t}
=
\mathbf{x}_t+
\mathbf{U}_{drift}(t)\Delta t+
\Delta\mathbf{X}_{diff}
}
$$

This produces the predicted future spill spread.

---

# 10. Backward Hindcast

For source estimation, propagate particles backwards.

Simplified deterministic form:

$$
\boxed{
\mathbf{x}_{t-\Delta t}
=
\mathbf{x}_t-
\mathbf{U}_{drift}(t)\Delta t
}
$$

For the SIH prototype, use an **ensemble hindcast approximation**. Do not describe this as an exact inverse solution.

---

# 11. Initialising Particles from U-Net

Pipeline:

```text
Sentinel-1 SAR
      |
      v
    U-Net
      |
      v
Probability Map
      |
      v
Threshold
      |
      v
Binary Oil Mask
      |
      v
Geospatial Polygon
      |
      v
Sample N particles inside polygon
```

Example:

```python
particles = sample_points_inside(
    spill_polygon,
    n_particles=1000
)
```

Each particle stores:

```python
particle.lat
particle.lon
particle.timestamp
particle.beached
```

---

# 12. Ensemble Simulation

Use many particles rather than one trajectory.

```python
N_PARTICLES = 1000
```

Each particle receives independent random diffusion:

```python
Nx ~ Normal(0, 1)
Ny ~ Normal(0, 1)
```

This creates a probability distribution for the source and future spread.

---

# 13. Source Probability

After backtracking, divide the region into spatial cells.

$$
\boxed{
P_i=\frac{N_i}{N}
}
$$

Where:

- `Ni` = particles ending in cell `i`
- `N` = total particles

Example:

```text
1000 particles

Cell A = 520  -> 52%
Cell B = 230  -> 23%
Cell C = 110  -> 11%
Other   = 140 -> 14%
```

The highest-probability region becomes the candidate source region.

---

# 14. Uncertainty

Particle mean:

$$
\mu_x=\frac{1}{N}\sum_{i=1}^{N}x_i
$$

$$
\mu_y=\frac{1}{N}\sum_{i=1}^{N}y_i
$$

Standard deviation:

$$
\sigma_x=
\sqrt{
\frac{1}{N}\sum_{i=1}^{N}(x_i-\mu_x)^2
}
$$

$$
\sigma_y=
\sqrt{
\frac{1}{N}\sum_{i=1}^{N}(y_i-\mu_y)^2
}
$$

A concentrated cloud indicates lower spatial uncertainty; a dispersed cloud indicates higher uncertainty.

---

# 15. Coastline / Land Constraint

Oil cannot propagate through land.

MVP rule:

```python
if is_on_land(particle.lat, particle.lon):
    particle.beached = True
```

Possible particle states:

```text
ACTIVE
BEACHED
OUT_OF_DOMAIN
```

---

# 16. Spatial and Temporal Interpolation

Environmental datasets are gridded and may not have values exactly at a particle's position.

Use interpolation:

```python
u_current = interpolate(
    current_u,
    particle.lon,
    particle.lat,
    time
)

v_current = interpolate(
    current_v,
    particle.lon,
    particle.lat,
    time
)

u_wind = interpolate(
    wind_u,
    particle.lon,
    particle.lat,
    time
)

v_wind = interpolate(
    wind_v,
    particle.lon,
    particle.lat,
    time
)
```

For the MVP, **bilinear spatial interpolation** is appropriate.

If the requested time falls between dataset timestamps, use temporal interpolation where appropriate.

---

# 17. Units

Environmental velocities are commonly in `m/s`.

Use:

```python
dt_seconds = dt_hours * 3600.0
```

Useful conversions:

$$
1\ hour=3600\ seconds
$$

$$
1\ km=1000\ m
$$

Never mix degrees, metres, kilometres, seconds and hours without explicit conversion.

---

# 18. Starting Parameters

These are **starting values for experimentation**, not universal physical constants.

```python
N_PARTICLES = 1000
DT_SECONDS = 3600
WINDAGE_COEFFICIENT = 0.03
DIFFUSIVITY_M2_S = 10.0
EARTH_RADIUS_M = 6_371_000.0
```

`WINDAGE_COEFFICIENT` and `DIFFUSIVITY_M2_S` must be calibrated/validated for the intended operating conditions.

---

# 19. Python — Core Drift Velocity

```python
import math


def calculate_drift_velocity(
    u_current_ms: float,
    v_current_ms: float,
    u_wind_ms: float,
    v_wind_ms: float,
    windage: float = 0.03,
):
    """Current + windage drift velocity."""

    u_drift = u_current_ms + windage * u_wind_ms
    v_drift = v_current_ms + windage * v_wind_ms

    speed = math.sqrt(
        u_drift ** 2 + v_drift ** 2
    )

    return u_drift, v_drift, speed
```

---

# 20. Python — Diffusion

```python
import math
import random


def diffusion_displacement(
    diffusivity_x_m2_s: float,
    diffusivity_y_m2_s: float,
    dt_seconds: float,
):
    """Random-walk displacement from horizontal diffusion."""

    nx = random.gauss(0.0, 1.0)
    ny = random.gauss(0.0, 1.0)

    dx = math.sqrt(
        2.0 * diffusivity_x_m2_s * dt_seconds
    ) * nx

    dy = math.sqrt(
        2.0 * diffusivity_y_m2_s * dt_seconds
    ) * ny

    return dx, dy
```

---

# 21. Python — Forward Particle Step

```python
def forward_particle_step(
    lat_deg,
    lon_deg,
    u_current_ms,
    v_current_ms,
    u_wind_ms,
    v_wind_ms,
    dt_seconds,
    windage=0.03,
    diffusivity_x=10.0,
    diffusivity_y=10.0,
):
    # Deterministic drift
    u_drift = (
        u_current_ms +
        windage * u_wind_ms
    )

    v_drift = (
        v_current_ms +
        windage * v_wind_ms
    )

    # Stochastic diffusion
    dx_diff, dy_diff = diffusion_displacement(
        diffusivity_x,
        diffusivity_y,
        dt_seconds,
    )

    dx_total = (
        u_drift * dt_seconds +
        dx_diff
    )

    dy_total = (
        v_drift * dt_seconds +
        dy_diff
    )

    return move_particle(
        lat_deg,
        lon_deg,
        dx_total,
        dy_total,
    )
```

---

# 22. Python — Backward Particle Step

```python
def backward_particle_step(
    lat_deg,
    lon_deg,
    u_current_ms,
    v_current_ms,
    u_wind_ms,
    v_wind_ms,
    dt_seconds,
    windage=0.03,
    diffusivity_x=10.0,
    diffusivity_y=10.0,
):
    # Deterministic drift
    u_drift = (
        u_current_ms +
        windage * u_wind_ms
    )

    v_drift = (
        v_current_ms +
        windage * v_wind_ms
    )

    # Stochastic diffusion
    dx_diff, dy_diff = diffusion_displacement(
        diffusivity_x,
        diffusivity_y,
        dt_seconds,
    )

    # Reverse deterministic movement
    dx_total = (
        -u_drift * dt_seconds +
        dx_diff
    )

    dy_total = (
        -v_drift * dt_seconds +
        dy_diff
    )

    return move_particle(
        lat_deg,
        lon_deg,
        dx_total,
        dy_total,
    )
```

---

# 23. Python — Forward Simulation Skeleton

```python
from datetime import timedelta


def simulate_forward(
    particles,
    environmental_provider,
    start_time,
    end_time,
    dt_seconds,
):
    current_time = start_time

    while current_time < end_time:

        for particle in particles:

            if particle.beached:
                continue

            u_c, v_c = environmental_provider.current(
                particle.lat,
                particle.lon,
                current_time,
            )

            u_w, v_w = environmental_provider.wind(
                particle.lat,
                particle.lon,
                current_time,
            )

            particle.lat, particle.lon = (
                forward_particle_step(
                    particle.lat,
                    particle.lon,
                    u_c,
                    v_c,
                    u_w,
                    v_w,
                    dt_seconds,
                )
            )

            if is_on_land(
                particle.lat,
                particle.lon,
            ):
                particle.beached = True

        current_time += timedelta(
            seconds=dt_seconds
        )

    return particles
```

---

# 24. Python — Backward Simulation Skeleton

```python
def simulate_backward(
    particles,
    environmental_provider,
    start_time,
    earliest_time,
    dt_seconds,
):
    current_time = start_time

    while current_time > earliest_time:

        for particle in particles:

            if particle.beached:
                continue

            u_c, v_c = environmental_provider.current(
                particle.lat,
                particle.lon,
                current_time,
            )

            u_w, v_w = environmental_provider.wind(
                particle.lat,
                particle.lon,
                current_time,
            )

            particle.lat, particle.lon = (
                backward_particle_step(
                    particle.lat,
                    particle.lon,
                    u_c,
                    v_c,
                    u_w,
                    v_w,
                    dt_seconds,
                )
            )

        current_time -= timedelta(
            seconds=dt_seconds
        )

    return particles
```

---

# 25. Python — Source Probability

```python
from collections import Counter


def source_probability_grid(
    particle_positions,
    cell_size_deg=0.05,
):
    """Estimate source probability from backtracked positions."""

    cells = []

    for lat, lon in particle_positions:

        lat_cell = int(
            lat / cell_size_deg
        )

        lon_cell = int(
            lon / cell_size_deg
        )

        cells.append(
            (lat_cell, lon_cell)
        )

    counts = Counter(cells)
    total = len(cells)

    if total == 0:
        return {}

    return {
        cell: count / total
        for cell, count in counts.items()
    }
```

---

# 26. Python — Most Probable Source

```python
def most_probable_source(probabilities):

    if not probabilities:
        return None

    return max(
        probabilities.items(),
        key=lambda item: item[1]
    )
```

Usage:

```python
cell, probability = most_probable_source(
    probabilities
)

print(f"Source cell: {cell}")
print(f"Probability: {probability:.2%}")
```

---

# 27. Optional Simplified Weathering

A simple conceptual surface-mass decay model is:

$$
M(t)=M_0e^{-kt}
$$

However, **do not use this to claim accurate oil-mass prediction** without oil-specific calibration.

Detailed oil fate can include:

- evaporation
- emulsification
- dissolution
- dispersion
- sedimentation
- biodegradation

For the SIH MVP, focus on **transport and source attribution**.

---

# 28. Optional Wave / Stokes Drift

If reliable wave data is later available:

$$
\mathbf V_{oil}
=
\mathbf V_{current}
+
\alpha\mathbf V_{wind}
+
\mathbf V_{Stokes}
$$

This is an advanced extension, not required for the MVP.

---

# 29. Recommended MVP Physics

Use:

$$
\boxed{
Current
+
Windage
+
Stochastic\ Diffusion
+
Coastline\ Constraints
}
$$

with:

**ERA5 → wind**

**Copernicus Marine → currents**

**Sentinel-1/U-Net → initial spill geometry + timestamp**

**Lagrangian particles → forward/backward trajectories**

**Ensemble simulation → uncertainty/source probability**

A mature upgrade path can integrate NOAA GNOME/PyGNOME for more advanced oil trajectory and fate processes.

---

# 30. Data → Formula → Output

| Input | Formula/process | Output |
|---|---|---|
| ERA5 `u_w`, `v_w` | `sqrt(u_w² + v_w²)` | Wind speed/vector |
| Copernicus `u_c`, `v_c` | `sqrt(u_c² + v_c²)` | Current speed/vector |
| Wind + alpha | `alpha * U_wind` | Windage |
| Windage + current | `U_current + alpha*U_wind` | Drift velocity |
| Diffusivity + dt | `sqrt(2*K*dt)*N` | Random spreading |
| Drift + diffusion | Particle update | New particle position |
| Reverse propagation | Negative drift integration | Probable origin |
| Particle density | `N_i / N` | Source probability |
| Forward propagation | Same transport equation | Future spill spread |

---

# 31. Complete SlickTrace Physics Pipeline

```text
                    U-NET
                      |
                      v
                Spill Polygon
                      |
             +--------+--------+
             |                 |
          Location          Timestamp
             |                 |
             +--------+--------+
                      |
                      v
            Environmental Fields
             +--------+--------+
             |                 |
           ERA5          Copernicus Marine
           Wind                Current
             |                 |
             +--------+--------+
                      |
                      v
              Current + Windage
                      |
                      v
                Lagrangian
                 Particles
                      |
               +------+------+
               |             |
            Forward       Backward
            Forecast      Hindcast
               |             |
               v             v
          Future spread   Source probability
                              |
                              v
                        AIS Correlation
                              |
                              v
                       Vessel Attribution
```

---

# 32. References

- **NOAA GNOME / PyGNOME:** https://gnome.orr.noaa.gov/doc/pygnome/structure.html
- **ECMWF ERA5:** https://www.ecmwf.int/en/forecasts/datasets/era5-hourly-data-single-levels-1940-present
- **Copernicus Marine:** https://data.marine.copernicus.eu/
- **Sentinel-1 SAR Oil Spill Dataset:** https://zenodo.org/records/8346860

---

## Engineering rule

Do **not** present the drift engine as:

> “A formula that finds the exact source.”

Present it as:

> **“An ensemble Lagrangian drift model that uses time-varying wind and ocean-current forcing to estimate probable spill origin, future movement and spatial uncertainty.”**
