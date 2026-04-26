#!/bin/bash
# VPS Deployment Script for US100 Signal Monitor + Dashboard
# Ubuntu 20.04+ / Debian 11+

set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
echo "=== US100 Monitor VPS Deployment ==="
echo ""

# 1. System dependencies
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv curl git

# 2. Node.js (required for TradingView bridge)
echo "[2/6] Installing Node.js..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
fi
echo "  Node.js $(node --version)"

# 3. Python virtual environment
echo "[3/6] Setting up Python venv..."
python3 -m venv "$SCRIPT_DIR/.venv"
source "$SCRIPT_DIR/.venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
pip install tvscreener smartmoneyconcepts flask pytz -q

# 4. Node.js bridge dependencies
echo "[4/6] Installing Node.js bridge dependencies..."
cd "$SCRIPT_DIR/tv_bridge"
npm install --silent
cd "$SCRIPT_DIR"

# 5. Copy .env if not exists
echo "[5/6] Configuring environment..."
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "  Created .env — edit it now!"
    echo "  nano $SCRIPT_DIR/.env"
    exit 1
fi

# 6. Systemd services
echo "[6/6] Installing systemd services..."

# Monitor service
cat << EOF | sudo tee /etc/systemd/system/us100-monitor.service
[Unit]
Description=CFI:US100 Signal Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$SCRIPT_DIR
Environment="SMC_CREDIT=0"
ExecStart=$SCRIPT_DIR/.venv/bin/python run_us100_monitor.py
Restart=always
RestartSec=10
StandardOutput=append:$SCRIPT_DIR/monitor.log
StandardError=append:$SCRIPT_DIR/monitor.log

[Install]
WantedBy=multi-user.target
EOF

# Dashboard service
cat << EOF | sudo tee /etc/systemd/system/us100-dashboard.service
[Unit]
Description=CFI:US100 Signal Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$SCRIPT_DIR
Environment="FLASK_APP=dashboard.py"
ExecStart=$SCRIPT_DIR/.venv/bin/python -c "from dashboard import run_dashboard; run_dashboard(port=5000)"
Restart=always
RestartSec=10
StandardOutput=append:$SCRIPT_DIR/dashboard.log
StandardError=append:$SCRIPT_DIR/dashboard.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable us100-monitor us100-dashboard

echo ""
echo "=== Deployment complete ==="
echo ""
echo "  Start services:"
echo "  sudo systemctl start us100-monitor us100-dashboard"
echo ""
echo "  Check status:"
echo "  sudo systemctl status us100-monitor"
echo "  sudo systemctl status us100-dashboard"
echo ""
echo "  View logs:"
echo "  tail -f $SCRIPT_DIR/monitor.log"
echo "  tail -f $SCRIPT_DIR/dashboard.log"
echo ""
echo "  Dashboard:  http://$(curl -s ifconfig.me):5000"
echo ""
echo "  Edit .env first if needed!"
