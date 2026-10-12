#!/usr/bin/env python3

import sys
sys.path.append('../')
import gi
import configparser

gi.require_version('Gst', '1.0')
gi.require_version('GstRtsp', '1.0')
from gi.repository import GLib, Gst, GstRtsp

from ctypes import *
import time
import math
import platform
import numpy as np
import pyds
import cv2
import os
import shutil
from datetime import datetime

# DeepStream Common Imports
from common.platform_info import PlatformInfo
from common.bus_call import bus_call
from common.FPS import PERF_DATA

# Pure TensorRT Imports
import tensorrt as trt
import pycuda.driver as cuda

from collections import Counter, deque
import json
import threading
import requests

import queue

from concurrent.futures import ThreadPoolExecutor

# ==========================================
# CONFIGURATION
# ==========================================
REGISTERED_DIR = 'registered_users'
ATTENDANCE_ROOT_DIR = 'attendance_records'

DET_ENGINE_PATH = 'models/det_model.engine' 
REC_ENGINE_PATH = 'models/rec_model.engine' 

CONFIDENCE_THRESHOLD = 0.60
REQUIRED_DURATION = 0.0 


MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
MUXER_BATCH_TIMEOUT_USEC = 5000
TILED_OUTPUT_WIDTH = 1920
TILED_OUTPUT_HEIGHT = 1080

perf_data = None
platform_info = None
cuda_context = None

# ==========================================
# SOURCE CONFIGURATION
# ==========================================

# FILE sources:
#     uridecodebin is retained.
#
# RTSP sources:
#     nvurisrcbin is used so NVIDIA's RTSP reconnect
#     handling remains inside the source element.
#
# A failed RTSP source is never destroyed/recreated by
# application-level reconnect threads.

RTSP_RECONNECT_INTERVAL_SEC = 5
RTSP_RECONNECT_ATTEMPTS = -1
RTSP_LATENCY_MS = 500

source_bins = {}
source_uris = {}
source_is_rtsp = {}
source_finished = {}
source_mux_pads = {}

# ==========================================
# MULTI-CAMERA ATTENDANCE / ALERT STATE
# ==========================================

MATCH_HISTORY_SIZE = 10
MATCH_MAJORITY = 6

# Recognition history:
# {
#     stream_index: {
#         face_track_id: deque(...)
#     }
# }

last_detection_sent = {}

match_history = {}

# Temporary face tracks for each camera.
# Each camera has completely independent tracks.
face_tracks = {}

# Attendance verification state:
# {
#     (camera_id, person_name): last_seen_timestamp
# }
presence_tracker = {}

# Last alert sent for each person on each camera.
# Key = (camera_id, person_name)
last_alert_time = {}

# Persisted alert state.
ALERT_STATE_FILE = "attendance_alert_state.json"

# Don't write JSON for every detection.
# State is flushed at most once per this interval.
ALERT_STATE_SAVE_INTERVAL = 5.0

_last_alert_state_save = 0.0
_alert_state_lock = threading.Lock()

# Alert endpoint
BASE_URL = "http://52.66.48.116:8000"
# BASE_URL = "http://52.66.48.116:8000/api/ingest/detection"
DETECTION_API_URL = f"{BASE_URL}/api/ingest/detection"
BULK_DETECTION_API_URL = f"{BASE_URL}/api/ingest/detections/bulk"

# If you want another alert for the same person/camera after this
# many seconds, change this.
# None = only one alert per person/camera for the entire process.
ALERT_COOLDOWN_SECONDS = None


if not os.path.exists(REGISTERED_DIR):
    os.makedirs(REGISTERED_DIR)




alert_queue = queue.Queue()

def background_alert_worker():
    while True:
        try:
            camera_id, person_name, frame_capture = alert_queue.get()
            # Perform blocking network calls here safely off the main pipeline thread
            alert_success = send_attendance_alert(camera_id, person_name, frame_capture)
            if alert_success:
                print(f"NEW ATTENDANCE ALERT (Background): {camera_id} -> {person_name}")
            alert_queue.task_done()
        except Exception as e:
            print(f"[ALERT WORKER ERROR]: {e}")

# Start the worker thread in main() before running the pipeline:
threading.Thread(target=background_alert_worker, daemon=True).start()

###################################

# Create a dedicated pool for background network tasks
alert_pool = ThreadPoolExecutor(max_workers=4)

detection_pool = ThreadPoolExecutor(max_workers=4)

def queue_attendance_alert(camera_id, person_name, frame_capture):
    # Submit tasks asynchronously to the thread pool
    alert_pool.submit(async_upload_worker, camera_id, person_name, frame_capture)

def async_upload_worker(camera_id, person_name, frame_capture):
    try:
        alert_success = send_attendance_alert(camera_id, person_name, frame_capture)
        if alert_success:
            print(f"NEW ATTENDANCE ALERT (Pool): {camera_id} -> {person_name}")
    except Exception as e:
        print(f"[ALERT POOL ERROR]: {e}")


def load_alert_state():
    """
    Load last-alert information once when the application starts.

    Format:
    {
        "cam0": {
            "Ajay_Patel_Assistan_Manager": 1724240000.123
        },
        "cam1": {
            "Ajay_Patel_Assistan_Manager": 1724240012.456
        }
    }
    """

    global last_alert_time

    if not os.path.exists(ALERT_STATE_FILE):
        return

    try:
        with open(ALERT_STATE_FILE, "r") as f:
            data = json.load(f)

        with _alert_state_lock:
            last_alert_time.clear()

            for camera_id, people in data.items():
                for person_name, timestamp in people.items():
                    last_alert_time[(camera_id, person_name)] = float(timestamp)

        print(f"Loaded alert state from {ALERT_STATE_FILE}")

    except Exception as e:
        print(f"WARNING: Could not load alert state: {e}")


def save_alert_state(force=False):
    """
    Save alert state periodically instead of doing disk I/O
    for every detected frame.
    """

    global _last_alert_state_save

    now = time.time()

    if not force and (now - _last_alert_state_save) < ALERT_STATE_SAVE_INTERVAL:
        return

    with _alert_state_lock:
        try:
            data = {}

            for (camera_id, person_name), timestamp in last_alert_time.items():
                if camera_id not in data:
                    data[camera_id] = {}

                data[camera_id][person_name] = timestamp

            tmp_file = ALERT_STATE_FILE + ".tmp"

            with open(tmp_file, "w") as f:
                json.dump(data, f, indent=2)

            # Atomic replacement.
            os.replace(tmp_file, ALERT_STATE_FILE)

            _last_alert_state_save = now

        except Exception as e:
            print(f"WARNING: Could not save alert state: {e}")
            
def get_camera_id(stream_index, source_uri):
    """
    Generate a stable ID for each input.

    RTSP:
        rtsp://...cam9... -> cam9 if possible

    Otherwise:
        stream0
        stream1
        stream2
        ...

    You can also explicitly control this from main().
    """

    # If your RTSP URL contains something like cam9,
    # use that as the camera ID.
    uri_lower = source_uri.lower()

    import re

    match = re.search(r'cam[_-]?(\d+)', uri_lower)

    if match:
        return f"cam{match.group(1)}"

    return f"stream{stream_index}"



