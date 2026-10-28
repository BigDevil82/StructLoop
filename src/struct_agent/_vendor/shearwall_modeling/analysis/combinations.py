import numpy as np

def cqc(mu: list[float], lambdas: list[float], damping: list[float], scale_factors: list[float]) -> float:
    mu = np.asarray(mu)
    lam = np.asarray(lambdas)
    d = np.asarray(damping)
    sf = np.asarray(scale_factors)
    beta = lam[:, None] / lam[None, :]
    di = d[:, None]
    dj = d[None, :]
    numer = 8.0 * np.sqrt(di * dj) * (di + beta * dj) * beta ** 1.5
    denom = (1.0 - beta ** 2) ** 2 + 4.0 * di * dj * beta * (1.0 + beta ** 2) + 4.0 * (di ** 2 + dj ** 2) * beta ** 2
    rho = numer / denom
    w = sf * mu
    total = w @ rho @ w
    return float(np.sqrt(max(0.0, total)))

def srss(mu: list[float], scale_factors: list[float]) -> float:
    return float(np.sqrt(np.sum((np.asarray(scale_factors) * np.asarray(mu)) ** 2.0)))

def combine_story_drifts(modal_drifts: list[list[float]], lambdas: list[float], damping: list[float], scale_factors: list[float], method: str) -> list[float]:
    method_upper = method.upper()
    if method_upper == 'CQC':
        return [cqc(story_modal, lambdas, damping, scale_factors) for story_modal in modal_drifts]
    if method_upper == 'SRSS':
        return [srss(story_modal, scale_factors) for story_modal in modal_drifts]
    raise ValueError(f'Unsupported method {method}. Use CQC or SRSS.')
