#!/usr/bin/env python3

class PID():
    def __init__(self):
        self.i_state = 0.0
        self.d_state = 0.0

        self.i_min = -1.0
        self.i_max = 1.0

        self.p_gain = 1.0
        self.i_gain = 0.0
        self.d_gain = 0.0

    def set_pid_gains(self, p_gain, i_gain, d_gain):
        self.p_gain = p_gain
        self.i_gain = i_gain
        self.d_gain = d_gain

    def set_integrator_limits(self, i_min, i_max):
        self.i_min = i_min
        self.i_max = i_max

    def update(self, error, position):

        # Calculate proportional term
        p_term = self.p_gain * error

        self.i_state += error
        if self.i_state > self.i_max:
            self.i_state = self.i_max
        elif self.i_state < self.i_min:
            self.i_state = self.i_min

        # Calculate integral term
        i_term = self.i_gain * self.i_state

        # Calculate derivative term
        d_term = self.d_gain * (self.d_state - position)
        self.d_state = position

        return p_term + d_term + i_term