# ==========================================
# TENSORRT EXECUTION ENGINE WITH CONTEXT COUPLING
# ==========================================

class TRTRunner:
    def __init__(self, engine_path, cuda_context):
        self.logger = trt.Logger(trt.Logger.WARNING)
        trt.init_libnvinfer_plugins(self.logger, '')
        
        self.ctx = cuda_context
        self.ctx.push()
        
        with open(engine_path, "rb") as f, trt.Runtime(self.logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())
            
        self.context = self.engine.create_execution_context()
        self.stream = cuda.Stream()
        
        self.inputs = []
        self.outputs = []
        self.allocations = {}
        
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            dtype = trt.nptype(self.engine.get_tensor_dtype(name))
            shape = self.engine.get_tensor_shape(name)
            mode = self.engine.get_tensor_mode(name)
            
            if mode == trt.TensorIOMode.INPUT:
                self.inputs.append({'name': name, 'dtype': dtype, 'shape': shape})
            else:
                self.outputs.append({'name': name, 'dtype': dtype, 'shape': shape})
                
        self.ctx.pop()

    def __call__(self, input_data):
        self.ctx.push()
        
        inp = self.inputs[0]
        name = inp['name']
        self.context.set_input_shape(name, input_data.shape)
        
        for io_tensor in self.inputs + self.outputs:
            t_name = io_tensor['name']
            t_dtype = io_tensor['dtype']
            t_shape = self.context.get_tensor_shape(t_name)
            size = trt.volume(t_shape) * np.dtype(t_dtype).itemsize
            
            if t_name not in self.allocations or self.allocations[t_name]['size'] < size:
                if t_name in self.allocations:
                    self.allocations[t_name]['ptr'].free()
                self.allocations[t_name] = {'ptr': cuda.mem_alloc(size), 'size': size}
            self.context.set_tensor_address(t_name, int(self.allocations[t_name]['ptr']))
            
        input_data = np.ascontiguousarray(input_data, dtype=inp['dtype'])
        cuda.memcpy_htod_async(self.allocations[name]['ptr'], input_data, self.stream)
        self.context.execute_async_v3(stream_handle=self.stream.handle)
        
        results = []
        for out in self.outputs:
            t_name = out['name']
            t_shape = self.context.get_tensor_shape(t_name)
            out_data = np.empty(t_shape, dtype=out['dtype'])
            cuda.memcpy_dtoh_async(out_data, self.allocations[t_name]['ptr'], self.stream)
            results.append(out_data)
            
        self.stream.synchronize()
        self.ctx.pop()
        return results

# ==========================================
# PURE NUMPY PRE/POST PROCESSING 
# ==========================================

class Face:
    def __init__(self, bbox, kps, det_score):
        self.bbox = bbox
        self.kps = kps
        self.det_score = det_score
        self.embedding = None

