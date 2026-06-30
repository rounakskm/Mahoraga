import numpy as np
import pandas as pd

from services.trader.training import eval as kernel_eval
from services.trader.training.parse_metric import report_from_eval, report_hash
from services.trader.training.strategy_template import RegimeConditionalStrategy, label_regimes


def _price(n=600):
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100*np.exp(np.cumsum(np.random.default_rng(0).normal(4e-4,1e-2,n))), index=idx)

def test_report_captures_fitness_and_is_hash_stable():
    p = _price()
    s = RegimeConditionalStrategy.seed()
    ev = kernel_eval.evaluate(s, p, label_regimes(p))
    r = report_from_eval(ev, s.windows)
    assert r.sharpe == ev.sharpe and r.fitness == ev.fitness.score
    assert r.promoted == ev.report.promoted
    assert report_hash(r) == report_hash(report_from_eval(ev, s.windows))  # deterministic
