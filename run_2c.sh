#!/bin/zsh
# Sequential: never two models on the GPU at once (concurrent GPU work caused two Metal OOMs
# in Stage 1 and contaminated a measurement).
set -x
PY=/Users/mangilipallinagaraj/anaconda3/envs/doc-intel/bin/python
$PY -m src.stage2_compare --arm base
$PY -m src.stage2_compare --arm tuned
$PY -m src.stage2_compare --arm prompted
$PY -m src.stage2_regression --suite arc    --arm base
$PY -m src.stage2_regression --suite arc    --arm tuned
$PY -m src.stage2_regression --suite stage1 --arm base
$PY -m src.stage2_regression --suite stage1 --arm tuned
echo "ALL_2C_RUNS_COMPLETE"
