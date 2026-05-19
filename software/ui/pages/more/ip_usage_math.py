"""IP 使用图表的数学辅助。"""

from __future__ import annotations

import math


def compute_monotone_slopes(xs, ys):
    n = len(xs)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        m[i] = (d[i - 1] + d[i]) / 2
    for i in range(n - 1):
        if abs(d[i]) < 1e-10:
            m[i] = m[i + 1] = 0.0
        else:
            a, b = m[i] / d[i], m[i + 1] / d[i]
            s = a * a + b * b
            if s > 9:
                t = 3 / math.sqrt(s)
                m[i] = t * a * d[i]
                m[i + 1] = t * b * d[i]
    return m


def eval_monotone_cubic(xs, ys, ms, x):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 2
    while lo < hi:
        mid = (lo + hi) // 2
        if xs[mid + 1] < x:
            lo = mid + 1
        else:
            hi = mid
    i = lo
    h = xs[i + 1] - xs[i]
    t = (x - xs[i]) / h
    t2, t3 = t * t, t * t * t
    return (
        (2 * t3 - 3 * t2 + 1) * ys[i]
        + (t3 - 2 * t2 + t) * h * ms[i]
        + (-2 * t3 + 3 * t2) * ys[i + 1]
        + (t3 - t2) * h * ms[i + 1]
    )
