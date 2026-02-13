# 🚀 Deployment Guide

## Deployment Options

### Option 1: GitHub Actions (Recommended - Free)

#### Setup
1. Fork/create repository
2. Add GitHub Secrets (see SETUP.md)
3. Enable Actions in Settings
4. Workflow runs automatically 4 times daily

#### Monitoring
- Check Actions tab for runs
- View real-time logs
- Monitor artifacts (logs, reports)

#### Advantages
- ✅ Completely free
- ✅ No server to manage
- ✅ GitHub-native integration
- ✅ Built-in logging
- ✅ Easy to debug

#### Costs
- FREE (up to 2000 minutes/month)

---

### Option 2: Docker Container (Self-Hosted)

#### Local Docker
```bash
# Build image
docker build -t smart-shorts .

# Run container
docker run -d \
  --name smart-shorts \
  -v $(pwd)/db:/app/db \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  smart-shorts
```

#### Docker Compose
```bash
# Run everything
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

#### Advantages
- ✅ Full control
- ✅ Offline processing
- ✅ Custom scheduling
- ✅ Persistent storage

#### Costs
- Depends on hosting (VPS, cloud, etc.)

---

### Option 3: Cloud Platforms

#### Google Cloud Run (Recommended for Cloud)
```bash
# Build and push
gcloud builds submit --tag gcr.io/PROJECT_ID/smart-shorts

# Deploy
gcloud run deploy smart-shorts \
  --image gcr.io/PROJECT_ID/smart-shorts \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --set-env-vars=$(cat .env | tr '\n' ',')
```

#### AWS Lambda + EventBridge
- Package as container
- Set up EventBridge triggers
- Schedule cron jobs
- Monitor with CloudWatch

#### Azure Container Instances
- Create container image
- Schedule with Logic Apps
- Storage for database/logs

#### DigitalOcean App Platform
- Connect GitHub repo
- Auto-deploy on push
- Built-in monitoring

---

### Option 4: VPS/Dedicated Server

#### Setup SSH Access
```bash
# Connect to server
ssh user@your-vps-ip

# Clone repository
git clone https://github.com/youssefamen237/youssefamen237.git
cd youssefamen237

# Install dependencies
make setup
```

#### Install & Run
```bash
# Using systemd service
sudo cp systemd/smart-shorts.service /etc/systemd/system/
sudo systemctl start smart-shorts
sudo systemctl enable smart-shorts

# Or use cron
crontab -e
# Add: 0 */6 * * * /usr/bin/python3 /path/to/brain.py --single-cycle
```

#### Reverse Proxy (Optional)
```nginx
server {
    listen 80;
    server_name shorts.example.com;
    
    location /logs {
        alias /path/to/logs;
        autoindex on;
    }
    
    location /api {
        proxy_pass http://localhost:8080;
    }
}
```

---

## Performance Optimization

### Database Optimization
```python
# Create indexes
CREATE INDEX idx_video_upload_time 
ON video_performance(upload_time);

CREATE INDEX idx_content_dna_question 
ON content_dna(hash_question);

CREATE INDEX idx_upload_history_timestamp 
ON upload_history(upload_timestamp);
```

### Memory Management
- Implement batch processing
- Clear cache regularly
- Archive old logs
- Limit database retention

### Network Optimization
- Compress videos before upload
- Cache API responses
- Implement retry backoff
- Use connection pooling

---

## Monitoring & Alerts

### Health Checks
```python
# Monitor system health
def health_check():
    return {
        'database': db_ok(),
        'youtube_api': youtube_ok(),
        'disk_space': disk_ok(),
        'memory': memory_ok()
    }
```

### Discord Webhooks
```python
# Send alerts to Discord
def send_alert(message):
    webhook_url = os.getenv('DISCORD_WEBHOOK')
    requests.post(webhook_url, json={'content': message})
```

### Logging Levels
- `DEBUG` - Detailed information
- `INFO` - General information
- `WARNING` - Warning messages
- `ERROR` - Error messages
- `CRITICAL` - Critical errors

### Log Rotation
```python
# Daily log rotation
logging.handlers.TimedRotatingFileHandler(
    filename='logs/brain.log',
    when='midnight',
    interval=1,
    backupCount=30
)
```

---

## Scaling Strategies

### Horizontal Scaling
- Multiple instances with shared database
- Load balancing via cron jobs
- Distributed video processing

### Vertical Scaling
- Larger machines
- More CPU cores
- More memory
- Faster storage (SSD)

### Resource Limits
```yaml
# docker-compose.yml
resources:
  limits:
    cpus: '4'
    memory: 8G
  reservations:
    cpus: '2'
    memory: 4G
```

---

## Backup Strategy

### Daily Backups
```bash
#!/bin/bash
# Backup script
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup database
cp db/system.db $BACKUP_DIR/system_$DATE.db

# Backup logs
tar -czf $BACKUP_DIR/logs_$DATE.tar.gz logs/

# Upload to cloud storage
aws s3 cp $BACKUP_DIR/ s3://my-backups/shorts/ --recursive
```

### Database Snapshots
```bash
# SQLite backup
sqlite3 db/system.db ".backup db/system.backup"

# Restore if needed
sqlite3 db/system.db ".restore db/system.backup"
```

### Version Control
- Tag production releases
- Keep database schema in git
- Document migrations
- Test recovery process

---

## Continuous Improvement

### Monitoring Metrics
- Upload success rate
- Video performance scores
- API response times
- Database query times
- CPU/Memory usage
- Network bandwidth

### Analytics Dashboard
Build simple dashboard to track:
- Videos produced per day
- Average performance score
- Shadow ban status
- Content type distribution
- Revenue estimates

### Update Process
```bash
# Pull latest changes
git pull origin main

# Test locally
python src/brain.py --single-cycle

# If OK, push to production
git push heroku main  # or equivalent for your platform
```

---

## Security in Production

### API Key Rotation
- Change monthly
- Use different keys per environment
- Monitor usage patterns
- Revoke immediately if compromised

### Database Security
- Use encrypted connections
- Regular backups with encryption
- Daily integrity checks
- Limit access to localhost

### Network Security
- Use HTTPS only
- Enable firewall rules
- Whitelist IPs if possible
- Monitor for suspicious activity

### Audit Logging
- Log all API calls
- Track user actions
- Monitor file changes
- Alert on anomalies

---

## Troubleshooting Deployment

### Issues
**Container won't start:**
- Check Docker logs: `docker logs container-name`
- Verify environment variables
- Check disk space
- Review port conflicts

**YouTube API fails:**
- Verify refresh token is valid
- Check quota limits
- Review error logs
- Get new credentials if needed

**Database corruption:**
- Restore from backup
- Rebuild database
- Check disk space
- Verify permissions

**Memory leaks:**
- Monitor with `docker stats`
- Check for infinite loops
- Implement resource limits
- Restart periodically

---

## Cost Estimation

### GitHub Actions
- **$0** (free tier: 2000 mins/month)
- Sufficient for 4 runs/day

### AWS Lambda
- **~$1-5/month** for light usage
- Pay per execution
- Auto-scaling

### DigitalOcean Droplet
- **$5-20/month** basic VPS
- Fixed monthly cost
- Full control

### Google Cloud Run
- **$0.40-2/month** for light usage
- Per-100ms billing
- Auto-scaling

### Azure Container
- **$1-10/month** for light usage
- Storage + compute time
- Pay-as-you-go

---

**Recommended:** GitHub Actions for simplicity and cost-effectiveness.

*Last Updated: February 2026*
