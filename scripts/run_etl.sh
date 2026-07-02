#!/bin/bash
# Run the ETL pipeline on Azure (via SSH: bash scripts/run_etl.sh)
set -e
cd /home/site/wwwroot
echo "Starting ETL pipeline..."
python main.py
echo "ETL complete. Database: data/economic_stress.db"