class PureSCRFD:
    def __init__(self, engine_path, cuda_context, input_size=(640, 640), conf_thresh=0.5, nms_thresh=0.4):
        self.engine = TRTRunner(engine_path, cuda_context)
        self.input_size = input_size
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self.strides = [8, 16, 32]
        self.center_cache = self._generate_anchors()

    def _generate_anchors(self):
        cache = {}
        for stride in self.strides:
            h, w = self.input_size[0] // stride, self.input_size[1] // stride
            grid_y, grid_x = np.mgrid[0:h, 0:w]
            grid = np.stack((grid_x, grid_y), axis=-1).astype(np.float32)
            grid = (grid * stride) + (stride // 2)
            cache[stride] = np.repeat(grid.reshape(-1, 2), 2, axis=0)
        return cache

    def detect(self, img):
        ratio = min(self.input_size[0] / img.shape[0], self.input_size[1] / img.shape[1])
        new_w, new_h = int(img.shape[1] * ratio), int(img.shape[0] * ratio)
        resized = cv2.resize(img, (new_w, new_h))
        
        pad_img = np.zeros((self.input_size[0], self.input_size[1], 3), dtype=np.uint8)
        pad_img[:new_h, :new_w, :] = resized
        
        pad_img_rgb = pad_img[:, :, ::-1] 
        blob = (pad_img_rgb.astype(np.float32) - 127.5) / 128.0
        blob = np.expand_dims(blob.transpose(2, 0, 1), axis=0)
        
        outputs = self.engine(blob)
        scores, bboxes, kpss = [], [], []
        
        for out in outputs:
            out = out.reshape(-1, out.shape[-1]) 
            num_points = out.shape[0]
            stride = 8 if num_points == 12800 else (16 if num_points == 3200 else 32)
            if out.shape[1] == 1: scores.append((stride, out))
            elif out.shape[1] == 4: bboxes.append((stride, out))
            elif out.shape[1] == 10: kpss.append((stride, out))

        scores, bboxes, kpss = dict(scores), dict(bboxes), dict(kpss)
        final_boxes, final_kps, final_scores = [], [], []
        
        for stride in self.strides:
            score = scores[stride].flatten()
            mask = score > self.conf_thresh
            if not mask.any(): continue
            valid_scores = score[mask]
            valid_centers = self.center_cache[stride][mask]
            
            bbox_reg = bboxes[stride][mask]
            x1 = valid_centers[:, 0] - bbox_reg[:, 0] * stride
            y1 = valid_centers[:, 1] - bbox_reg[:, 1] * stride
            x2 = valid_centers[:, 0] + bbox_reg[:, 2] * stride
            y2 = valid_centers[:, 1] + bbox_reg[:, 3] * stride
            valid_boxes = np.stack([x1, y1, x2, y2], axis=-1) / ratio
            
            kps_reg = kpss[stride][mask]
            valid_kps = []
            for i in range(0, 10, 2):
                kx = valid_centers[:, 0] + kps_reg[:, i] * stride
                ky = valid_centers[:, 1] + kps_reg[:, i+1] * stride
                valid_kps.append(kx)
                valid_kps.append(ky)
            valid_kps = np.stack(valid_kps, axis=-1).reshape(-1, 5, 2) / ratio
            
            final_boxes.extend(valid_boxes)
            final_kps.extend(valid_kps)
            final_scores.extend(valid_scores)
            
        if not final_boxes: return []
        
        final_boxes = np.array(final_boxes)
        final_scores = np.array(final_scores)
        final_kps = np.array(final_kps)
        
        xywh_boxes = final_boxes.copy()
        xywh_boxes[:, 2] = xywh_boxes[:, 2] - xywh_boxes[:, 0]
        xywh_boxes[:, 3] = xywh_boxes[:, 3] - xywh_boxes[:, 1]
        
        indices = cv2.dnn.NMSBoxes(xywh_boxes.tolist(), final_scores.tolist(), self.conf_thresh, self.nms_thresh)
        faces = [Face(final_boxes[i], final_kps[i], final_scores[i]) for i in indices.flatten()]
        return faces

class PureArcFace:
    def __init__(self, engine_path, cuda_context):
        self.engine = TRTRunner(engine_path, cuda_context)
        self.src_pts = np.array([
            [38.2946, 51.6963], [73.5318, 51.5014],
            [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
        ], dtype=np.float32)

    def align(self, img, kps):
        tform = cv2.estimateAffinePartial2D(kps, self.src_pts, method=cv2.LMEDS)[0]
        # UPGRADE 1: Use INTER_CUBIC for high-quality mathematical zooming instead of default linear
        return cv2.warpAffine(img, tform, (112, 112), flags=cv2.INTER_CUBIC)

    def get_feat(self, imgs):
        feats = []
        for img in imgs:
            img_rgb = img[:, :, ::-1]
            blob = (img_rgb.astype(np.float32) / 127.5) - 1.0
            blob = np.expand_dims(blob.transpose(2, 0, 1), axis=0)
            feat = self.engine(blob)[0].flatten()
            feats.append(feat)
        return feats

    def get(self, img, face):
        aligned = self.align(img, face.kps)
        
        # UPGRADE 2: Apply a gentle Unsharp Mask to the zoomed 112x112 image to define edges for the AI
        gaussian = cv2.GaussianBlur(aligned, (0, 0), 2.0)
        sharpened = cv2.addWeighted(aligned, 1.5, gaussian, -0.5, 0)
        
        aligned_rgb = sharpened[:, :, ::-1] # Use the sharpened image
        blob = (aligned_rgb.astype(np.float32) / 127.5) - 1.0
        blob = np.expand_dims(blob.transpose(2, 0, 1), axis=0)
        feat = self.engine(blob)[0].flatten()
        norm = np.linalg.norm(feat)
        face.embedding = feat / norm if norm != 0 else feat

class TensorRTFacePipeline:
    def __init__(self, det_engine, rec_engine, cuda_context):
        self.det_model = PureSCRFD(det_engine, cuda_context)
        self.rec_model = PureArcFace(rec_engine, cuda_context)

    def get(self, img):
        faces = self.det_model.detect(img)
        for face in faces:
            self.rec_model.get(img, face)
        return faces

# ==========================================
# ATTENDANCE & LOGIC FUNCTIONS
# ==========================================
def get_today_paths(camera_id):
    """
    Attendance is now completely isolated per camera/source.

    Example:

    attendance_records/
        21-08-2026/
            cam1/
                present/
                absent/
                evidence/
            cam2/
                present/
                absent/
                evidence/
            stream2/
                present/
                absent/
                evidence/
    """

    today_str = datetime.now().strftime('%d-%m-%Y')

    daily_dir = os.path.join(
        ATTENDANCE_ROOT_DIR,
        today_str,
        camera_id
    )

    present_dir = os.path.join(daily_dir, "present")
    absent_dir = os.path.join(daily_dir, "absent")
    evidence_dir = os.path.join(daily_dir, "evidence")

    return present_dir, absent_dir, evidence_dir

def setup_daily_attendance(known_names, camera_ids):
    """
    Create independent attendance state for every camera.
    """

    for camera_id in camera_ids:

        present_dir, absent_dir, evidence_dir = get_today_paths(camera_id)

        os.makedirs(present_dir, exist_ok=True)
        os.makedirs(absent_dir, exist_ok=True)
        os.makedirs(evidence_dir, exist_ok=True)

        for name in set(known_names):

            absent_file = os.path.join(
                absent_dir,
                f"{name}.txt"
            )

            present_file = os.path.join(
                present_dir,
                f"{name}.txt"
            )

            if (
                not os.path.exists(present_file)
                and not os.path.exists(absent_file)
            ):
                with open(absent_file, "w") as f:
                    f.write(
                        f"Created: "
                        f"{datetime.now().strftime('%H:%M:%S')}"
                    )

def mark_attendance(camera_id, user_id, frame_capture):
    """
    Mark attendance independently for each camera.

    Returns:
        True  -> attendance was newly registered
        False -> person was already registered on this camera
    """

    present_dir, absent_dir, evidence_dir = get_today_paths(camera_id)

    os.makedirs(present_dir, exist_ok=True)
    os.makedirs(absent_dir, exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)

    absent_file = os.path.join(
        absent_dir,
        f"{user_id}.txt"
    )

    present_file = os.path.join(
        present_dir,
        f"{user_id}.txt"
    )

    timestamp = datetime.now().strftime('%H-%M-%S')

    proof_path = os.path.join(
        evidence_dir,
        f"{user_id}_{timestamp}.jpg"
    )

    # First detection/registration on this camera.
    if os.path.exists(absent_file):

        shutil.move(absent_file, present_file)

        with open(present_file, 'w') as f:
            f.write(
                f"Present marked at: "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )

        cv2.imwrite(proof_path, frame_capture)

        return True

    # Already registered on this camera.
    elif os.path.exists(present_file):

        return False

    # Fallback if neither file exists.
    else:

        with open(present_file, 'w') as f:
            f.write(
                f"Present marked at: "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )

        cv2.imwrite(proof_path, frame_capture)

        return True

def send_attendance_alert(camera_id, person_name, frame_capture):
    """
    Request an S3 presigned URL from FastAPI and upload
    the attendance evidence directly to S3.

    This is called ONLY after the 10-frame majority succeeds
    AND attendance is newly registered for that camera.
    """

    detected_at = datetime.utcnow().strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:

        # ------------------------------------------
        # 1. Ask FastAPI for presigned URL
        # ------------------------------------------

        data = {
            "camera_id": camera_id,
            "detected_at": detected_at,
            "file_ext": "jpg"
        }

        response = requests.post(
            f"{BASE_URL}/api/ingest/presigned-url",
            json=data,
            timeout=10
        )

        if response.status_code != 200:
            print(
                f"[ALERT] Presigned URL failed "
                f"for {camera_id}/{person_name}: "
                f"{response.status_code} "
                f"{response.text}"
            )
            return False

        result = response.json()

        upload_url = result["upload_url"]
        s3_key = result["s3_key"]

        # ------------------------------------------
        # 2. Encode current frame
        # ------------------------------------------

        success, encoded = cv2.imencode(
            ".jpg",
            frame_capture,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                90
            ]
        )

        if not success:
            print(
                f"[ALERT] JPEG encoding failed "
                f"for {camera_id}/{person_name}"
            )
            return False

        # ------------------------------------------
        # 3. Upload directly to S3
        # ------------------------------------------

        upload_response = requests.put(
            upload_url,
            data=encoded.tobytes(),
            headers={
                "Content-Type": "image/jpeg"
            },
            timeout=30
        )

        if upload_response.status_code not in (200, 201, 204):
            print(
                f"[ALERT] S3 upload failed "
                f"for {camera_id}/{person_name}: "
                f"{upload_response.status_code} "
                f"{upload_response.text}"
            )
            return False

        print(
            f"[ALERT] REGISTERED | "
            f"camera={camera_id} | "
            f"person={person_name} | "
            f"s3={s3_key}"
        )

        return True

    except Exception as e:

        print(
            f"[ALERT] Exception for "
            f"{camera_id}/{person_name}: {e}"
        )

        return False

def send_detection(employee_id, camera_id, confidence):
    detected_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    data = {
        "employee_id": employee_id,
        "camera_id": camera_id,
        "detected_at": detected_at,
        "confidence": float(confidence)
    }

    try:
        response = requests.post(
            DETECTION_API_URL,
            json=data,
            timeout=10
        )

        print(
            f"[DETECTION API] "
            f"{employee_id} | {camera_id} | "
            f"status={response.status_code} | "
            f"{response.text}"
        )

        return response.ok

    except Exception as e:
        print(
            f"[DETECTION API] Failed for "
            f"{employee_id}/{camera_id}: {e}"
        )
        return False


def process_registered_person(camera_id, person_name, frame_capture):
    now = time.time()
    
    # 1. Register attendance locally
    newly_registered = mark_attendance(camera_id, person_name, frame_capture)
    if not newly_registered and ALERT_COOLDOWN_SECONDS is None:
        return False

    key = (camera_id, person_name)
    if key in last_alert_time:
        if ALERT_COOLDOWN_SECONDS is None or (now - last_alert_time[key]) < ALERT_COOLDOWN_SECONDS:
            return False

    # 2. Update last alert time immediately
    last_alert_time[key] = now
    save_alert_state()

    # 3. Offload to ThreadPool instead of a single jammed queue
    queue_attendance_alert(camera_id, person_name, frame_capture.copy())
    
    return True

def load_known_faces(ai_pipeline):
    known_embeddings, known_names = [], []

    EMPLOYEE_ID_MAP = {
        "Ajay_Patel": "GG0001",
        "Fiyanshu_Naydu": "GG0002",
        "Hitesh_Desale": "GG0003",
        "Jatin_Patel": "GG0004",
        "Jaynil_Trivedi": "GG0005",
        "john_doe": "GG0006",
        "Ketan_Gohil": "GG0007",
        "Kiran_Gawale": "GG0008",
        "Laxmi_Choudhary": "GG0009",
        "Lucky_Rao": "GG0010",
        "Manisha_Dubey": "GG0011",
        "Muskan_Singh": "GG0012",
        "Parimal_Sagar": "GG0013",
        "Pushpendra_Patil": "GG0014",
        "Ramesh_Jasoliya": "GG0015",
        "Ramesh_Suthar": "GG0016",
        "Sanjay_Bharwad": "GG0017",
        "Vishal": "GG0020",
        "Vishal_Maurya": "GG0021",
    }

    print(f"Loading users from '{REGISTERED_DIR}'...")
    if not os.path.exists(REGISTERED_DIR): os.makedirs(REGISTERED_DIR)
        
    for entry in os.listdir(REGISTERED_DIR):
        entry_path = os.path.join(REGISTERED_DIR, entry)
        if os.path.isdir(entry_path):
            for filename in os.listdir(entry_path):
                if filename.lower().endswith((".jpg", ".png", ".jpeg", ".bmp", ".pgm")):
                    img = cv2.imread(os.path.join(entry_path, filename))
                    if img is None: continue
                    
                    try:
                        face_img = cv2.resize(img, (112, 112))
                        feat = ai_pipeline.rec_model.get_feat([face_img])
                        if feat and len(feat) > 0:
                            emb = feat[0]
                            norm = np.linalg.norm(emb)

                            # known_embeddings.append(emb / norm if norm != 0 else emb)
                            # known_names.append(entry)

                            known_embeddings.append(emb / norm if norm != 0 else emb)

                            for name, employee_id in EMPLOYEE_ID_MAP.items():
                                if entry.startswith(name + "_") or entry == name:
                                    known_names.append(employee_id)
                                    break
                            else:
                                print(f"WARNING: No employee ID mapping for folder: {entry}")

                    except Exception as e:
                        print(f"Error loading {filename}: {e}")

    print(f"Loaded {len(known_embeddings)} face embeddings for {len(set(known_names))} unique users.")
    return known_embeddings, known_names

# ==========================================
# DEEPSTREAM PIPELINE LOGIC
# ==========================================

global ai_pipeline, feature_bank, known_names
global last_fps_time, frame_fps_counter, current_fps_val

last_fps_time = time.time()
frame_fps_counter = 0
current_fps_val = 0.0


def bbox_center(bbox):
    x1, y1, x2, y2 = bbox

    return (
        (x1 + x2) / 2.0,
        (y1 + y2) / 2.0
    )


def bbox_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)

    intersection = inter_w * inter_h

    area1 = max(
        0.0,
        box1[2] - box1[0]
    ) * max(
        0.0,
        box1[3] - box1[1]
    )

    area2 = max(
        0.0,
        box2[2] - box2[0]
    ) * max(
        0.0,
        box2[3] - box2[1]
    )

    union = area1 + area2 - intersection

    if union <= 0:
        return 0.0

    return intersection / union


