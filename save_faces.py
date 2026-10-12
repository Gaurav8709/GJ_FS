import os
import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface.utils import face_align

# ==========================================
# Configuration
# ==========================================

CLIPS_DIR = "clips"
REGISTERED_DIR = "registered_users"

SAMPLE_EVERY_N_FRAMES = 5
MAX_CROPS_PER_PERSON = 200        # files 00000.jpg .. 00199.jpg

# ---------- "both eyes visible" filter ----------
MIN_DET_SCORE = 0.60              # back-of-head / partial detections score low
MIN_FACE_SIZE = 40                # px, smaller side of the face bbox
MAX_ABS_YAW = 45.0                # degrees left/right (both eyes still visible)
MAX_ABS_PITCH = 35.0              # degrees up/down
NOSE_POS_MIN = 0.20               # nose x between the eyes, as a fraction
NOSE_POS_MAX = 0.80               #   of left-eye -> right-eye distance
MIN_EYE_DIST_RATIO = 0.25         # eye distance / face bbox width

# ---------- quality ----------
MIN_SHARPNESS = 30.0              # Laplacian variance; lower = blurrier

# ---------- de-duplication ----------
# Skip a face if its embedding is this similar to one already saved
# for the same person. Consecutive frames are typically > 0.92.
# Lower = fewer, more varied crops. Higher = more crops.
DEDUP_SIMILARITY = 0.92

# Save ArcFace-aligned 112x112 crops (same geometry face_search.py
# uses at runtime) instead of padded raw crops.
SAVE_ALIGNED_112 = True

os.makedirs(REGISTERED_DIR, exist_ok=True)

# ==========================================
# Initialize InsightFace
# ==========================================

print("[Init] Loading InsightFace...")

app = FaceAnalysis(
    name="buffalo_l",
    providers=[
        "CUDAExecutionProvider",
        "CPUExecutionProvider"
    ]
)

app.prepare(
    ctx_id=0,
    det_size=(640, 640)
)


# ==========================================
# Face filters
# ==========================================

def check_frontal(face):
    """
    Returns (ok, reason). Accept only faces where both eyes are visible.

    face.kps (5 points): left eye, right eye, nose, left mouth, right mouth
    face.pose (buffalo_l 3D landmark model): [pitch, yaw, roll] in degrees
    """

    if face.det_score < MIN_DET_SCORE:
        return False, "low_score"

    x1, y1, x2, y2 = face.bbox
    fw, fh = x2 - x1, y2 - y1

    if min(fw, fh) < MIN_FACE_SIZE:
        return False, "too_small"

    kps = face.kps
    if kps is None:
        return False, "no_landmarks"

    le, re, nose = kps[0], kps[1], kps[2]

    eye_dx = re[0] - le[0]

    # Eyes collapsed together or flipped -> profile / back of head
    if eye_dx <= 0 or eye_dx / max(fw, 1.0) < MIN_EYE_DIST_RATIO:
        return False, "eyes_not_visible"

    # Nose must sit between the two eyes. When the head turns far
    # enough to hide one eye, the nose crosses past that eye.
    nose_pos = (nose[0] - le[0]) / eye_dx
    if not (NOSE_POS_MIN <= nose_pos <= NOSE_POS_MAX):
        return False, "side_face"

    pose = getattr(face, "pose", None)
    if pose is not None:
        pitch, yaw = float(pose[0]), float(pose[1])
        if abs(yaw) > MAX_ABS_YAW:
            return False, "yaw"
        if abs(pitch) > MAX_ABS_PITCH:
            return False, "pitch"

    return True, "ok"


