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
- **Boot boost.** On the first valid reading the element runs at full power
  for up to 6 s, sized to the temperature deficit (none when already hot).
- **Warm-up** (`espyresso/warmup.py`). While the group head is still cold, the
  boiler is held above its setpoint so early shots come out close to those
  from a warm machine; it switches itself off once the group is warm (see
  below).
- **Heat budget for Pi shots.** During a shot the Pi runs, it knows how much
  water is still to come and lets the boiler store the heat that water will
  take, so the temperature drops less. Shots on the machine's own switch don't
  get this (the Pi can't know when they end).
- **Safety**, independent of the model: a raw-sensor cut-off (setpoint + 15 °C,
  never above 145 °C), detached-sensor detection, a watchdog that turns the
  heater off when control stalls, and systemd hooks that switch the outputs
  off if the program dies. See the README's safety section.

## 1. Boot from cold

The boiler is at temperature a few minutes after switching on; the group
head and portafilter (1.6 kg of brass) take much longer, and a cold group
cools the water on its way to the coffee. So the first good shot waits for
the group, not the boiler.

**The warm-up** works around that. The controller keeps an estimate of the
group's temperature (it isn't measured: a single thermal mass bolted to the
boiler wall, warmed by water flowing through it) and, while the group is
cold, holds the boiler above the setpoint: 1 °C per °C the group is below
warm, beyond a 2 °C dead-band, at most 4 °C. Hotter water makes up for the
cold group, the heater stays at full power longer at the start, and the
offset fades as the group warms. It is exactly zero once the group is warm,
about 5 minutes after a cold start, so holding temperature, shots and steam
on a warm machine are untouched. The screen's target shows it: "→103°" right
after switching on, counting down to "→99°" when the warm-up is over.

The group estimate starts as warm as the first reading, so after a short
restart (boiler and group still warm) there is no warm-up rather than a hot
shot. Settings: `WARMUP_*` in `espyresso/config.py`; `WARMUP_MAX_OFFSET = 0`
turns it off.

A Pi shot after a cold start, compared with one from a fully warm machine
(simulated, main fit; `make sim` section `warmup`):

| Shot at | 4 min | 5 min | 6 min | 7 min | Within 1 °C from |
|---|---|---|---|---|---|
| With warm-up | -3.7 °C | -1.8 °C | -1.2 °C | -0.7 °C | 7 min |
| Without | -6.2 °C | -3.4 °C | -1.9 °C | -1.0 °C | 8 min |

The other plants that fit the logs equally well gain about a minute too; on
the one that puts the sensor on the plain side the warm-up makes a 5 minute
shot up to 1.1 °C too hot. A preheat flush (short press on button one) still
helps on top: flush at 1.5 minutes, shot at 5 minutes, -1.6 °C on the main
fit.

### Ready to brew: what the screen says

The header shows one word for whether to brew, flush or wait
(`espyresso/readiness.py`). It comes from the same group estimate the
warm-up uses, plus the controller's model of the boiler water:

| Screen | Meaning | What to do |
|---|---|---|
| ●HEAT | boiler water more than 1.5 °C below the setpoint (after switching on, after a shot) | wait |
| ●FLUSH | boiler hot, group head more than 6 °C below warm | short press on button one: pulses hot water through the group until FLUSH ends |
| ●WARM | group nearly warm; the warm-up's hotter boiler makes up the rest | brew if you can't wait (within about 2 °C), or wait |
| ●READY | a shot now comes out close to one from a fully warm machine | brew |
| ●COOL | boiler more than 3 °C above its target, e.g. after steaming | wait, or flush to cool it faster |
| ●FLOW | a shot or flush is running | |
| ●STEAM, ○OFF, FAULT | steam mode, boiler off, safety cut-off | |

Button one follows the same estimate: a short press flushes while the group
is cold (FLUSH, or HEAT with a cold group) and brews once it isn't, and a
running flush stops when the group no longer needs it. HEAT and COOL clear at
half their threshold, so the word doesn't flicker when the boiler hovers at
the edge. Every change is logged as a `brew_state` event.

Simulated on every plant that fits the logs, after a cold start:

| | READY after | Shot pulled at READY vs a warm machine |
|---|---|---|
| Wait | 6.8-6.9 min | -0.8 to +0.7 °C |
| Flush when FLUSH first shows (about 1.5 min, 140 mL) | 5.2-5.7 min | -1.2 to +1.0 °C |

After a shot, READY returns in about 45 s. A second shot pulled then runs up
to about 1 °C hotter than the first on the main fit (1.7 °C on the plant
with the sensor on the plain side): the group is still hot from the first,
and the boiler from the heat it stored for it. It fades within about 2
minutes. After steaming, COOL lasts about 15 minutes unless you flush.

The boiler itself, booting from about 35 °C. The first run with the warm-up
(2026-10-25 13:55) behaved as simulated:

| | Measured, before the warm-up (09:30) | Measured, with the warm-up (13:55) | Simulated with warm-up |
|---|---|---|---|
| Display reaches setpoint | 63 s | 62 s | 58 s |
| Display peak | +2.7 °C (101.7 °C at 69 s) | +7.6 °C (106.6 °C at 74 s), +6.3 °C at 3.6 min | +6.2 °C at 3.7 min |
| Warm-up switched off | | after 279 s | after 281 s |
| Boiler water within 1 °C of setpoint | not measurable | not measurable | 130 s |
| Boiler water peak | not measurable | not measurable | +4.5 °C (the warm-up target) |
| Display at 10 minutes | 99.9 °C | 99.7 °C | 99.6 °C |

