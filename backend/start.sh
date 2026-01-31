#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Load environment variables from .env file (ignoring comments and empty lines)
set -a
source <(grep -v '^#' .env | grep -v '^$')
set +a

# Start the FastAPI server
python3 app.py