def sharpness(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def make_crop(frame, face):
    if SAVE_ALIGNED_112:
        return face_align.norm_crop(frame, landmark=face.kps, image_size=112)

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    px = int((x2 - x1) * 0.2)
    py = int((y2 - y1) * 0.2)
    x1, y1 = max(0, x1 - px), max(0, y1 - py)
    x2, y2 = min(w, x2 + px), min(h, y2 + py)
    return frame[y1:y2, x1:x2]


# ==========================================
# Extract faces from ONE video
# ==========================================

def extract_and_crop_faces(video_path, target_dir):

    os.makedirs(target_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"[Error] Could not open video: {video_path}")
        return 0

    # --------------------------------------
    # Continue from existing numbered crops
    # --------------------------------------

    existing_numbers = [
        int(f[:-4]) for f in os.listdir(target_dir)
        if f.lower().endswith(".jpg") and f[:-4].isdigit() and len(f[:-4]) == 5
    ]
    next_index = max(existing_numbers) + 1 if existing_numbers else 0

    print(f"[FACE EXTRACT] {video_path}")
    print(f"[FACE EXTRACT] Output -> {target_dir}")

    saved_embeddings = []   # normalized embeddings of crops saved this run
    saved_this_run = 0
    rejects = {}
    frame_idx = 0

    while cap.isOpened():

        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % SAMPLE_EVERY_N_FRAMES != 0:
            frame_idx += 1
            continue

        faces = app.get(frame)

        for face in faces:

            if next_index >= MAX_CROPS_PER_PERSON:
                print(f"[FACE EXTRACT] Reached {MAX_CROPS_PER_PERSON} image limit.")
                cap.release()
                print(f"[FACE EXTRACT DONE] saved={saved_this_run} rejected={rejects}")
                return saved_this_run

            ok, reason = check_frontal(face)
            if not ok:
                rejects[reason] = rejects.get(reason, 0) + 1
                continue

            crop_img = make_crop(frame, face)
            if crop_img is None or crop_img.size == 0:
                rejects["empty_crop"] = rejects.get("empty_crop", 0) + 1
                continue

            if sharpness(crop_img) < MIN_SHARPNESS:
                rejects["blurry"] = rejects.get("blurry", 0) + 1
                continue

            emb = getattr(face, "normed_embedding", None)
            if emb is not None and saved_embeddings:
                max_sim = float(np.max(np.dot(np.array(saved_embeddings), emb)))
                if max_sim > DEDUP_SIMILARITY:
                    rejects["duplicate"] = rejects.get("duplicate", 0) + 1
                    continue

            crop_filename = os.path.join(target_dir, f"{next_index:05d}.jpg")

            if cv2.imwrite(crop_filename, crop_img):
                yaw_txt = ""
                if getattr(face, "pose", None) is not None:
                    yaw_txt = f" yaw={face.pose[1]:+.0f}"
                print(f"[FACE SAVED] {crop_filename} "
                      f"score={face.det_score:.2f}{yaw_txt}")
                next_index += 1
                saved_this_run += 1
                if emb is not None:
                    saved_embeddings.append(emb)

        frame_idx += 1

    cap.release()

    print(f"[FACE EXTRACT DONE] {video_path}: saved={saved_this_run} "
          f"rejected={rejects}")

    return saved_this_run


# ==========================================
# Original batch mode
# ==========================================

def process_all_clips():

    video_extensions = (".mp4", ".avi", ".mov", ".mkv", ".webm")

    video_files = []
    for root, dirs, files in os.walk(CLIPS_DIR):
        for filename in sorted(files):
            if filename.lower().endswith(video_extensions):
                video_files.append(os.path.join(root, filename))

    if not video_files:
        print(f"[Warning] No video files found recursively inside: {CLIPS_DIR}")
        return

    print(f"[Info] Found {len(video_files)} video file(s)")

    for video_path in sorted(video_files):

        relative_path = os.path.relpath(video_path, CLIPS_DIR)
        relative_dir = os.path.dirname(relative_path)

        if relative_dir and relative_dir != ".":
            video_name = os.path.basename(relative_dir)
        else:
            video_name = os.path.splitext(os.path.basename(video_path))[0]

        target_dir = os.path.join(REGISTERED_DIR, video_name)

        existing_crops = [
            f for f in os.listdir(target_dir)
            if f.lower().endswith(".jpg") and f[:-4].isdigit() and len(f[:-4]) == 5
        ] if os.path.isdir(target_dir) else []

        if existing_crops:
            print(f"[SKIP] {video_name} already has {len(existing_crops)} face crop(s).")
            continue

        print(f"\n[Processing] {video_path}")
        extract_and_crop_faces(video_path, target_dir)

    print("\n[Done] All clips processed.")


# ==========================================
# IMPORTANT:
# Importing this file DOES NOT process clips.
# ==========================================

if __name__ == "__main__":
    process_all_clips()
