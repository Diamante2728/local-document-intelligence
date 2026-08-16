#!/bin/zsh
cd "/Users/mangilipallinagaraj/Desktop/Trustworthy Local Document Intelligence"
PY=/Users/mangilipallinagaraj/anaconda3/envs/doc-intel/bin/python
echo "### ARC64 base $(date +%H:%M:%S)"
$PY -m src.stage2_regression --suite arc --arm base
echo "### ARC64 tuned $(date +%H:%M:%S)"
$PY -m src.stage2_regression --suite arc --arm tuned
echo "ARC64_COMPLETE $(date +%H:%M:%S)"