def get_face_track_id(camera_id, bbox):
    """
    Simple per-camera face tracker.

    It matches the current detection against the previous
    detections using IoU and center distance.

    Each camera has its own independent track IDs.
    """

    if camera_id not in face_tracks:
        face_tracks[camera_id] = {}

    tracks = face_tracks[camera_id]

    current_center = bbox_center(bbox)

    best_track = None
    best_score = 0.0

    for track_id, track in tracks.items():

        old_bbox = track["bbox"]

        iou = bbox_iou(
            bbox,
            old_bbox
        )

        old_center = track["center"]

        distance = math.sqrt(
            (current_center[0] - old_center[0]) ** 2 +
            (current_center[1] - old_center[1]) ** 2
        )

        # Combined score.
        if iou > 0.05:
            score = iou

            if distance < 250:
                score += 0.2

            if score > best_score:
                best_score = score
                best_track = track_id

    if best_track is None:

        best_track = (
            f"{camera_id}_face_"
            f"{len(tracks)}"
        )

        tracks[best_track] = {
            "bbox": bbox.copy(),
            "center": current_center,
            "last_seen": time.time()
        }

    else:

        tracks[best_track]["bbox"] = bbox.copy()
        tracks[best_track]["center"] = current_center
        tracks[best_track]["last_seen"] = time.time()

    return best_track


def cleanup_face_tracks(camera_id, max_age=2.0):

    if camera_id not in face_tracks:
        return

    now = time.time()

    dead_tracks = []

    for track_id, track in face_tracks[camera_id].items():

        if now - track["last_seen"] > max_age:
            dead_tracks.append(track_id)

    for track_id in dead_tracks:

        del face_tracks[camera_id][track_id]

        match_history.pop(
            (camera_id, track_id),
            None
        )


