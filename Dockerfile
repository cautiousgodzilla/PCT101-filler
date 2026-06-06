# PCT → Form 1 Filler — container image for Render (or any Docker host).
#
# Uses full Playwright + Chromium (no @sparticuz / serverless hacks). The
# official Playwright Python image ships the system libraries Chromium needs;
# we install the matching browser binary for whatever playwright version pip
# resolves, so the two always line up.
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the Chromium build matching the installed playwright (the base image
# already provides the OS dependencies).
RUN playwright install chromium

COPY . .

# Render injects PORT; local_server.py reads it (default 8000). Bind 0.0.0.0.
ENV PORT=10000
EXPOSE 10000

CMD ["python", "local_server.py"]
