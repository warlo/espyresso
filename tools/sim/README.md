# Simulation and tuning

Tools for trying control changes before they reach the machine, analysing
logs, and calibrating the estimates that still need real measurements. For
what the results mean in practice (how precise the temperature is when
booting, idling, brewing and steaming) see
[docs/temperature-control.md](../../docs/temperature-control.md).

## How the simulation works

```
                 ┌──────────────── production code (unchanged) ────────────────┐
 plant model ──► │ TSIC reading ─► Temperature ─► PController ─► SafetyGuard   │
 (this machine)  │                     │                              │        │
       ▲         │                 Watchdog                         Boiler ─────┼──► heater duty
       │         └─────────────────────────────────────────────────────────────┘        │
       └──────────────────────────── heater power, water flow ◄──────────────────────────┘
```

`espyresso/sim/closedloop.py` runs the **real control path**: `Temperature`
(the control tick, warm-up boost, safety guard), `PController`, `Boiler` and
the `Watchdog`. Only the hardware is replaced:

| Real | Simulated |
|---|---|
| TSIC 306 sensor on GPIO | the plant's sensor temperature, rounded to the TSIC's 0.098 °C steps |
| pigpio hardware PWM | records the duty the `Boiler` writes; the plant heats with duty × element power |
| flow meter | the scenario's flow (preinfusion, shot, preheat, steam refill) |
| wall clock | a simulated clock, ticking every 93 ms (the logged median) |

Because the control code is the production code, a change to the controller
or the safety layers is simulated exactly as it will run on the Pi.

### The plant (`espyresso/sim/plant.py`)

The plant is the machine as the simulation sees it. It uses the same six
thermal masses as the controller's own model (Tom Brazier's design): heating
element half of the boiler, the other half (boiler wall), water, machine
body, brew head with portafilter, and the sensor. Heat flows between them in
proportion to their temperature differences; water flowing through takes
heat out of the boiler and gives some of it to the brew head. Two things are
added that the controller doesn't model:

- **Where the sensor sits** (`a_s`): it follows a mix of element and wall
  temperature. The controller assumes the element only; the fit puts it about
  halfway, with a faster response (about 8 s instead of 28 s).
- **How much heat the brew head takes from the water** on its way to the puck
  (`eps`). A boiler sensor can't see this, so it is not fitted; the puck
  temperature is reported for three assumptions (central, weak and strong
  group coupling).

### Fitting it to this machine (`tools/sim/fit.py`)

The coefficients in `espyresso/sim/plant_fit.json` were fitted to logged
cold starts by **replaying the recorded heater duty** through the plant (no
controller) and adjusting the coefficients until the plant's sensor matches
the logged sensor (least squares, with physical bounds and loose priors on
the masses and element power, which were never measured on this machine).

The controller's own constants came from Tom Brazier's modified Gaggia Baby
Class, not this Classic. The fit suggests a heavier boiler (about 760 g of
aluminium and 120 mL of water) and a 1290 W element.

### How good it is

| Check | Result |
|---|---|
| Controller's constants, replaying logged heater duty | sensor off by 9-12 °C above 80 °C |
| Fitted plant, the two cold starts it was fitted on | RMSE 0.9 and 2.1 °C |
| Leave-one-out (fit on one, predict the other) | about ±2.5 °C bias |
| Holdout: 2026-10-25 cold start at 99 °C, replayed | RMSE 3.6 °C (runs 3.5 °C hot above 80 °C) |
| Holdout, closed loop (controller reacting) | matched the real warm-up within about 0.5 °C at 63, 132 and 203 s |
| Idle display, closed loop | +0.60 °C (real +0.57 °C) |

Open loop the errors accumulate; closed loop the controller corrects for
them, just as on the machine, which is why the closed-loop match is better.
`espyresso/tests/test_plant_fit.py` pins these numbers on two public fixtures
(`espyresso/tests/fixtures/`, made with `tools/sim/make_fixture.py`), so a
refit that makes the plant worse fails the tests.

### What it can't tell you

- **The puck temperature** depends on the group head coupling, which is
  unmeasured; treat puck numbers as estimates with the given range.
- **Steam drawn through the wand** (its latent heat) is not modelled; steam
  mode results are for heating and holding only.
- **Non-uniform starts**: every simulated start has the machine at one
  temperature (or a given state); a refit with this morning's start pushed
  parameters to their bounds, likely because the group and body weren't at
  the boiler's temperature.
- **Water layering** in the boiler, mains voltage changes and the flow
  meter's calibration are not modelled.