def tiler_sink_pad_buffer_probe(pad, info, u_data):
    global last_fps_time, frame_fps_counter, current_fps_val
    gst_buffer = info.get_buffer()
    if not gst_buffer: return Gst.PadProbeReturn.OK

    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    l_frame = batch_meta.frame_meta_list

    frame_fps_counter += 1
    t_now = time.time()
    if (t_now - last_fps_time) >= 1.0:
        current_fps_val = frame_fps_counter / (t_now - last_fps_time)
        frame_fps_counter = 0
        last_fps_time = t_now

    while l_frame is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            source_index = frame_meta.pad_index

            # camera_id = f"cam{source_index + 1}"
            camera_id = get_camera_id(
                        source_index,
                        source_uris[source_index]
                    )


        except StopIteration:
            break


        n_frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)

        frame_copy = np.array(n_frame, copy=True, order='C')
        frame_bgr = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGR)

        t_ai_start = time.time()
        faces = ai_pipeline.get(frame_bgr)

        ai_latency = (time.time() - t_ai_start) * 1000
        current_frame_names = set()

        for face in faces:
            
            # DEFAULT EXTENSIONS FOR UNKNOWN
            name, text = "Unknown", "Unknown"
            color = (1.0, 0.0, 0.0, 1.0) # Pure Red
            
            if len(feature_bank) > 0:
                sims = np.dot(feature_bank, face.embedding)
                max_idx = np.argmax(sims)
                max_score = sims[max_idx]
                
                # if max_score > CONFIDENCE_THRESHOLD:
                #     name = known_names[max_idx]
                #     current_frame_names.add(name)
                    
                #     if name not in presence_tracker:
                #         presence_tracker[name] = time.time()
                #         text = "Verifying..."
                #         color = (1.0, 1.0, 0.0, 1.0) # Yellow
                #     else:
                #         elapsed = time.time() - presence_tracker[name]
                #         if elapsed >= REQUIRED_DURATION:
                #             mark_attendance(name, frame_bgr)
                #             text = f"{name} ({int(max_score*100)}%)" # Correct matching string structure
                #             color = (0.0, 1.0, 0.0, 1.0) # Pure Green
                #         else:
                #             text = f"{name} {elapsed:.1f}s"

                # Track prediction history per face
                # history_key = id(face)

                # if history_key not in match_history:
                #     match_history[history_key] = []

                # if max_score > CONFIDENCE_THRESHOLD:
                #     match_history[history_key].append((known_names[max_idx], max_score))
                # else:
                #     match_history[history_key].append(("Unknown", max_score))

                # # Keep only latest 10 frames
                # match_history[history_key] = match_history[history_key][-MATCH_HISTORY_SIZE:]


                # ------------------------------------------
                # CAMERA-SPECIFIC FACE TRACK
                # ------------------------------------------

                track_id = get_face_track_id(
                    camera_id,
                    face.bbox
                )

                history_key = (camera_id, track_id)

                if history_key not in match_history:
                    match_history[history_key] = deque(
                        maxlen=MATCH_HISTORY_SIZE
                    )

                # ------------------------------------------
                # Add current recognition result
                # ------------------------------------------

                if max_score > CONFIDENCE_THRESHOLD:

                    match_history[history_key].append(
                        (
                            known_names[max_idx],
                            float(max_score)
                        )
                    )

                else:

                    match_history[history_key].append(
                        (
                            "Unknown",
                            float(max_score)
                        )
                    )

                # ------------------------------------------
                # 10-FRAME MAJORITY
                # ------------------------------------------

                if len(match_history[history_key]) >= MATCH_HISTORY_SIZE:

                    votes = [
                        n
                        for n, score in match_history[history_key]
                        if n != "Unknown"
                    ]

                    if votes:

                        voted_name, vote_count = Counter(
                            votes
                        ).most_common(1)[0]

                        # Require 6/10 or better.
                        if vote_count >= MATCH_MAJORITY:

                            name = voted_name

                            current_frame_names.add(name)

                            matching_scores = [
                                score
                                for n, score in match_history[history_key]
                                if n == voted_name
                            ]

                            avg_score = float(
                                np.mean(matching_scores)
                            )

                            # ------------------------------------------
                            # CAMERA-SPECIFIC ATTENDANCE
                            # ------------------------------------------

                            presence_key = (camera_id, name)

                            if presence_key not in presence_tracker:
                                presence_tracker[presence_key] = time.time()

                            # if name not in presence_tracker:

                            #     presence_tracker[name] = time.time()

                                text = "Verifying..."
                                color = (
                                    1.0,
                                    1.0,
                                    0.0,
                                    1.0
                                )

                            else:

                                # elapsed = (
                                #     time.time()
                                #     - presence_tracker[name]
                                # )

                                presence_key = (camera_id, name)

                                elapsed = time.time() - presence_tracker[presence_key]


                                if elapsed >= REQUIRED_DURATION:

                                    annotated_frame = frame_bgr.copy()
                                    x1, y1, x2, y2 = map(int, face.bbox)
                                    
                                    # Draw green bounding box around face
                                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                    
                                    # Optional: Add text label above box
                                    label = f"{name} ({int(avg_score * 100)}%)"
                                    cv2.putText(annotated_frame, label, (x1, max(y1 - 10, 15)), 
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                                    # ----------------------------------
                                    # REGISTER + ALERT
                                    # ----------------------------------

                                    # employee_id = EMPLOYEE_ID_MAP.get(name, name)
                                    
                                    # employee_id = u_data.get(name, name)

                                    employee_id = name

                                    # send_detection(
                                    #     employee_id=employee_id,
                                    #     camera_id=camera_id,
                                    #     confidence=avg_score
                                    # )


                                    # detection_pool.submit(
                                    #     send_detection,
                                    #     employee_id,
                                    #     camera_id,
                                    #     avg_score
                                    # )

                                    detection_key = (camera_id, employee_id)
                                    now = time.time()

                                    if now - last_detection_sent.get(detection_key, 0) >= 60:
                                        last_detection_sent[detection_key] = now

                                        detection_pool.submit(
                                            send_detection,
                                            employee_id,
                                            camera_id,
                                            avg_score
                                        )

                                    alert_sent = process_registered_person(
                                        camera_id,
                                        name,
                                        annotated_frame # frame_bgr
                                    )

                                    

                                    text = (
                                        f"{name} "
                                        f"({int(avg_score * 100)}%)"
                                    )

                                    color = (
                                        0.0,
                                        1.0,
                                        0.0,
                                        1.0
                                    )

                                    if alert_sent:

                                        print(
                                            f"NEW ATTENDANCE ALERT: "
                                            f"{camera_id} -> {name}"
                                        )

                                else:

                                    text = (
                                        f"{name} "
                                        f"{elapsed:.1f}s"
                                    )

                # # ------------------------------------------
                # # 10-frame voting logic
                # # ------------------------------------------
                # if len(match_history[history_key]) >= MATCH_HISTORY_SIZE:
                #     votes = [
                #         n for n, score in match_history[history_key] if n != "Unknown"
                #     ]

                #     if votes:
                #         voted_name, vote_count = Counter(votes).most_common(1)[0]

                #         # Require majority: at least 6/10 frames
                #         if vote_count >= 6:
                #             name = voted_name
                #             current_frame_names.add(name)

                #             # Calculate average similarity score for the voted person
                #             matching_scores = [
                #                 score
                #                 for n, score in match_history[history_key]
                #                 if n == voted_name
                #             ]
                #             avg_score = np.mean(matching_scores)

                #             if name not in presence_tracker:
                #                 presence_tracker[name] = time.time()
                #                 text = "Verifying..."
                #                 color = (1.0, 1.0, 0.0, 1.0)  # Yellow
                #             else:
                #                 elapsed = time.time() - presence_tracker[name]
                #                 if elapsed >= REQUIRED_DURATION:
                #                     mark_attendance(name, frame_bgr)
                #                     text = f"{name} ({int(avg_score * 100)}%)"
                #                     color = (0.0, 1.0, 0.0, 1.0)  # Pure Green
                #                 else:
                #                     text = f"{name} {elapsed:.1f}s"
            
            obj_meta = pyds.nvds_acquire_obj_meta_from_pool(batch_meta)
            obj_meta.class_id = 0
            obj_meta.confidence = face.det_score
            
            rect = obj_meta.rect_params
            rect.left, rect.top = float(face.bbox[0]), float(face.bbox[1])
            rect.width = float(face.bbox[2] - face.bbox[0])
            rect.height = float(face.bbox[3] - face.bbox[1])
            rect.border_width = 3
            rect.border_color.set(color[0], color[1], color[2], color[3])
            
            txt = obj_meta.text_params
            txt.display_text = text
            txt.font_params.font_name = "Serif"
            txt.font_params.font_size = 12
            txt.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
            txt.set_bg_clr = 1
            txt.text_bg_clr.set(0.0, 0.0, 0.0, 1.0)

            # Text coordinates matched to bounding box coordinates as integers
            txt.x_offset = int(rect.left)
            txt.y_offset = max(0, int(rect.top) - 50)
            
            pyds.nvds_add_obj_meta_to_frame(frame_meta, obj_meta, None)

        # for tracked in list(presence_tracker.keys()):
        #     if tracked not in current_frame_names: del presence_tracker[tracked]

        current_presence_keys = {
            (camera_id, name)
            for name in current_frame_names
        }

        for tracked in list(presence_tracker.keys()):

            tracked_camera, tracked_name = tracked

            if (
                tracked_camera == camera_id
                and tracked not in current_presence_keys
            ):
                del presence_tracker[tracked]

        # ---------------------------------------------------------
        # DISPLAY METADATA INJECTION (FIXED FLAT API STRUCTURE)
        # ---------------------------------------------------------
        display_meta = pyds.nvds_acquire_display_meta_from_pool(batch_meta)
        display_meta.num_labels = 2
        
        # Indicator 1: Display FPS Flat Assignment Configuration
        txt_fps = display_meta.text_params[0]
        txt_fps.display_text = f"Display FPS: {int(current_fps_val)}"
        txt_fps.x_offset = 30
        txt_fps.y_offset = 40
        txt_fps.font_params.font_name = "Arial"
        txt_fps.font_params.font_size = 22
        txt_fps.font_params.font_color.set(1.0, 1.0, 0.0, 1.0) # Yellow Text
        txt_fps.set_bg_clr = 0

        # Indicator 2: GPU AI Latency Flat Assignment Configuration
        txt_lat = display_meta.text_params[1]
        txt_lat.display_text = f"GPU AI Latency: {ai_latency:.1f} ms"
        txt_lat.x_offset = 30
        txt_lat.y_offset = 80
        txt_lat.font_params.font_name = "Arial"
        txt_lat.font_params.font_size = 22
        txt_lat.font_params.font_color.set(0.0, 1.0, 0.0, 1.0) # Green Text
        txt_lat.set_bg_clr = 0

        pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)

        stream_index = "stream{0}".format(frame_meta.pad_index)
        global perf_data
        perf_data.update_fps(stream_index)
        
        if platform_info.is_integrated_gpu():
            pyds.unmap_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK


