# Temperature control: how it works and how precise it is

This page describes how espyresso controls the Gaggia Classic's boiler and how
precise the temperature is in each operating state: booting from cold,
holding temperature, brewing and steaming.

Every number here comes from one of two places, and each one is labelled:

- **Measured**: real logs from the machine (`log/` on the Pi).
- **Simulated**: `make sim` (`tools/sim/report.py precision`), which runs the
  production control code against a model of this machine. How the simulation
  works and how far to trust it is in [tools/sim/README.md](../tools/sim/README.md).

Re-run `make sim` after changing any setting; the numbers below were produced
at setpoint 99 °C (`BREW_PUCK_TEMP` 93 + `PUCK_OFFSET` 6) on 2026-10-25.

## Three temperatures

The machine has one temperature sensor (a TSIC 306 on the boiler, 0.1 °C
resolution). That gives three different temperatures worth keeping apart:

| | What it is | Known how |
|---|---|---|
| **Display** | the sensor reading, shown on the screen | measured |
| **Boiler water** | the water in the boiler | estimated by the controller's model; simulated |
| **Puck** | the water reaching the coffee, after passing through the group | simulated only; the drop over a shot is calibrated against published measurements, the level is not |

The display reads about 0.5 °C above the boiler water at rest (the sensor
sits mostly on the heating element's side of the boiler), and the puck is
several degrees below the boiler water (the group head takes heat from it). The
setpoint is the boiler water target; `PUCK_OFFSET` is the estimated drop to
the puck, until it is measured with a thermocouple.

## How the controller works

`espyresso/pcontroller.py` is a model-predictive controller based on
[Tom Brazier's design](http://tomblog.firstsolo.net/index.php/solved-temperature-control/).
It models six thermal masses (heating element, boiler wall, water, machine
body, brew head with portafilter, and the sensor itself) and, ten times a
second:

1. Steps the model forward with the heater power it applied and any water
   flowing through (from the flow meter).
2. Nudges the model towards the sensor reading (an observer), so modelling
   errors don't accumulate.
3. Works out how much heat would bring the modelled water to the setpoint in
   about 15 seconds, adds the known losses (to the group, body and incoming
   water), and limits it so the boiler can't store more heat than it would
   lose quickly (to avoid overshoot).

On top of that model:

- **Self-healing.** After a pause in readings (start-up, a stall) or a large,
  persistent disagreement with the sensor, the model restarts from the
  measurement instead of integrating a long step. The model corrects all its
  masses near any setpoint (brew or steam). It works from any starting state:
  cold, warm, or hot after a crash.
- **Warm-up boost.** On the first valid reading the element runs at full power
  for up to 6 s, sized to the temperature deficit (none when already hot).
- **Heat budget for Pi shots.** During a shot the Pi runs, it knows how much
  water is still to come and lets the boiler store the heat that water will
  take, so the temperature drops less. Shots on the machine's own switch don't
  get this (the Pi can't know when they end).
- **Safety**, independent of the model: a raw-sensor cut-off (setpoint + 15 °C,
  never above 145 °C), detached-sensor detection, a watchdog that turns the
  heater off when control stalls, and systemd hooks that switch the outputs
  off if the program dies. See the README's safety section.

## 1. Boot from cold

| | Measured (2026-10-25, from 35.5 °C) | Simulated, from 35.5 °C | Simulated, from 22.6 °C |
|---|---|---|---|
| Display reaches setpoint | 63 s | 59 s | 75 s |
| Display peak | +2.7 °C (101.7 °C) | +2.2 °C | +2.3 °C |
| Boiler water within 1 °C | not measurable | 192 s | 216 s |
| Boiler water peak | not measurable | +0.7 °C | +0.8 °C |
| Boiler water settled within ±0.5 °C | not measurable | 6.2 min | 6.7 min |
| Display back near its idle level | 99.9 °C at 7 min | | |

The display overshoots more than the water: the element and wall run hotter
than the water while heating. The display is at setpoint after about a
minute, but **the boiler water needs about 3 to 3.5 minutes, and the group
head much longer** (see brewing). A warm restart does not overshoot: from
98.6 °C the display peaked at 99.8 °C (measured; the old controller went to
104-106 °C).

## 2. Holding temperature (idle)

| | Measured (25 min, 2026-10-25) | Simulated |
|---|---|---|
| Display mean vs setpoint | +0.57 °C | +0.58 °C |
| Display standard deviation | 0.08 °C | 0.06 °C |
| Display range | +0.29 to +0.78 °C | +0.51 to +0.71 °C |
| Boiler water mean vs setpoint | not measurable (model: -0.15 °C) | +0.09 °C |
| Boiler water standard deviation | not measurable | 0.03 °C |
| Heater power | about 4 % (55 W) | 3-4 % |

At idle the temperature is **stable to about ±0.1 °C**, at the limit of the
sensor's resolution. The display sits about 0.5 °C above the setpoint while
the boiler water is on it: the sensor is mostly on the element's side, which
runs a little hotter than the water.

## 3. While brewing

No shot has been pulled since temperature logging started, so this is
**simulated only**. A shot here is 7 s of preinfusion at ~1.4 mL/s then 30 s
at ~0.95 mL/s (the median of the 34 logged Pi shots), pulled 10 minutes after
a cold boot.

| | Pi shot (button) | Manual shot (machine switch) |
|---|---|---|
| Boiler water during the shot | 99.2 → 93.7 °C | 99.2 → 91.6 °C |
| Water at the puck, mean | 94.1 °C (93.9 to 94.3) | 92.6 °C (92.6 to 92.7) |
| Puck temperature range over the shot | 1.3 °C | 2.3 °C |
| Display peak (the element at full power) | 110.7 °C | 105.9 °C |
| Boiler back within ±0.5 °C after the shot | 29 s | 36 s |
| Boiler water overshoot after the shot | +0.4 °C | +0.3 °C |
| Second shot 23 s after the first | +0.8 °C at the puck | |

The boiler loses 5-8 °C during a shot because the cold water coming in is a
large heat sink for a small boiler; the puck sees less of that because the
group head buffers it. Pi shots do better because of the heat budget. The
display jumps well above the setpoint during a shot: that is the heating
element running at full power, not the water.

**How sure is this?** Two things decide the puck numbers, and they are known
to different degrees:

- **The drop over a shot** depends on how much heat the group head takes
  from the water (`eps` in the simulation). It is calibrated against a 2005
  thermocouple study of a PID Classic, which measured the puck water falling
  7.5-10 °C over a 60 mL shot; the simulation reproduces 8.7 °C. On that
  same shot this controller gives 4.6 °C on a manual shot and 2.7 °C on a
  Pi shot: the flow feed-forward and the heat budget cut a plain PID's drop
  roughly in half and by two thirds. The numbers in brackets are the range
  over the plausible `eps`.
- **The level** (94.1 °C) is less certain. The same study measured the puck
  starting about 91 °C with its PID at 99.5 °C; this simulation would give
  94.5 °C. Their sensor sat elsewhere on the boiler, so the two setpoints
  don't mean the same water, but the real puck here could be up to about
  3.5 °C lower than simulated. PID kits for the Classic assume 7-8 °C
  between the boiler sensor and the brew water (Gaggiuino's default is
  7 °C), which points the same way. That is why the setpoint is 99 °C
  (`PUCK_OFFSET` 6), between the model (94 °C at the puck) and the kits
  (91-92 °C), until the puck is measured once (see the simulation README).

The boiler's recovery after a shot (29-36 s) is the least certain number:
no shot has been logged since temperature logging started, and the warm-ups
the model is fitted to don't pin it down well. One logged shot will.

The group head also matters for the first shot of the day: it warms far more
slowly than the boiler. The Pi's preheat routine (short press on button one
while the head is cold) runs hot water through it.

## 4. Steaming

Steam mode (hold button one for 5 s or more) switches the setpoint to 135 °C for up
to 2 minutes or until pressed again. **Simulated only**, and the simulation
does not model the steam actually drawn through the wand (its latent heat),
so real steaming will run cooler than this:

| | Simulated, from idle at 99 °C |
|---|---|
| Display reaches 134 °C | 32 s |
| Boiler water after 60 s / 120 s | 129.2 °C / 132.8 °C |
| Display peak | 137.8 °C |
| Back to brew temperature (±1 °C) after steaming | about 14 min |

The boiler water lags the display by several degrees while heating for steam,
so give it a minute before steaming. Getting back down to brew temperature
takes a long time because the boiler can only cool by losing heat; running
water through the group cools it much faster. Brew first, then steam.

If you steam with the machine's own steam switch, that path may bypass the
Pi entirely (on 2026-01-17 the boiler heated while the Pi had the heater
off), so espyresso does not regulate it. Check the wiring before relying on
either.

The optional refill during steam mode (`STEAM_REFILL_PWM`) is off by default:
in the simulation, refilling at about 1 mL/s kept the water near 110 °C while
the element side ran into the 145 °C safety cut-off.

## Improving precision further

In order of expected benefit:

1. **Measure the puck temperature** once and correct `PUCK_OFFSET`. This
   removes the largest uncertainty (up to about 3.5 °C).
2. **Log one Pi shot** after a 15 minute warm-up. Its boiler dip and
   recovery pin down the in-shot behaviour the model can't learn from
   warm-ups.
3. **Add a second sensor on the group head.** The controller could then track
   the real group temperature instead of estimating it, which matters most
   for the first shots after a cold start.
4. **Calibrate the flow meter and puck retention** (see the simulation
   README), so Pi shots stop at the right yield and the heat budget knows
   exactly how much water is still to come.
5. **Measure the element and mains voltage**, and **refit the model** after a
   few more cold starts (`make fetch-logs`, `make fit`), so the simulation
   matches this machine more closely.
