import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, get_db, async_session
from app.services.camera_manager import CameraManager
from app.services.batch_inference_engine import BatchInferenceEngine
from app.services.auto_assignment_service import AutoAssignmentService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gjfashion.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for FastAPI."""
    logger.info("Starting up GJ-Fashion API...")
    
    # Initialize Camera Manager and Batch Inference
    manager = CameraManager.get_instance()
    batch_engine = BatchInferenceEngine.get_instance()
    auto_assign = AutoAssignmentService.get_instance()
    
    # Ensure database tables exist in AWS RDS / Postgres
    try:
        from app.database import Base
        from app.models import camera, floor, user, worker, new_features
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing DB schema: {e}")

    # Load cameras from DB and start
    try:
        async with async_session() as session:
            await manager.load_cameras_from_db(session)
            manager.start_all()
            batch_engine.start()
            auto_assign.start()
    except Exception as e:
        logger.error(f"Error starting cameras: {e}")
        
    yield
    
    # Shutdown
    logger.info("Shutting down GJ-Fashion API...")
    auto_assign.stop()
    batch_engine.stop()
    manager.stop_all()
    await engine.dispose()


app = FastAPI(
    title="GJ-Fashion Smart Showroom API",
    description="Backend API for AI-powered showroom analytics.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, specify the actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static directory for file uploads
import os
from fastapi.staticfiles import StaticFiles
os.makedirs("static_files", exist_ok=True)
app.mount("/static", StaticFiles(directory="static_files"), name="static")

# Include Routers
from app.routers import (
    auth, cameras, floors, zones, workers, assignments, detections, analytics, streaming,
    forensics, footfall, face_alerts, heatmaps
)

app.include_router(auth.router)
app.include_router(floors.router)
app.include_router(cameras.router)
app.include_router(zones.router)
app.include_router(workers.router)
app.include_router(assignments.router)
app.include_router(detections.router)
app.include_router(analytics.router)
app.include_router(streaming.router)
app.include_router(forensics.router)
app.include_router(footfall.router)
app.include_router(face_alerts.router)
app.include_router(heatmaps.router)

from fastapi import WebSocket, WebSocketDisconnect
from app.routers.streaming import alert_manager

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await alert_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        alert_manager.disconnect(websocket)

@app.websocket("/ws/stats")
async def websocket_stats(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass

from app.services.stream_service import ws_sender
from fastapi import Query

@app.websocket("/ws/streams/{camera_id}")
async def websocket_stream(
    websocket: WebSocket, 
    camera_id: str,
    q: int = Query(75),
    fps: float = Query(30.0),
    show_zones: bool = Query(True)
):
    await websocket.accept()
    await ws_sender(websocket, camera_id, quality=q, fps=fps, show_zones=show_zones)


@app.get("/api/health", tags=["System"])
async def health_check():
    """System health check endpoint."""
    return {"status": "ok"}