def decodebin_child_added(child_proxy, Object, name, user_data):
    """
    Configure decoder elements used by FILE/uridecodebin sources.

    RTSP configuration is intentionally NOT done here because
    RTSP sources use nvurisrcbin.
    """

    try:

        if "decodebin" in name:

            Object.connect(
                "child-added",
                decodebin_child_added,
                user_data
            )

        if (
            not platform_info.is_integrated_gpu()
            and "nvv4l2decoder" in name
        ):

            if Object.find_property(
                "cudadec-memtype"
            ) is not None:

                Object.set_property(
                    "cudadec-memtype",
                    2
                )

    except Exception as e:

        print(
            f"[FILE] decodebin_child_added error "
            f"for {name}: {e}"
        )

def create_source_bin(index, uri):
    """
    Create a source for one input.

    RTSP:
        nvurisrcbin is used directly. Its video output is dynamic and is
        linked to nvstreammux by rtsp_nvurisrcbin_pad_added().

    FILE:
        uridecodebin is retained. Its decoder output is attached to a
        source-bin ghost pad by cb_newpad().
    """

    bin_name = f"source-bin-{index:02d}"
    is_rtsp = uri.lower().startswith("rtsp://")

    source_is_rtsp[index] = is_rtsp
    source_finished[index] = False
    source_uris[index] = uri

    # --------------------------------------------------
    # RTSP -> nvurisrcbin
    # --------------------------------------------------

    if is_rtsp:

        source = Gst.ElementFactory.make(
            "nvurisrcbin",
            bin_name
        )

        if source is None:
            raise RuntimeError(
                f"Could not create nvurisrcbin for {bin_name}"
            )

        source.set_property("uri", uri)

        if source.find_property("source-id") is not None:
            source.set_property("source-id", index)

        if source.find_property("select-rtp-protocol") is not None:
            source.set_property("select-rtp-protocol", 4)

        if source.find_property("latency") is not None:
            source.set_property("latency", RTSP_LATENCY_MS)

        if source.find_property("rtsp-reconnect-interval") is not None:
            source.set_property(
                "rtsp-reconnect-interval",
                RTSP_RECONNECT_INTERVAL_SEC
            )

        if source.find_property("init-rtsp-reconnect-interval") is not None:
            source.set_property(
                "init-rtsp-reconnect-interval",
                RTSP_RECONNECT_INTERVAL_SEC
            )

        if source.find_property("rtsp-reconnect-attempts") is not None:
            source.set_property(
                "rtsp-reconnect-attempts",
                RTSP_RECONNECT_ATTEMPTS
            )

        if source.find_property("disable-audio") is not None:
            source.set_property("disable-audio", True)

        if source.find_property("drop-pipeline-eos") is not None:
            source.set_property("drop-pipeline-eos", True)

        print(f"[SOURCE {index}] RTSP -> nvurisrcbin")
        print(f"[RTSP {index}] URI: {uri}")
        print(
            f"[RTSP {index}] TCP transport, "
            f"latency={RTSP_LATENCY_MS} ms, "
            f"reconnect={RTSP_RECONNECT_INTERVAL_SEC}s, "
            f"attempts={RTSP_RECONNECT_ATTEMPTS}"
        )

        return source

    # --------------------------------------------------
    # FILE -> uridecodebin
    # --------------------------------------------------

    source_bin = Gst.Bin.new(bin_name)

    if source_bin is None:
        raise RuntimeError(
            f"Could not create {bin_name}"
        )

    uri_decode_bin = Gst.ElementFactory.make(
        "uridecodebin",
        "uri-decode-bin"
    )

    if uri_decode_bin is None:
        raise RuntimeError(
            "Could not create uridecodebin"
        )

    uri_decode_bin.set_property(
        "uri",
        uri
    )

    uri_decode_bin.connect(
        "pad-added",
        cb_newpad,
        source_bin
    )

    uri_decode_bin.connect(
        "child-added",
        decodebin_child_added,
        source_bin
    )

    source_bin.add(
        uri_decode_bin
    )

    ghost_pad = Gst.GhostPad.new_no_target(
        "src",
        Gst.PadDirection.SRC
    )

    if ghost_pad is None:
        raise RuntimeError(
            f"Could not create ghost pad for {bin_name}"
        )

    source_bin.add_pad(ghost_pad)

    source_bins[index] = source_bin
    source_uris[index] = uri

    print(f"[SOURCE {index}] FILE -> uridecodebin")

    return source_bin


