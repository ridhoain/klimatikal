FROM python:3.12-slim

# Containerised so the runner can change without a rewrite. Oracle's free VM
# is the first host; if it has no capacity, the same image runs anywhere.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY encoding.py build_run.py ./

# Fails loudly at build time rather than at 02:00 if the GRIB stack is broken.
RUN python -c "import cfgrib, ecmwf.opendata, boto3; print('grib stack ok')"

ENTRYPOINT ["python", "build_run.py"]
