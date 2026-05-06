# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A small Python learning repository with standalone scripts and a Jupyter notebook for data analysis. No build system, package manager, or test framework is configured.

## Running Code

```bash
# Run standalone scripts (interactive — require user input)
python kello.py
python viikonpaivat.py

# Launch Jupyter notebook
jupyter notebook Census_tests.ipynb
```

## Architecture

The repo contains three independent components:

- **`kello.py`** — Clock/alarm calculator. Takes current hour and wait duration as input, computes the alarm time modulo 24.
- **`viikonpaivat.py`** — Day-of-week calculator. Takes departure day and trip length, returns return day modulo 7.
- **`Census_tests.ipynb`** — Jupyter notebook that loads `census.csv` (not committed; must be supplied separately), then performs grouped aggregations, boolean masking, Pearson correlation analysis, state-size classification, and bar chart visualization using pandas, numpy, and scipy.

`Salitrack - Sheet1.csv` is a data file unrelated to the scripts and notebook.

## Dependencies

The notebook requires `pandas`, `numpy`, and `scipy`. The scripts use only the Python standard library.
