import numpy as np

def cqc(mu: list[float], lambdas: list[float], damping: list[float], scale_factors: list[float]) -> float:
    """Signed modal amplitudes; lambdas are omega**2, damping is dimensionless."""
    mu, lam, d, sf = (np.asarray(v, dtype=float) for v in (mu, lambdas, damping, scale_factors))
    if any(v.ndim != 1 or v.shape != mu.shape or not np.isfinite(v).all() for v in (mu, lam, d, sf)):
        raise ValueError('CQC requires equal-length finite 1D vectors')
    if np.any(lam <= 0) or np.any(d < 0):
        raise ValueError('CQC requires positive eigenvalues and nonnegative damping')
    if not len(mu):
        return 0.0
    # OpenSees eigenvalues are omega**2; CQC correlation uses frequency ratios.
    omega = np.sqrt(lam)
    beta = omega[:, None] / omega[None, :]
    di = d[:, None]
    dj = d[None, :]
    numer = 8.0 * np.sqrt(di * dj) * (di + beta * dj) * beta ** 1.5
    denom = (1.0 - beta ** 2) ** 2 + 4.0 * di * dj * beta * (1.0 + beta ** 2) + 4.0 * (di ** 2 + dj ** 2) * beta ** 2
    rho = np.divide(numer, denom, out=np.zeros_like(numer), where=denom > 0)
    np.fill_diagonal(rho, 1.0)
    w = sf * mu
    total = w @ rho @ w
    return float(np.sqrt(max(0.0, total)))

def srss(mu: list[float], scale_factors: list[float]) -> float:
    values, factors = (np.asarray(v, dtype=float) for v in (mu, scale_factors))
    if values.ndim != 1 or values.shape != factors.shape or not np.isfinite(values).all() or not np.isfinite(factors).all():
        raise ValueError('SRSS requires equal-length finite 1D vectors')
    return float(np.linalg.norm(factors * values))

def combine_story_drifts(modal_drifts: list[list[float]], lambdas: list[float], damping: list[float], scale_factors: list[float], method: str) -> list[float]:
    method_upper = method.upper()
    if method_upper == 'CQC':
        return [cqc(story_modal, lambdas, damping, scale_factors) for story_modal in modal_drifts]
    if method_upper == 'SRSS':
        return [srss(story_modal, scale_factors) for story_modal in modal_drifts]
    raise ValueError(f'Unsupported method {method}. Use CQC or SRSS.')
