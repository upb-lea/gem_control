import gym_electric_motor as gem
import numpy as np
import scipy.interpolate as sp_interpolate
import matplotlib.pyplot as plt
from .operation_point_selection import OperationPointSelection
from ..base_controllers import PIController
from ..anti_windup import AntiWindup


class SCIMOperationPointSelection(OperationPointSelection):
    def __init__(self,  max_modulation_level: float = 2 / np.sqrt(3), modulation_damping: float = 1.2,
                 psi_controller=PIController(control_task='FC')):
        super().__init__()
        self.mp = None
        self.limit = None
        self.nominal_value = None
        self.i_sd_limit = 0.0
        self.i_sq_limit = 0.0
        self.l_m = 0.0
        self.l_r = 0.0
        self.l_s = 0.0
        self.r_r = 0.0
        self.r_s = 0.0
        self.p = 0
        self.tau = 0.0

        self._modulation_damping = modulation_damping
        self.a_max = max_modulation_level

        self.t_count = 1001
        self.psi_count = 1000
        self.i_sd_count = 500
        self.i_sq_count = 1000

        self.omega_idx = None
        self.u_sd_idx = None
        self.u_sq_idx = None
        self.u_a_idx = None
        self.torque_idx = None
        self.epsilon_idx = None
        self.i_sd_idx = None
        self.i_sq_idx = None

        self.psi_controller = psi_controller

    def psi_opt(self):
        # Calculate the optimal flux for a given torque
        psi_opt_t = []
        i_sd = np.linspace(0, self.limit[self.i_sd_idx], self.i_sd_count)
        for t in np.linspace(self.t_minimum, self.t_maximum, self.t_count):
            if t != 0:
                i_sq = t / (3/2 * self.p * self.l_m ** 2 / self.l_r * i_sd[1:])
                pv = 3 / 2 * (self.r_s * np.power(i_sd[1:], 2) + (
                            self.r_s + self.r_r * self.l_m ** 2 / self.l_r ** 2) * np.power(i_sq, 2)) # Calculate losses

                i_idx = np.argmin(pv)   # Minimize losses
                i_sd_opt = i_sd[i_idx]
                i_sq_opt = i_sq[i_idx]
            else:
                i_sq_opt = 0
                i_sd_opt = 0

            psi_opt = self.l_m * i_sd_opt
            psi_opt_t.append([t, psi_opt, i_sd_opt, i_sq_opt])
        return np.array(psi_opt_t).T

    def t_max(self):
        # All flux values to calculate the corresponding torque and currents for
        psi = np.linspace(self.psi_max, 0, self.psi_count)
        # The resulting torque and currents lists
        t_val = []
        i_sd_val = []
        i_sq_val = []

        for psi_ in psi:
            i_sd = psi_ / self.l_m
            i_sq = np.sqrt(self.nominal_value[self.u_sd_idx] ** 2 / (
                        self.nominal_value[self.omega_idx] ** 2 * self.l_s ** 2) - i_sd ** 2)

            t = 3 / 2 * self.p * self.l_m / self.l_r * psi_ * i_sq
            t_val.append(t)
            i_sd_val.append(i_sd)
            i_sq_val.append(i_sq)

        # The characteristic is symmetrical for positive and negative torques.
        t_val.extend(list(-np.array(t_val[::-1])))
        psi = np.append(psi, psi[::-1])
        i_sd_val.extend(i_sd_val[::-1])
        i_sq_val.extend(list(-np.array(i_sq_val[::-1])))

        return np.array([t_val, psi, i_sd_val, i_sq_val])

    def tune(self, env: gem.core.ElectricMotorEnvironment, env_id: str, current_safety_margin: float = 0.2):
        super().tune(env, env_id, current_safety_margin)
        self.mp = env.physical_system.electrical_motor.motor_parameter
        self.limit = env.physical_system.limits
        self.nominal_value = env.physical_system.nominal_state
        self.omega_idx = env.state_names.index('omega')
        self.u_sd_idx = env.state_names.index('u_sd')
        self.u_sq_idx = env.state_names.index('u_sq')
        self.u_sa_idx = env.state_names.index('u_sa')
        self.torque_idx = env.state_names.index('torque')
        self.epsilon_idx = env.state_names.index('epsilon')
        self.i_sd_idx = env.state_names.index('i_sd')
        self.i_sq_idx = env.state_names.index('i_sq')

        self.t_minimum = -self.limit[self.torque_idx]
        self.t_maximum = self.limit[self.torque_idx]

        self.i_sd_limit = self.limit[self.i_sd_idx] * (1 - current_safety_margin)
        self.i_sq_limit = self.limit[self.i_sq_idx] * (1 - current_safety_margin)

        self.l_m = self.mp['l_m']
        self.l_r = self.l_m + self.mp['l_sigr']
        self.l_s = self.l_m + self.mp['l_sigs']
        self.r_r = self.mp['r_r']
        self.r_s = self.mp['r_s']
        self.p = self.mp['p']
        self.tau = env.physical_system.tau
        tau_s = self.l_s / self.r_s

        self.psi_controller.tune(env, env_id, 4, tau_s)

        self.psi_opt_t = self.psi_opt()
        self.psi_max = np.max(self.psi_opt_t[1])

        self.t_max_psi = self.t_max()

        alpha = self._modulation_damping / (self._modulation_damping - np.sqrt(self._modulation_damping ** 2 - 1))
        self.i_gain = 1 / (self.l_s / (1.25 * self.r_s)) * (alpha - 1) / alpha ** 2
        self.u_dc = np.sqrt(3) * self.limit[self.u_sa_idx]
        self.limited = False
        self.integrated = 0
        self.psi_high = 0.1 * self.psi_max
        self.psi_low = -self.psi_max
        self.integrated_reset = 0.5 * self.psi_low  # Reset value of the modulation controller

    # Methods to get the indices of the lists for maximum torque and optimal flux
    def get_psi_opt(self, torque):
        torque = np.clip(torque, self.t_minimum, self.t_maximum)
        return int(round((torque - self.t_minimum) / (self.t_maximum - self.t_minimum) * (self.torque_count - 1)))

    def get_t_max(self, psi):
        psi = np.clip(psi, 0, self.psi_max)
        return int(round(psi / self.psi_max * (self.psi_count - 1)))

    def _select_operating_point(self, state, reference):
        self.psi_controller([1], 0.8)
        return np.array([0.2, 0])

    def modulation_control(self, state):
        # Calculate modulation
        a = 2 * np.sqrt((state[self.u_sd_idx] * self.limit[self.u_sd_idx]) ** 2 + (
                    state[self.u_sq_idx] * self.limit[self.u_sq_idx]) ** 2) / self.u_dc

        if a > 1.01 * self.a_max:
            self.integrated = self.integrated_reset

        a_delta = self.k_ * self.a_max - a

        omega = max(np.abs(state[self.omega_idx]) * self.limit[self.omega_idx], 0.0001)

        # Calculate i gain
        k_i = 2 * np.abs(omega) * self.p / self.u_dc
        i_gain = self.i_gain * k_i

        psi_delta = i_gain * (a_delta * self.tau + self.integrated)     # Calculate Flux delta

        # Check, if limits are violated
        if self.psi_low <= psi_delta <= self.psi_high:
            self.integrated += a_delta * self.tau
        else:
            psi_delta = np.clip(psi_delta, self.psi_low, self.psi_high)

        psi_max = self.u_dc / (np.sqrt(3) * np.abs(omega) * self.p)
        psi = max(psi_max + psi_delta, 0)

        return psi
