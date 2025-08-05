#!/bin/bash
# Application Deployment Script for HoloWellness Chatbot
# Run this script on the EC2 instance to deploy the application

set -e  # Exit on any error

echo "🚀 HoloWellness Chatbot - Application Deployment"
echo "=============================================="

# Configuration
REPO_URL="https://github.com/azamkhan555622848/Holowellness_Chatbot_version_1.0.git"
APP_DIR="/opt/holowellness"
SERVICE_NAME="holowellness"

echo "📋 Configuration:"
echo "   Repository: $REPO_URL"
echo "   App Directory: $APP_DIR"
echo "   Service Name: $SERVICE_NAME"
echo ""

# Step 1: Clone Repository
echo "📦 Step 1: Cloning Repository..."
if [ -d "$APP_DIR/.git" ]; then
    echo "   Repository already exists, pulling latest changes..."
    cd $APP_DIR
    git pull origin main
else
    echo "   Cloning repository..."
    sudo rm -rf $APP_DIR
    git clone $REPO_URL $APP_DIR
    sudo chown -R ubuntu:ubuntu $APP_DIR
fi

cd $APP_DIR

# Step 2: Setup Python Environment
echo ""
echo "🐍 Step 2: Setting up Python Environment..."
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install production dependencies
pip install --upgrade pip
pip install -r requirements-prod.txt

echo "   ✅ Python environment ready"

# Step 3: Build Frontend
echo ""
echo "🔨 Step 3: Building Frontend..."
cd $APP_DIR

# Install Node.js dependencies
npm install

# Build React frontend for production
npm run build

# Create frontend directory and copy build files
sudo mkdir -p $APP_DIR/frontend/dist
sudo cp -r dist/* $APP_DIR/frontend/dist/
sudo chown -R ubuntu:ubuntu $APP_DIR/frontend

echo "   ✅ Frontend built and deployed"

# Step 4: Configure Environment  
echo ""
echo "⚙️  Step 4: Configuring Environment..."
cd backend

# Copy production environment file
if [ -f ".env.production" ]; then
    cp .env.production .env
    echo "   ✅ Production environment configured"
else
    echo "   ⚠️  .env.production not found, creating from example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "   Please edit .env with your actual credentials"
    fi
fi

# Step 5: Sync PDFs from S3
echo ""
echo "📄 Step 5: Syncing PDFs from S3..."
python sync_rag_pdfs.py || echo "   ⚠️  PDF sync failed - continuing anyway"

# Step 6: Test Application
echo ""
echo "🧪 Step 6: Testing Application..."
export FLASK_ENV=production
python -c "from app import app; print('✅ Application imports successfully')" || {
    echo "❌ Application test failed"
    exit 1
}

# Step 7: Create Systemd Service
echo ""
echo "🔧 Step 7: Creating Systemd Service..."

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=HoloWellness Chatbot API
After=network.target

[Service]
Type=exec
User=ubuntu
Group=ubuntu
WorkingDirectory=$APP_DIR/backend
ExecStart=$APP_DIR/backend/venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --timeout 300 app:app
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=10

EnvironmentFile=$APP_DIR/backend/.env

[Install]
WantedBy=multi-user.target
EOF

# Step 8: Configure Nginx
echo ""
echo "🌐 Step 8: Configuring Nginx..."

# Get instance public IP
INSTANCE_IP=\$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

sudo tee /etc/nginx/sites-available/${SERVICE_NAME} > /dev/null << EOF
server {
    listen 80;
    server_name \$INSTANCE_IP;

    # API routes
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # Serve React frontend (if built)
    location / {
        root $APP_DIR/frontend/dist;
        try_files \$uri \$uri/ /index.html;
        
        # Fallback to backend if frontend not available
        error_page 404 = @backend;
    }

    location @backend {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/${SERVICE_NAME} /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx configuration
sudo nginx -t

# Step 9: Start Services
echo ""
echo "🚀 Step 9: Starting Services..."

# Reload systemd and start services
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl start ${SERVICE_NAME}
sudo systemctl reload nginx

# Step 10: Verify Deployment
echo ""
echo "✅ Step 10: Verifying Deployment..."

# Wait a moment for services to start
sleep 5

# Check service status
if sudo systemctl is-active --quiet ${SERVICE_NAME}; then
    echo "   ✅ HoloWellness service is running"
else
    echo "   ❌ HoloWellness service failed to start"
    sudo systemctl status ${SERVICE_NAME}
    exit 1
fi

if sudo systemctl is-active --quiet nginx; then
    echo "   ✅ Nginx is running"
else
    echo "   ❌ Nginx failed to start"
    sudo systemctl status nginx
    exit 1
fi

# Test health endpoint
HEALTH_STATUS=\$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health)
if [ "\$HEALTH_STATUS" = "200" ]; then
    echo "   ✅ Health check passed"
else
    echo "   ⚠️  Health check returned status: \$HEALTH_STATUS"
fi

# Get final instance IP
INSTANCE_IP=\$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

# Summary
echo ""
echo "🎉 Deployment Complete!"
echo "====================="
echo "✅ Application deployed successfully"
echo "✅ Services are running"
echo "✅ Nginx configured"
echo ""
echo "🔗 Access your application:"
echo "   Health Check: http://\$INSTANCE_IP/health"
echo "   API Base URL: http://\$INSTANCE_IP/api/"
echo ""
echo "📊 Service Management:"
echo "   Check status: sudo systemctl status $SERVICE_NAME"
echo "   View logs: sudo journalctl -f -u $SERVICE_NAME"
echo "   Restart: sudo systemctl restart $SERVICE_NAME"
echo ""
echo "🔧 Configuration files:"
echo "   App config: $APP_DIR/backend/.env"
echo "   Nginx config: /etc/nginx/sites-available/$SERVICE_NAME"
echo "   Service config: /etc/systemd/system/${SERVICE_NAME}.service"