def cb_newpad(decodebin, decoder_src_pad, data):
    """
    Called whenever uridecodebin creates a new source pad.

    When an RTSP camera reconnects, a new decoder/source pad
    is created and this function attaches it to the source-bin
    ghost pad.
    """

    try:
        caps = decoder_src_pad.get_current_caps()

        if caps is None:
            caps = decoder_src_pad.query_caps(None)

        if caps is None or caps.get_size() == 0:
            return

        structure = caps.get_structure(0)
        media_type = structure.get_name()

        if media_type.startswith("video"):

            # We only want NVIDIA NVMM video buffers.
            if caps.get_features(0).contains("memory:NVMM"):

                bin_ghost_pad = data.get_static_pad("src")

                if bin_ghost_pad is not None:

                    # Replace previous target if necessary.
                    try:
                        bin_ghost_pad.set_target(None)
                    except Exception:
                        pass

                    bin_ghost_pad.set_target(decoder_src_pad)

                    print(
                        f"[RTSP] Video pad connected: "
                        f"{data.get_name()}"
                    )

    except Exception as e:
        print(f"[RTSP] cb_newpad error: {e}")

def rtsp_nvurisrcbin_pad_added(element, src_pad, sink_pad):
    """
    RTSP-only callback. nvurisrcbin creates its video output
    dynamically; link that pad directly to its nvstreammux sink.
    """

    try:
        caps = src_pad.get_current_caps()
        if caps is None:
            caps = src_pad.query_caps(None)

        if caps is None or caps.get_size() == 0:
            return

        media_type = caps.get_structure(0).get_name()
        if not media_type.startswith("video"):
            return

        if sink_pad.is_linked():
            return

        result = src_pad.link(sink_pad)

        if result == Gst.PadLinkReturn.OK:
            print(
                f"[RTSP] Video pad connected: "
                f"{element.get_name()} -> {sink_pad.get_name()}"
            )
        else:
            print(
                f"[RTSP] Failed to link video pad: "
                f"{element.get_name()} -> {sink_pad.get_name()}: {result}"
            )

    except Exception as e:
        print(
            f"[RTSP] nvurisrcbin pad-added error for "
            f"{element.get_name()}: {e}"
        )


def get_source_bin_from_message(message):
    """
    Walk up the GStreamer object hierarchy until
    source-bin-XX is found.
    """

    try:

        element = message.src

        while element is not None:

            name = element.get_name()

            if name.startswith("source-bin-"):
                return element

            element = element.get_parent()

    except Exception:
        pass

    return None


def on_pipeline_message(bus, message, loop):
    """
    Handle pipeline/source messages without destroying RTSP sources.

    RTSP:
        nvurisrcbin owns reconnect handling, so source ERROR/EOS/timeout
        messages are logged and left alive.

    FILE:
        Mark the individual file source finished.

    Pipeline EOS:
        Quit the main loop.
    """

    try:
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:

            error, debug = message.parse_error()

            source_bin = get_source_bin_from_message(message)

            if source_bin is not None:

                source_name = source_bin.get_name()

                try:
                    index = int(source_name.split("-")[-1])
                except Exception:
                    index = None

                if index is not None:

                    if source_is_rtsp.get(index, False):

                        print(
                            f"[RTSP ERROR {index}] {error}"
                        )

                        if debug:
                            print(
                                f"[RTSP DEBUG {index}] {debug}"
                            )

                        print(
                            f"[RTSP {index}] "
                            f"Leaving nvurisrcbin alive; "
                            f"its reconnect logic remains active."
                        )

                        return

                    source_finished[index] = True

                    print(
                        f"[FILE ERROR {index}] {error}"
                    )

                    if debug:
                        print(
                            f"[FILE DEBUG {index}] {debug}"
                        )

                    return

            print(f"[GSTREAMER ERROR] {error}")

            if debug:
                print(f"[GSTREAMER DEBUG] {debug}")

            return

        if msg_type == Gst.MessageType.EOS:

            source_bin = get_source_bin_from_message(message)

            if source_bin is not None:

                source_name = source_bin.get_name()

                try:
                    index = int(source_name.split("-")[-1])
                except Exception:
                    index = None

                if index is not None:

                    if source_is_rtsp.get(index, False):

                        print(
                            f"[RTSP EOS {index}] "
                            f"Leaving nvurisrcbin alive for reconnect."
                        )

                        return

                    source_finished[index] = True

                    print(
                        f"[FILE EOS {index}] "
                        f"Source finished normally."
                    )

                    return

            print("[PIPELINE] EOS received.")
            loop.quit()
            return

        if msg_type == Gst.MessageType.ELEMENT:

            structure = message.get_structure()

            if structure is None:
                return

            if structure.get_name() == "GstRTSPSrcTimeout":

                source_bin = get_source_bin_from_message(message)

                if source_bin is not None:

                    source_name = source_bin.get_name()

                    try:
                        index = int(source_name.split("-")[-1])
                    except Exception:
                        index = None

                    if (
                        index is not None
                        and source_is_rtsp.get(index, False)
                    ):

                        print(
                            f"[RTSP TIMEOUT {index}] "
                            f"nvurisrcbin will handle reconnect."
                        )

                return

    except Exception as e:

        print(f"[BUS HANDLER ERROR] {e}")


