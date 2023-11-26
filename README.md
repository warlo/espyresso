# Espyresso

Espyresso is a hobby Python project designed for the Gaggia Classic espresso machine, providing advanced control and automation features. The project incorporates various elements such as a boiler controller with PWM (Pulse Width Modulation), a pump controller with PWM, flow meter integration, automatic timed shots with weight and flow measurements, a display with graphical representation using Pygame, a digital temperature sensor (TSIC 306), water level sensor, and Bluetooth scale support for the Eureka Precisa.

<img src="https://github.com/warlo/espyresso/assets/5417271/66c09f42-f7c9-46aa-ba3e-e11ee3089577" width="30%" />

*Espyresso Simulator*


**Note:** Espyresso is a project tailored for enthusiasts with a penchant for tinkering. Due to the custom requirements of the hardware, this wont work seamlessly out of the box. The software is designed to run on a Raspberry Pi Zero with custom soldered hardware. However feel free to use it as inspiration!

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

## Inspiration

Espyresso draws inspiration from the work of jam3sward ([int03.co.uk](http://int03.co.uk/blog/project-coffee-espiresso-machine/)) and Tom Brazier ([tomblog.firstsolo.net](http://tomblog.firstsolo.net/index.php/hobbies/pimping-my-coffee-machine/coffee-machine-features/)).

## License

Espyresso is licensed under the [MIT License](LICENSE). See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- jam3sward for inspiration.
- Tom Brazier for inspiration and the MPC temperature control approach.
- Holger Fleischmann for TSIC 306 python code