The display overshoots more than the water: the element side runs hotter
than the water while heating, more so with the warm-up's longer full-power
start. On the machine the first climb peaked 1-3 °C higher than simulated;
from 4 minutes on the two agree within 0.5 °C. The safety cut-off stays at setpoint + 15 °C; the warm-up never moves
it. A warm restart does not overshoot: from 98.6 °C the display peaked at
99.8 °C (measured; the old controller went to 104-106 °C).

## 2. Holding temperature (idle)

| | Measured (25 min, 2026-10-25) | Simulated |
|---|---|---|
| Display mean vs setpoint | +0.57 °C | +0.57 °C |
| Display standard deviation | 0.08 °C | 0.06 °C |
| Display range | +0.29 to +0.78 °C | +0.51 to +0.71 °C |
| Boiler water mean vs setpoint | not measurable (model: -0.15 °C) | +0.24 °C |
| Boiler water standard deviation | not measurable | 0.04 °C |
| Heater power | about 4 % (55 W) | 3-4 % |

At idle the temperature is **stable to about ±0.1 °C**, at the limit of the
sensor's resolution. The display sits about 0.6 °C above the setpoint and
the boiler water about 0.2 °C above it: the sensor is mostly on the
element's side, which runs a little hotter than the water.

## 3. While brewing

No shot has been pulled since temperature logging started, so this is
**simulated only**. A shot here is 7 s of preinfusion at ~1.4 mL/s then 30 s
at ~0.95 mL/s (the median of the 34 logged Pi shots), pulled 10 minutes after
a cold boot.

| | Pi shot (button) | Manual shot (machine switch) |
|---|---|---|
| Boiler water during the shot | 99.3 → 92.5 °C | 99.3 → 90.3 °C |
| Water at the puck, mean | 93.1 °C (92.9 to 93.4) | 91.8 °C (91.7 to 91.9) |
| Puck temperature range over the shot | 1.6 °C | 2.9 °C |
| Display peak (the element at full power) | 110.7 °C | 106.1 °C |
| Boiler back within ±0.5 °C after the shot | 100 s | 41 s |
| Boiler water overshoot after the shot | +0.5 °C | +0.5 °C |
| Second shot 23 s after the first | +0.8 °C at the puck | |

The boiler loses 7-9 °C during a shot because the cold water coming in is a
large heat sink for a small boiler; the puck sees less of that because the
group head buffers it. Pi shots do better because of the heat budget. The
display jumps well above the setpoint during a shot: that is the heating
element running at full power, not the water.

**How sure is this?** Two things decide the puck numbers, and they are known
to different degrees:

- **The drop over a shot** depends on how much heat the group head takes
  from the water (`eps` in the simulation). It is calibrated against a 2005
  thermocouple study of a PID Classic, which measured the puck water falling
  7.5-10 °C over a 60 mL shot; the simulation reproduces 9.2 °C. On that
  same shot this controller gives 5.5 °C on a manual shot and 3.6 °C on a
  Pi shot: the flow feed-forward and the heat budget cut a plain PID's drop
  by about 40 % and 60 %. The numbers in brackets are the range
  over the plausible `eps`.
- **The level** (93.1 °C) is less certain. The same study measured the puck
  starting about 91 °C with its PID at 99.5 °C; this simulation would give
  94.0 °C. Their sensor sat elsewhere on the boiler, so the two setpoints
  don't mean the same water, but the real puck here could be up to about
  3 °C lower than simulated. PID kits for the Classic assume 7-8 °C
  between the boiler sensor and the brew water (Gaggiuino's default is
  7 °C), which points the same way. The setpoint is 99 °C (`PUCK_OFFSET`
  6): the model puts the puck at 93 °C there, the kits' offset at 91-92 °C.
  Measure the puck once to settle it (see the simulation README).

The boiler's recovery after a shot is the least certain number: no shot has
been logged since temperature logging started, and the warm-ups the model is
fitted to don't pin it down (adding the latest warm-up moved it from 30 to
100 s). One logged shot will.

The group head also matters for the first shot of the day: it warms far more
slowly than the boiler. The screen says FLUSH while a preheat flush helps
(see "Ready to brew" above).

## 4. Steaming

Steam mode (hold button one for 5 s or more) switches the setpoint to 135 °C for up
to 2 minutes or until pressed again. **Simulated only**, and the simulation
does not model the steam actually drawn through the wand (its latent heat),
so real steaming will run cooler than this:

| | Simulated, from idle at 99 °C |
|---|---|
| Display reaches 134 °C | 33 s |
| Boiler water after 60 s / 120 s | 129.1 °C / 133.3 °C |
| Display peak | 137.7 °C |
| Back to brew temperature (±1 °C) after steaming | about 15 min |

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

1. **Pull a shot 5 minutes after a cold start, and another at 15.** The
   first warm-up run matched the simulation on the boiler side; the two
   shots show whether its compensation is right for this group.
2. **Measure the puck temperature** once and correct `PUCK_OFFSET`. This
   removes the largest uncertainty (up to about 3.5 °C).
3. **Log one Pi shot** after a 15 minute warm-up. Its boiler dip and
   recovery pin down the in-shot behaviour the model can't learn from
   warm-ups.
4. **Add a second sensor on the group head.** The warm-up could then use the
   real group temperature instead of its estimate, which is what limits it
   now.
5. **Calibrate the flow meter and puck retention** (see the simulation
   README), so Pi shots stop at the right yield and the heat budget knows
   exactly how much water is still to come.
6. **Measure the element and mains voltage**, and **refit the model** after a
   few more cold starts (`make fetch-logs`, `make fit`), so the simulation
   matches this machine more closely.