def main(args):
    global perf_data, platform_info, ai_pipeline, feature_bank, known_names, cuda_context
    
    if len(args) < 2:
        sys.stderr.write("usage: %s <uri1> [uri2] ... [uriN]\n" % args[0])
        sys.exit(1)

    cuda.init()
    cuda_device = cuda.Device(0)
    cuda_context = cuda_device.make_context()

    print("Initializing Native TensorRT AI Pipeline...")
    ai_pipeline = TensorRTFacePipeline(DET_ENGINE_PATH, REC_ENGINE_PATH, cuda_context)
    
    emb, nms = load_known_faces(ai_pipeline)
    
    cuda_context.push()
    feature_bank = np.array(emb) if emb else np.empty((0, 512))
    cuda_context.pop()
    
    # known_names = nms
    # setup_daily_attendance(known_names)


    known_names = nms

    # known_names = nms

    # EMPLOYEE_ID_MAP = {
    #     "GG0013": "GG0013",
    #     "GG0021": "GG0021",
    #     "GG0005": "GG0005",
    # }

    EMPLOYEE_ID_MAP = {
            "Ajay_Patel": "GG0001",
            "Fiyanshu_Naydu": "GG0002",
            "Hitesh_Desale": "GG0003",
            "Jatin_Patel": "GG0004",
            "Jaynil_Trivedi": "GG0005",
            "john_doe": "GG0006",
            "Ketan_Gohil": "GG0007",
            "Kiran_Gawale": "GG0008",
            "Laxmi_Choudhary": "GG0009",
            "Lucky_Rao": "GG0010",
            "Manisha_Dubey": "GG0011",
            "Muskan_Singh": "GG0012",
            "Parimal_Sagar": "GG0013",
            "Pushpendra_Patil": "GG0014",
            "Ramesh_Jasoliya": "GG0015",
            "Ramesh_Suthar": "GG0016",
            "Sanjay_Bharwad": "GG0017",
            "Vishal": "GG0020",
            "Vishal_Maurya": "GG0021",
        }

    camera_ids = [
        get_camera_id(i, args[i + 1]) # f"cam{i + 1}"
        for i in range(len(args) - 1)
    ]

    setup_daily_attendance(
        known_names,
        camera_ids
    )

    load_alert_state()


    number_sources = len(args) - 1
    perf_data = PERF_DATA(number_sources)
    platform_info = PlatformInfo()
    Gst.init(None)

    pipeline = Gst.Pipeline()
    is_live = False
    
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    pipeline.add(streammux)


    for i in range(number_sources):

        uri_name = args[i + 1]

        if uri_name.lower().startswith("rtsp://"):
            is_live = True

        source_bin = create_source_bin(i, uri_name)
        pipeline.add(source_bin)

        sink_pad = streammux.request_pad_simple(f"sink_{i}")

        if sink_pad is None:
            raise RuntimeError(
                f"Could not request nvstreammux sink_{i}"
            )

        source_mux_pads[i] = sink_pad

        # RTSP: dynamic nvurisrcbin video pad -> mux sink.
        if source_is_rtsp.get(i, False):

            source_bin.connect(
                "pad-added",
                rtsp_nvurisrcbin_pad_added,
                sink_pad
            )

            print(
                f"[RTSP {i}] Waiting for dynamic nvurisrcbin "
                f"video pad -> nvstreammux sink_{i}"
            )

        # FILE: uridecodebin -> source-bin ghost src -> mux sink.
        else:

            src_pad = source_bin.get_static_pad("src")

            if src_pad is None:
                raise RuntimeError(
                    f"Could not get FILE source-bin ghost "
                    f"src pad for source {i}"
                )

            result = src_pad.link(sink_pad)

            if result != Gst.PadLinkReturn.OK:
                raise RuntimeError(
                    f"Failed to link FILE source {i} "
                    f"to nvstreammux sink_{i}: {result}"
                )

            print(
                f"[FILE {i}] Source-bin ghost pad linked "
                f"to nvstreammux sink_{i}"
            )

    nvvidconv1 = Gst.ElementFactory.make("nvvideoconvert", "convertor1")
    caps1 = Gst.Caps.from_string("video/x-raw(memory:NVMM), format=RGBA")
    filter1 = Gst.ElementFactory.make("capsfilter", "filter1")
    filter1.set_property("caps", caps1)
    
    tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")

    sink = Gst.ElementFactory.make("fakesink", "fakesink")
    if not sink:
        sys.stderr.write("Unable to create fakesink\n"); return False

    streammux.set_property('live-source', 1)
    streammux.set_property('width', MUXER_OUTPUT_WIDTH)
    streammux.set_property('height', MUXER_OUTPUT_HEIGHT)
    streammux.set_property("batch-size", number_sources)
    streammux.set_property('batched-push-timeout', MUXER_BATCH_TIMEOUT_USEC)
    streammux.set_property("sync-inputs", 0)
    
    tiler_rows = int(math.sqrt(number_sources))
    tiler.set_property("rows", tiler_rows)
    tiler.set_property("columns", int(math.ceil((1.0 * number_sources) / tiler_rows)))
    tiler.set_property("width", TILED_OUTPUT_WIDTH)
    tiler.set_property("height", TILED_OUTPUT_HEIGHT)

    mem_type = int(pyds.NVBUF_MEM_CUDA_UNIFIED)
    streammux.set_property("nvbuf-memory-type", mem_type)
    nvvidconv.set_property("nvbuf-memory-type", mem_type)
    tiler.set_property("nvbuf-memory-type", mem_type)
    
    if platform_info.is_integrated_gpu():
        nvvidconv1.set_property("nvbuf-memory-type", 4)
    else:
        nvvidconv1.set_property("nvbuf-memory-type", mem_type)

    sink.set_property("sync", 0)
    sink.set_property("qos", 0)

    pipeline.add(nvvidconv1)
    pipeline.add(filter1)
    pipeline.add(tiler)
    pipeline.add(nvvidconv)
    pipeline.add(sink)

    streammux.link(nvvidconv1)

    nvvidconv1.link(filter1)
    filter1.link(tiler)
    tiler.link(nvvidconv)
    nvvidconv.link(sink)   

    loop = GLib.MainLoop()

    bus = pipeline.get_bus()
    bus.add_signal_watch()

    bus.connect(
        "message",
        on_pipeline_message,
        loop
    )

    tiler_sink_pad = tiler.get_static_pad("sink")
    # tiler_sink_pad.add_probe(Gst.PadProbeType.BUFFER, tiler_sink_pad_buffer_probe, 0)
    tiler_sink_pad.add_probe(Gst.PadProbeType.BUFFER, tiler_sink_pad_buffer_probe, EMPLOYEE_ID_MAP)
    GLib.timeout_add(5000, perf_data.perf_print_callback)

    


    print("Starting DeepStream hardware pipeline...\n")

    pipeline.set_state(
        Gst.State.PLAYING
    )

    try:

        loop.run()

    except KeyboardInterrupt:

        print(
            "\n[PIPELINE] Ctrl+C received. "
            "Stopping..."
        )

    finally:

        print(
            "[PIPELINE] Setting pipeline to NULL..."
        )

        pipeline.set_state(
            Gst.State.NULL
        )

        # Give GStreamer time to finish cleanup.
        pipeline.get_state(
            Gst.CLOCK_TIME_NONE
        )

        try:
            cuda_context.pop()
        except Exception:
            pass

        try:
            cuda_context.detach()
        except Exception:
            pass

        print(
            "Pipeline exited cleanly."
        )
    

if __name__ == '__main__':
    sys.exit(main(sys.argv))
