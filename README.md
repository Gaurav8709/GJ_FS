# 🛍️ GJ-Fashion AI Smart Showroom

Welcome to the **GJ-Fashion AI Smart Showroom** repository. This system powers real-time Computer Vision analytics, Footfall tracking, Face Recognition alert notifications, Heatmap overlays, and Smart Vehicle Intelligence for the showroom.

---

## 📌 Table of Contents
1. [Architecture Overview](#-architecture-overview)
2. [Local Development Setup](#-local-development-setup)
3. [EC2 Server Deployment Guide (Step-by-Step)](#-ec2-server-deployment-guide-step-by-step)
4. [Computer Vision (CV) Scripts & CLI Usage](#-computer-vision-cv-scripts--cli-usage)
5. [Useful Troubleshooting & Service Commands](#-useful-troubleshooting--service-commands)

---

## 🏗️ Architecture Overview

- **Frontend**: Vite + React SPA (Hosted on Vercel)
- **Backend API**: FastAPI (Python 3.14) running on AWS EC2 (`65.2.158.148`)
- **Reverse Proxy**: Nginx (Listens on Port 80, forwards `/api/` & `/ws/` to Port 8000)
- **Process Manager**: Systemd (`gj_backend.service`)
- **Database**: PostgreSQL (AWS RDS) & SQLite
- **Media Storage**: AWS S3 Bucket (`gj-snapshots`)

---

## 💻 Local Development Setup

### 1. Backend Setup
```bash
cd backend
source venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend Setup
```bash
cd frontend
npm run dev
```

---

## 🚀 EC2 Server Deployment Guide (Step-by-Step)

Whenever you make changes to the backend or CV scripts locally and want to update the live EC2 server (`65.2.158.148`), follow these 3 main steps:

### **STEP 1: Push Changes from Local Machine to GitHub**

Run these commands in your local terminal:
```bash
# 1. Check changed files
git status

# 2. Stage all modifications
git add .

# 3. Commit your changes
git commit -m "Update backend feature and CV scripts"

# 4. Push to GitHub main branch
git push origin main
```

---

### **STEP 2: Pull Updated Code on EC2 Server**

1. **SSH into the EC2 Server**:
   ```bash
   ssh -i /path/to/your-key.pem ubuntu@65.2.158.148
   ```

2. **Navigate to the Backend Directory (`~/app/backend`)**:
   ```bash
   cd ~/app/backend
   ```

3. **Pull the Latest Code from GitHub**:
   ```bash
   git pull origin main
   ```

---

### **STEP 3: Restart Backend & Nginx Services**

In your EC2 terminal (`~/app/backend`), run:

```bash
# 1. Activate Virtual Environment (if needed)
source venv/bin/activate

# 2. Restart the FastAPI Systemd Backend Service
sudo systemctl restart gj_backend

# 3. Check Backend Status (Verify it says "active (running)")
sudo systemctl status gj_backend

# 4. (Optional) Restart Nginx if proxy configs were changed
sudo systemctl restart nginx
```

---

## 🎥 Computer Vision (CV) Scripts & CLI Usage

The repository includes zero-dependency CV metadata pushers inside `backend/scripts/`. They feature automatic port fallback (`:8000` ➔ Port `80`) and execution speeds under 35ms.

### 1. Footfall Analytics Pusher
Pushes real-time entry/exit counts and demographic breakdowns:
```bash
python scripts/cv_footfall_pusher.py --cam-id cam6 --entries 1 --exits 0 --api-url http://65.2.158.148
```

### 2. Employee Face Recognition Pusher
Broadcasts live face alerts to the frontend:
```bash
python scripts/cv_employee_detector_pusher.py --emp-id EMP-105 --emp-name Gaurav --cam-id cam06 --api-url http://65.2.158.148
```

### 3. Camera Heatmap Pusher
Uploads camera foot-traffic KDE heatmap images:
```bash
python scripts/cv_heatmap_pusher.py --cam-id cam1 --image test_heatmap.png --density 0.88 --api-url http://65.2.158.148
```

### 4. Facial Embedding Listener Pipeline
Polls new employee clips and indexes 512-D vectors:
```bash
python scripts/cv_listener_pipeline.py --poll --interval 10 --api-url http://65.2.158.148
```

---

## 🛠️ Useful Troubleshooting & Service Commands

### View Live Backend Server Logs on EC2:
```bash
sudo journalctl -u gj_backend -f -n 100
```

### Fix "Address Already in Use" Error (Port 8000):
If Uvicorn gets stuck on port 8000:
```bash
lsof -t -i:8000 | xargs kill -9
```

### Check Nginx Configuration & Status:
```bash
sudo nginx -t
sudo systemctl status nginx
```
