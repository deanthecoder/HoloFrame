"""1-Euro filter implementation used for smoothing tracked signals."""

import math


class OneEuro:
    def __init__(self, min_cutoff=1.0, beta=0.02, dcutoff=1.0):
        self.min_cutoff, self.beta, self.dcutoff = min_cutoff, beta, dcutoff
        self.t_prev = None
        self.x_prev = None
        self.dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self, x, t):
        """Reset the filter so the next `filter` call emits `x` immediately."""
        self.t_prev = t
        self.x_prev = x
        self.dx_prev = 0.0

    def filter(self, x, t):
        if self.t_prev is None:
            self.t_prev, self.x_prev = t, x
            return x
        dt = max(1e-6, t - self.t_prev)
        self.t_prev = t
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.dcutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        self.dx_prev = dx_hat
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev = x_hat
        return x_hat


__all__ = ["OneEuro"]
