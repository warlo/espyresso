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
  three quarters element, with a faster response (about 13 s instead of 28 s).
- **How much heat the brew head takes from the water** on its way to the puck
  (`eps`). A boiler sensor can't see this, so it is calibrated against a
  published measurement instead (below): 0.6, with 0.5 to 0.7 shown as the
  range in the report.

### Fitting it to this machine (`tools/sim/fit.py`)

The coefficients in `espyresso/sim/plant_fit.json` were fitted to the logged
cold starts by **replaying the recorded heater duty** through the plant (no
controller) and adjusting the coefficients until the plant's sensor matches
the logged sensor (least squares, with physical bounds and loose priors on
the element power and the group coupling).

The masses are not fitted. The controller's constants come from Tom
Brazier's Gaggia Baby Class, which has the same boiler and group as the
pre-2015 aluminium Classic, and he weighed them: 609 g of aluminium boiler,
100 mL of water, 1172 g brew head and 450 g portafilter. They have to be
fixed because a boiler sensor can't tell a heavier boiler with a stronger
element from a lighter one with a weaker element: scaling every heat
capacity, every coupling and the element power by the same factor gives
exactly the same temperatures. (An earlier fit with the masses free found
760 g and 120 mL; that was this ambiguity, not a heavier boiler.
`make fit FIT_ARGS=--free-masses` shows it.)

What the fit changes from Tom's constants:

| | Tom's (controller) | Fitted | Notes |
|---|---|---|---|
| Element power | 1350 W | 1106 W | Tom's element measured 42.7 Ω, 1350 W at 240 V; about 1240 W at 230 V. 1106 W matches 218 V mains or a slightly higher resistance |
| Element to wall | 14 W/K | 3.8 W/K | |
| Boiler to water (no flow) | 14.7 W/K | 24 W/K | weakly pinned, see below |
| Boiler to brew head | 3.6 W/K | 5.3 W/K | Tom insulated his boiler and used heat-sink paste at the group joint |
| Boiler to body | 1.8 W/K | 0.42 W/K | |
| Body heat capacity | 395 J/K | 190 J/K | |
| Sensor | element, 28 s | 76 % element, 13 s | |

### How good it is

| Check | Result |
|---|---|
| Controller's constants, replaying logged heater duty | sensor off by 9-12 °C above 80 °C |
| Fitted plant, the three cold starts it was fitted on (2026-05-15, 06-27, 10-25) | RMSE 1.3, 1.1 and 2.1 °C |
| Leave-one-out (fit on two, predict the third) | RMSE 1.3 to 4.2 °C; bias -4.1 to +2.8 °C above 80 °C |
| Closed loop vs the 2026-10-25 warm-up (controller reacting) | within 0.35 °C at 63, 132, 203, 300 and 420 s; up to 2.9 °C off during the first climb |
| Idle display, closed loop | +0.58 °C (real +0.57 °C) |
| Published PID Classic shot, controller blind to flow (below) | puck drop 8.7 °C (measured 7.5-10 °C) |

Open loop the errors accumulate; closed loop the controller corrects for
them, just as on the machine, which is why the closed-loop match is better.
`espyresso/tests/test_plant_fit.py` pins these numbers on two public fixtures
(`espyresso/tests/fixtures/`, made with `tools/sim/make_fixture.py`), so a
refit that makes the plant worse fails the tests.

**Calibrating `eps` against published data.** A 2005 thermocouple study of a
PID-controlled Classic (setpoint 99.5 °C, 60 mL in 30 s after a 20 minute
warm-up) measured the water above the puck falling 7.5-10 °C over the shot.
A plain PID can't see the flow, so `closedloop.simulate(...,
controller_sees_flow=False)` reproduces it: `eps` 0.52 to 0.68 gives that
drop (0.6 gives 8.7 °C). Tom's assumption (1.0, the water arrives at the
brew head's temperature) gives 2.7 °C and is ruled out. Even a controller
that didn't react to the shot at all would need `eps` 0.6 to 0.75, so the
range holds however hard their PID worked.
`test_plant_reproduces_published_puck_drop_of_a_pid_classic` pins this.

On the same 60 mL shot this controller gives a 4.6 °C drop on a manual
shot (the flow meter's feed-forward) and 2.7 °C on a Pi shot (the heat
budget).

### What it can't tell you

- **The absolute puck temperature.** The drop over a shot is calibrated; the
  level is not. The study measured the puck starting at about 91 °C with the
  PID at 99.5 °C; the simulator, at 99.5 °C, starts at 94.5 °C. Their sensor
  saw much less of the shot (a 0.5-1 °C dip, where ours dips about 4 °C in
  the model), so it sat elsewhere on the boiler and its "99.5" meant
  different water. Plant changes that bring the simulated puck down to 91 °C
  break the fit to this machine's own warm-ups. So the real puck may be up
  to about 3.5 °C below what the report says; only a measurement settles it.
- **The boiler during and right after a shot.** No shot has been logged
  since the temperature logging started, so how fast the boiler water
  exchanges heat with its walls is pinned only by warm-ups: two fits that
  matched them equally well differed by almost 2x (13 and 24 W/K). Recovery
  times after a shot are the least certain numbers. One logged Pi shot fixes
  this.
- **Steam drawn through the wand** (its latent heat) is not modelled; steam
  mode results are for heating and holding only.
- **Non-uniform starts**: every simulated start has the machine at one
  temperature (or a given state). After a short pause the real group and
  body are cooler than the boiler.
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
preheat; `eps` 0.6, 0.7 and 0.5) and `setpoints` (setpoint to puck
temperature).

Only `make fit` needs numpy/pandas/scipy (pulled in by `uv`); the simulator,
report and tests are pure Python.

### Writing your own scenario

```python
from espyresso.sim import closedloop, plant, scenarios

run = closedloop.simulate(
    duration=900,                              # seconds
    start=plant.uniform(22.6),                 # or plant.at_setpoint(99), or a dict of temperatures
    params=plant.fitted(eps=0.5),              # plant assumptions
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

**One logged shot.** Pull a Pi shot with the temperature logging running
(any shot after a 15 minute warm-up). Its boiler dip and recovery pin the
in-shot behaviour the warm-ups can't.

**Element power.** Measure the element's resistance (machine unplugged, at
the element terminals) and the mains voltage: power = V² / R. The fit's
1106 W corresponds to 218 V on a 42.7 Ω element.

**Plant.** After a few new cold starts (machine off for an hour, then on),
`make fetch-logs && make fit`. If the fit and leave-one-out look sane and no
parameter is at its bound, `make fit FIT_ARGS=--write`, then
`make test && make sim`. The masses stay fixed at Tom's weighed values.
