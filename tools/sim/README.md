# Simulation and tuning

Tools for checking control changes before they reach the machine, and for
calibrating the estimates that still need real measurements.

## What is simulated

`espyresso/sim` runs the **production control path** (`Temperature`,
`PController`, `SafetyGuard`, `Boiler`, `Watchdog`) against a thermal model of
the machine on a simulated clock. Only the hardware is faked.

The plant (`espyresso/sim/plant.py`) has the controller's six-mass structure
with coefficients fitted to this machine's logs (`espyresso/sim/plant_fit.json`).
The shipped controller constants came from Tom Brazier's modified Gaggia Baby
Class; open loop they over-predict the sensor by 9-12 C. The fitted plant
matches the logged cold starts to about 1-2 C (leave-one-out about +-2.5 C).

**Trust the boiler side, not the puck.** How much heat the brew head takes
from the water on its way to the coffee (`eps`, `k_bh`) can't be identified
from one boiler sensor. Puck temperatures are therefore reported for three
assumptions (central / weak / strong group) and only compared relative to each
other until the puck temperature is measured.

## Workflow

```sh
make fetch-logs                    # Pi log/ -> log/pi
python3 tools/review_shot.py log/pi                     # newest session summary
make fit                           # refit the plant to cold starts (FIT_ARGS=--write saves)
make sim                           # closed-loop report: restarts, faults, shots, setpoints
make test                          # includes closed-loop regression tests
```

Only `make fit` needs numpy/pandas/scipy (pulled in by `uv`); the simulator,
report and tests are pure Python (`python3 tools/sim/report.py shots`).

Each session on the Pi writes `log/shot-<ts>-tick.csv`, `-event.csv` and
`-meta.json` (git commit + every config value), so any log can be traced to
the code and settings that produced it.

## Tuning knobs (espyresso/config.py)

| Setting | What it does | How to tune |
|---|---|---|
| `BREW_PUCK_TEMP` | water temperature wanted at the coffee | taste; 93-94 for light washed coffee |
| `PUCK_OFFSET` | boiler water above puck temperature | **measure** (below); now a simulation estimate |
| `FLOW_HEAT_HORIZON_MAX` | in-shot heat budget for Pi shots | `make sim` shots section: drop vs back-to-back |
| `BREW_TARGET_YIELD_G`, `BREW_DOSE_G` | shot recipe (volume stop without a scale) | recipe |
| `BREW_RETAINED_ML_PER_G` | inlet water the puck/basket keeps | **measure** (below) |
| `BOOT_BOOST_*` | warm-up boost sized from the first reading | `make sim` restarts section |
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
`make fetch-logs && make fit` and, if the fit and leave-one-out look sane,
`make fit FIT_ARGS=--write`, then `make test && make sim`.
