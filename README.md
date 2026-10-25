# Espyresso

Espyresso is a hobby Python project designed for the Gaggia Classic espresso machine, providing advanced control and automation features. The project incorporates various elements such as a boiler controller with PWM (Pulse Width Modulation), a pump controller with PWM, flow meter integration, automatic timed shots with weight and flow measurements, a display with graphical representation using Pygame, a digital temperature sensor (TSIC 306), water level sensor, and Bluetooth scale support for the Eureka Precisa.

<img src="https://github.com/warlo/espyresso/assets/5417271/66c09f42-f7c9-46aa-ba3e-e11ee3089577" width="30%" />

*Espyresso Simulator*


**Note:** Espyresso is a project tailored for enthusiasts with a penchant for tinkering. Due to the custom requirements of the hardware, this wont work seamlessly out of the box. The software is designed to run on a Raspberry Pi Zero with custom soldered hardware. However feel free to use it as inspiration!

**Pygame version:** Pygame is pinned to `1.9.6` on purpose. It is the only version that works on the Raspberry Pi Zero, so do not upgrade it. Dependencies in general are left as-is, since this is a small local device and not something that needs to track upstream.

## Features

- **Boiler Controller with PWM:** Efficiently manages the boiler temperature using Pulse Width Modulation for precise control.

- **Pump Controller with PWM:** Regulates the pump with PWM for optimal water flow during espresso extraction.

- **Flow Meter Integration:** Utilizes a flow meter to monitor and control the flow rate during espresso extraction.

- **Automatic Timed Shots:** Enables automatic shot control based on time, weight, and flow measurements, providing consistency in espresso preparation.

- **Graphical Display with Pygame:** Presents real-time data and graphs through a Pygame-based graphical interface for enhanced user experience.

- **Digital Temperature Sensor (TSIC 306):** Incorporates a digital temperature sensor for accurate temperature monitoring and control.

- **Water Level Sensor:** Monitors the water level in the espresso machine, ensuring timely refilling if required.

- **Bluetooth Scale Support (Eureka Precisa):** Supports Bluetooth-enabled scales, specifically the Eureka Precisa, for precise measurement of coffee grounds.

- **PID and MPC Temperature Control:** Initially implemented PID temperature adjustment, later updated to an MPC (Model Predictive Controller) inspired by Tom Brazier's work [here](http://tomblog.firstsolo.net/index.php/solved-temperature-control/).

## Safety and self-healing

The element is never left to the controller alone:

- `espyresso/safety.py`: a raw-sensor guard between controller and PWM
  (over-temperature cut, detached-sensor detection) and a watchdog thread that
  forces the heater off when control stalls, bounds pump run time, runs the
  auto-off timer and feeds systemd's watchdog.
- `espyresso/failsafe.py`: switches the outputs off from systemd before every
  start and after every stop, including crashes (pigpiod keeps a hardware PWM
  running after its client dies).
- The controller re-syncs its model after gaps or large errors, sizes the
  warm-up boost from the first reading, and recovers from any starting state.
- `sudo services/install.sh` (on the Pi) installs the unit, the Pi's hardware
  watchdog and a persistent journal.

## Simulation and tuning

`espyresso/sim` runs the production control path against a plant fitted to
this machine's logs; `make sim` prints restarts, faults, shots and the
setpoint-to-puck mapping, and the closed-loop tests pin the behaviour. See
[tools/sim/README.md](tools/sim/README.md) for the workflow and for
calibrating the puck offset and shot yield with real measurements.

## Inspiration

Espyresso draws inspiration from the work of jam3sward ([int03.co.uk](http://int03.co.uk/blog/project-coffee-espiresso-machine/)) and Tom Brazier ([tomblog.firstsolo.net](http://tomblog.firstsolo.net/index.php/hobbies/pimping-my-coffee-machine/coffee-machine-features/)).

## License

Espyresso is licensed under the [MIT License](LICENSE). See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- jam3sward for inspiration.
- Tom Brazier for inspiration and the MPC temperature control approach.
- Holger Fleischmann for TSIC 306 python code
