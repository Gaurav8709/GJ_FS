# Employee face matching — Stage 1

This change adds cosine-similarity matching to the existing FastAPI backend.
It does **not** detect faces or generate embeddings yet.

## Endpoints

- `GET /api/recognition/index/status`
- `POST /api/recognition/match`

Example request (vector abbreviated for illustration only):

```json
{
  "embedding": [0.12, -0.03, 0.2],
  "cam_id": "cam5",
  "track_id": "42"
}
```

The real request must contain exactly `FACE_EMBEDDING_DIM` finite, non-zero
values from the same face-embedding model used during enrollment.

## Trusted embedding format

Files are read from `backend/scripts/cv_embeddings/*_embeddings.json`.
A file is accepted only if it contains `embedding_type: "face"` and
`is_placeholder: false`. This intentionally excludes the existing listener's
random placeholder vectors.

```json
{
  "emp_id": "EMP001",
  "emp_name": "Example Employee",
  "embedding_type": "face",
  "embedding_model": "model-name-and-version",
  "is_placeholder": false,
  "facial_embeddings": [0.1, 0.2]
}
```

The vector above is abbreviated; the real vector must have the configured
dimension. Matching normalizes vectors and compares cosine similarity.

## Configuration

Add the following to `backend/app/config.py` inside `Settings`:

```python
FACE_MATCH_THRESHOLD: float = Field(default=0.45)
FACE_EMBEDDING_DIM: int = Field(default=512)
```

Optional `.env` overrides:

```dotenv
FACE_MATCH_THRESHOLD=0.45
FACE_EMBEDDING_DIM=512
```

The threshold is a starting value, not an accuracy guarantee. Calibrate it
against representative camera footage before production deployment.

## Router registration

In `backend/app/main.py`, add `recognition` to the router import tuple:

```python
from app.routers import (
    auth, cameras, floors, zones, workers, assignments, detections, analytics, streaming,
    forensics, footfall, face_alerts, heatmaps, recognition
)
```

Then register it alongside the existing routers:

```python
app.include_router(recognition.router)
```

## Test

From the `backend` directory in the VS Code terminal:

```powershell
python -m unittest discover -s tests -v
```

## Next stage

Connect a real face detector and embedding model to live camera frames, then
add video enrollment. Enrollment and live matching must use the same model and
version. Do not use the OSNet person re-identification model as a face model.
