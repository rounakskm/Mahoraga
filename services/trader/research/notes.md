# Research Notes — Autoresearch Ledger

> Canonical markdown ledger of the autoresearch loop. Each line is one recorded
> experiment (run / iteration / candidate hash / fitness / verdict). Appended by
> `Notebook.record(...)`; fully regenerable from `experiments.iterations` via
> `Notebook.regenerate_from_postgres(dsn)` — Postgres is the source of truth, this
> file is the human-readable mirror.

| run | iter | candidate | fitness | sharpe | promoted | reason |
|-----|------|-----------|---------|--------|----------|--------|
| fleet-nightly-seed1-1782855309 | 0 | 21fbb630e10fe6c4 | 0.0371 | 0.0554 | True | promoted |
| fleet-nightly-seed1-1782855309 | 1 | cd0d15a7431ac206 | 0.0244 | 0.0509 | True | promoted |
| fleet-nightly-seed1-1782855309 | 2 | a38621ecbb942606 | 0.0348 | 0.0526 | True | promoted |
| fleet-nightly-seed1-1782855309 | 3 | 3c7da1f1de355a1c | 0.0315 | 0.0506 | True | promoted |
| fleet-nightly-seed1-1782855309 | 4 | 52d15c62d7c522e1 | 0.0323 | 0.0498 | True | promoted |
| fleet-nightly-seed1-1782855309 | 5 | 1c6a277d66379fbb | 0.0354 | 0.0535 | True | promoted |
| fleet-nightly-seed1-1782855309 | 6 | 87dd2daa489534b7 | 0.0348 | 0.0525 | True | promoted |
| fleet-nightly-seed1-1782855309 | 7 | 308a525351e6a602 | 0.0348 | 0.0526 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 21fbb630e10fe6c4 | 0.0471 | 0.0570 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0290 | 0.0460 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0301 | 0.0466 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0321 | 0.0486 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0327 | 0.0514 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0330 | 0.0507 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0350 | 0.0526 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0328 | 0.0511 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0311 | 0.0474 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0330 | 0.0493 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0340 | 0.0526 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0326 | 0.0493 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0345 | 0.0511 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0325 | 0.0509 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0308 | 0.0473 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0326 | 0.0490 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0286 | 0.0454 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0263 | 0.0408 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0273 | 0.0416 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0262 | 0.0421 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0239 | 0.0389 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | 21fbb630e10fe6c4 | 0.0259 | 0.0397 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 21fbb630e10fe6c4 | 0.0256 | 0.0390 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 21fbb630e10fe6c4 | 0.0260 | 0.0387 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0226 | 0.0368 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | 21fbb630e10fe6c4 | 0.0266 | 0.0396 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 21fbb630e10fe6c4 | 0.0251 | 0.0378 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0249 | 0.0408 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0264 | 0.0402 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0296 | 0.0444 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0283 | 0.0460 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0299 | 0.0454 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0332 | 0.0495 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0288 | 0.0464 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0308 | 0.0465 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0340 | 0.0505 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0283 | 0.0454 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0303 | 0.0455 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0334 | 0.0493 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0294 | 0.0468 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0323 | 0.0482 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0353 | 0.0520 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0277 | 0.0446 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0305 | 0.0460 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0334 | 0.0497 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0296 | 0.0474 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0324 | 0.0487 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0348 | 0.0516 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0321 | 0.0510 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0349 | 0.0522 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0373 | 0.0551 | True | promoted |
| fleet-replay-seed2-1782855325 | 0 | 3c7da1f1de355a1c | 0.0321 | 0.0515 | True | promoted |
| fleet-replay-seed2-1782855325 | 1 | a38621ecbb942606 | 0.0351 | 0.0530 | True | promoted |
| fleet-replay-seed2-1782855325 | 2 | 21fbb630e10fe6c4 | 0.0374 | 0.0558 | True | promoted |