## Workflow

```sh
make fetch-logs PI=zero            # Pi log/ -> log/pi (PI = your ssh host)
python3 tools/review_shot.py log/pi                     # newest session summary
make sim                           # closed-loop report (sections below)
python3 tools/sim/report.py precision                   # one section
make fit                           # refit the plant to cold starts (FIT_ARGS=--write saves)
make test                          # includes closed-loop and plant regression tests
```

Report sections: `precision` (by state: boot, idle, brewing, steaming),
`restarts` (from cold, warm, at setpoint, hot, after a crash), `faults`
(control stall, failed first reading, detached sensor), `shots` (Pi, manual,
preheat; three group assumptions) and `setpoints` (setpoint to puck
temperature).

Only `make fit` needs numpy/pandas/scipy (pulled in by `uv`); the simulator,
report and tests are pure Python.

### Writing your own scenario

```python
from espyresso.sim import closedloop, plant, scenarios

run = closedloop.simulate(
    duration=900,                              # seconds
    start=plant.uniform(22.6),                 # or plant.at_setpoint(99), or a dict of temperatures
    params=plant.fitted(eps=0.25),             # plant assumptions
    flow=scenarios.preheat_then_shot(90, 420), # or pi_shots([...]), manual_shots([...]), steam(...)
    log_dir="log/sim",                         # optional: write a Pi-format session
)
run.max("water", after=420)                    # rows have t, sensor, duty, flow, water, puck, ...
```

With `log_dir`, the run is logged through the production `ShotLogger` on
simulated time: the same tick/event CSVs as the Pi plus a `sim` section in
`-meta.json`, so `tools/review_shot.py` and any other analysis work the same
on real and simulated sessions.

## Logs

Each session on the Pi writes, in `log/`:

| File | Contents |
|---|---|
| `shot-<ts>-tick.csv` | one row per control tick (~10 Hz): sensor, heater duty applied and commanded, safety limit, flow, setpoint, every modelled temperature and power term, model re-syncs, boost, heat budget |
| `shot-<ts>-event.csv` | buttons, boiler on/off, auto-off, brew phases (with stop reason, volume), steam, safety events |
| `shot-<ts>-meta.json` | the git commit and every config value, so a log can be tied to the code and settings that produced it |

Logs are not in git (`log/` is ignored). Tick rows are flushed at least every
2 s, so a crash or power cut loses little.

## Tuning knobs (espyresso/config.py)

| Setting | What it does | How to tune |
|---|---|---|
| `BREW_PUCK_TEMP` | water temperature wanted at the coffee | taste; 93-94 for light washed coffee |
| `PUCK_OFFSET` | boiler water above puck temperature | **measure** (below); now a simulation estimate |
| `FLOW_HEAT_HORIZON_MAX` | in-shot heat budget for Pi shots | `make sim` shots: drop vs back-to-back |
| `BREW_TARGET_YIELD_G`, `BREW_DOSE_G` | shot recipe (volume stop without a scale) | recipe |
| `BREW_RETAINED_ML_PER_G` | inlet water the puck/basket keeps | **measure** (below) |
| `BOOT_BOOST_*` | warm-up boost sized from the first reading | `make sim` restarts |
| `STEAM_SECONDS`, `STEAM_REFILL_PWM` | steam mode length, optional refill | `make sim` precision |
| `MPC_*` | model self-healing thresholds | data-backed defaults; see comments |
| `SAFETY_*`, `CONTROL_STALE_SECONDS` | safety limits | leave unless a log shows a false trip |

After changing any of these, run `make test` and `make sim`.

## Calibrating with measurements

**Puck temperature (`PUCK_OFFSET`).** Put a thermocouple tip just above the
puck (a cheap K-type through a spare basket, or a Scace-style device), pull a
shot at the current setpoint and note the average reading over the shot.
`PUCK_OFFSET += BREW_PUCK_TEMP - measured`. A second TSIC on the group head
would let the controller learn this on its own.

**Shot yield (`BREW_RETAINED_ML_PER_G`).** First check the flow meter: run a
flush without a puck into a cup on a scale and compare grams with the `total_ml`
in the `brew` end event. Then weigh three Pi shots: for each,
`retained = (total_ml - grams_in_cup) / BREW_DOSE_G`; use the average.

**Plant.** After a few new cold starts (machine off for an hour, then on),
`make fetch-logs && make fit`. If the fit and leave-one-out look sane and no
parameter is at its bound, `make fit FIT_ARGS=--write`, then
`make test && make sim`.
