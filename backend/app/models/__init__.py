"""
GJ-Fashion — ORM Models Package
Imports all models so Alembic / Base.metadata sees them.
"""

from app.models.floor import Floor, Section          # noqa: F401
from app.models.camera import Camera, CameraZone     # noqa: F401
from app.models.worker import Worker, WorkerAssignment  # noqa: F401
from app.models.detection import DetectionLog, Alert  # noqa: F401
from app.models.user import User, CameraAccess       # noqa: F401
from app.models.new_features import ForensicClip, FootfallRecord, EmployeeFace, CameraHeatmap  # noqa: F401
