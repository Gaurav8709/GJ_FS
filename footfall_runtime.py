#!/usr/bin/env python3
"""
footfall_runtime.py  -  24/7 DeepStream footfall + heatmap + age/gender
=========================================================================

Pipeline
    nvurisrcbin (N cameras, add/remove at runtime, RTSP over TCP, auto-reconnect)
      -> nvstreammux -> PeopleNet (person + face) -> NvDCF tracker
      -> nvvideoconvert (RGBA) -> [probe] -> fakesink  (or tiled display)

In the probe (pure Python, per camera, fully runtime-configurable):
    * ROI occupancy          (ROIs read from your config_nvdsanalytics_camX.txt)
    * Entry / exit counting  (line-crossing lines from the same files, or JSON)
    * Age / gender           (PeopleNet face -> matched to person track ->
                              InsightFace genderage.onnx, voted over samples)
    * Hourly heatmap         (person-seconds at foot position, uploaded hourly)

Backend
    POST {BACKEND_URL}/api/footfall/listener-update   every FOOTFALL_REPORT_SEC
    POST {BACKEND_URL}/api/heatmaps/upload            every hour, per camera

Cameras
    footfall_cameras.json (auto-created on first run). Edit it while running:
    add / remove / disable cameras or change ROIs and lines; changes apply
    within ~2 s. Interactive commands (when run in a terminal):
        status | add <cam> [rtsp_uri] | del <cam> | reload | quit

Why not nvdsanalytics?
    nvdsanalytics loads its per-stream ROI/line config once at startup, keyed by
    stream index, so a camera added at runtime into a new slot gets no ROI or
    lines. Doing the geometry here keeps everything per camera and hot-reloadable.

Run
    python3 footfall_runtime.py
    FOOTFALL_DISPLAY=1 python3 footfall_runtime.py        # with tiled window
"""

import os
import sys
import re
import json
import time
import queue
import signal
import threading
import platform
import traceback
import ctypes
import glob
import uuid
import urllib.request
import urllib.error
import configparser
from datetime import datetime, timedelta

import numpy as np
import cv2
import requests

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst
import pyds


# =============================================================================
# CONFIGURATION  (env overridable)
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

BACKEND_URL = os.environ.get("BACKEND_URL", "http://65.2.158.148").rstrip("/")
FOOTFALL_URL = BACKEND_URL + "/api/footfall/listener-update"
HEATMAP_URL = BACKEND_URL + "/api/heatmaps/upload"

CAMERAS_JSON = os.environ.get("FOOTFALL_CAMERAS_JSON", "footfall_cameras.json")
STATE_FILE = os.environ.get("FOOTFALL_STATE_FILE", "footfall_state.json")
HEATMAP_DIR = os.environ.get("FOOTFALL_HEATMAP_DIR", "heatmaps")

PGIE_BASE_CONFIG = "dsnvanalytics_pgie_config.txt"
PGIE_RUNTIME_CONFIG = "pgie_footfall_runtime.txt"

# ---- genderage as TGIE (nvinfer on PeopleNet faces) ----
TGIE_BASE_CONFIG = "config_infer_tertiary_genderage.txt"
TGIE_RUNTIME_CONFIG = "tgie_genderage_runtime.txt"
TGIE_UID = 3
FACE_EXPAND = 1.5          # InsightFace crops 1.5 x max(w,h) square around the face
TRACKER_CONFIG_FILE = "dsnvanalytics_tracker_config.txt"

GENDERAGE_MODEL_CANDIDATES = [
    os.environ.get("GENDERAGE_MODEL", ""),
    "models/genderage.onnx",
    "genderage.onnx",
    os.path.expanduser("~/.insightface/models/buffalo_l/genderage.onnx"),
]
AG_USE_CUDA = os.environ.get("AG_USE_CUDA", "0") == "1"

MAX_SOURCES = max(1, min(32, int(os.environ.get("FOOTFALL_MAX_SOURCES", "16"))))  # engine max = 32
MUX_W, MUX_H = 1920, 1080
MUX_TIMEOUT_USEC = 40000
GPU_ID = 0
DISPLAY = os.environ.get("FOOTFALL_DISPLAY", "0") == "1"
IS_JETSON = platform.machine() == "aarch64"

RTSP_LATENCY_MS = int(os.environ.get("RTSP_LATENCY_MS", "2000"))
RTSP_RECONNECT_SEC = int(os.environ.get("RTSP_RECONNECT_SEC", "30"))

CLASS_PERSON = 0
CLASS_FACE = 2

# ---- age / gender ----
FACE_PGIE_THRESHOLD = 0.30     # enables PeopleNet face class (was 1.01 = off)
FACE_MIN_CONF = 0.35
FACE_MIN_PX = 24               # min face side in 1920x1080 frame
AG_MIN_SAMPLES = 3             # samples needed to fix age/gender for a track
AG_MAX_ATTEMPTS = 12
AG_SAMPLE_INTERVAL_SEC = 0.4
AGE_BUCKETS = [("0_9", 0, 9), ("10_17", 10, 17), ("18_25", 18, 25),
               ("26_35", 26, 35), ("36_50", 36, 50), ("50_plus", 51, 200)]

# ---- entry / exit ----
LINE_HYST_PX = 8               # foot point must be this far from the line to count a side
LINE_SEGMENT_MARGIN = 0.10     # crossing must happen within the segment (+-10%)
LINE_EVENT_COOLDOWN_SEC = 1.5
TRACK_TTL_SEC = 5.0

# ---- reporting ----
FOOTFALL_REPORT_SEC = int(os.environ.get("FOOTFALL_REPORT_SEC", "60"))
STATUS_PRINT_SEC = 30

# ---- heatmap ----
HEAT_GW, HEAT_GH = 192, 108
HEAT_SIGMA = 2.5
HEAT_TOP_FRACTION = 0.10       # peak_density = share of dwell in hottest 10% of area
HEATMAP_UPLOAD_EMPTY = os.environ.get("HEATMAP_UPLOAD_EMPTY", "0") == "1"
HEAT_BG_W, HEAT_BG_H = 960, 540

# ---- 24/7 ----
STALL_RESTART_SEC = 90         # restart a camera if no frames for this long

DEFAULT_CAMERAS = {
    "backend_url": BACKEND_URL,
    "coord_width": 1920,
    "coord_height": 1080,
    "cameras": {
        "cam2":  {"enabled": False, "uri": "rtsp://65.1.214.31:8554/gj/cam2",  "analytics": "config_nvdsanalytics_cam2.txt"},
        "cam4":  {"enabled": False, "uri": "rtsp://65.1.214.31:8554/gj/cam4",  "analytics": "config_nvdsanalytics_cam4.txt"},
        "cam5":  {"enabled": True,  "uri": "rtsp://65.1.214.31:8554/gj/cam5",  "analytics": "config_nvdsanalytics_cam5.txt"},
        "cam5b": {"enabled": False, "uri": "rtsp://65.1.214.31:8554/gj/cam5b", "analytics": "config_nvdsanalytics_cam5b.txt"},
        "cam6":  {"enabled": True,  "uri": "rtsp://65.1.214.31:8554/gj/cam6",  "analytics": "config_nvdsanalytics_cam6.txt"},
        "cam12": {"enabled": True,  "uri": "rtsp://65.1.214.31:8554/gj/cam12", "analytics": "config_nvdsanalytics_cam12.txt",
                  "inside_point": None},
        "cam13": {"enabled": True,  "uri": "rtsp://65.1.214.31:8554/gj/cam13", "analytics": "config_nvdsanalytics_cam13.txt"},
        "cam16": {"enabled": True,  "uri": "rtsp://65.1.214.31:8554/gj/cam16", "analytics": "config_nvdsanalytics_cam16.txt"},
        "cam20": {"enabled": True,  "uri": "rtsp://65.1.214.31:8554/gj/cam20", "analytics": "config_nvdsanalytics_cam20.txt"},
    },
}


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


# =============================================================================
# GEOMETRY / CAMERA SPEC
# =============================================================================

class Roi:
    def __init__(self, name, pts, inverse=False):
        self.name = name
        self.pts = np.asarray(pts, dtype=np.float32)
        self.inverse = inverse

    def contains(self, x, y):
        inside = cv2.pointPolygonTest(self.pts, (float(x), float(y)), False) >= 0
        return (not inside) if self.inverse else inside

    def centroid(self):
        return float(self.pts[:, 0].mean()), float(self.pts[:, 1].mean())


class Line:
    """Door line a->b. inside_sign: sign of cross(b-a, p-a) for points inside the store."""

    def __init__(self, name, a, b, inside_sign, mode="both", inside_desc=""):
        self.name = name
        self.a = np.asarray(a, dtype=np.float64)
        self.b = np.asarray(b, dtype=np.float64)
        self.inside_sign = 1 if inside_sign >= 0 else -1
        self.mode = mode                      # both | entry_only | exit_only
        self.inside_desc = inside_desc
        v = self.b - self.a
        self.len = float(np.hypot(v[0], v[1])) or 1.0
        self.v = v

    def side_of(self, x, y):
        return self.v[0] * (y - self.a[1]) - self.v[1] * (x - self.a[0])

    def signed_dist_and_t(self, x, y):
        dx, dy = x - self.a[0], y - self.a[1]
        d = (self.v[0] * dy - self.v[1] * dx) / self.len
        t = (dx * self.v[0] + dy * self.v[1]) / (self.len ** 2)
        return d, t


class CameraSpec:
    def __init__(self, rois, lines, zones):
        self.rois = rois
        self.lines = lines
        self.zones = zones          # list of Roi used for "top_zone"

    def in_roi(self, x, y):
        if not self.rois:
            return True
        return any(r.contains(x, y) for r in self.rois)


def _nums(text):
    return [float(v) for v in re.split(r"[;,\s]+", text.strip()) if v != ""]


def parse_analytics_file(path):
    """Read [property], roi-filtering-stream-*, line-crossing-stream-* (case preserved)."""
    sections, cur = {}, None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("[") and s.endswith("]"):
                cur = s[1:-1].strip()
                sections.setdefault(cur, [])
                continue
            if cur is not None and "=" in s:
                k, v = s.split("=", 1)
                sections[cur].append((k.strip(), v.strip()))
    prop = dict(sections.get("property", []))
    cw = float(prop.get("config-width", MUX_W))
    ch = float(prop.get("config-height", MUX_H))

    rois, raw_lines = [], []
    for sec, items in sections.items():
        low = sec.lower()
        kv = dict(items)
        if kv.get("enable", "1").strip() == "0":
            continue
        if low.startswith("roi-filtering-stream"):
            inverse = kv.get("inverse-roi", "0").strip() == "1"
            for k, v in items:
                if k.lower().startswith("roi-"):
                    n = _nums(v)
                    if len(n) >= 6:
                        pts = np.array(n[: len(n) // 2 * 2], dtype=np.float32).reshape(-1, 2)
                        rois.append((k[4:], pts, inverse))
        elif low.startswith("line-crossing-stream"):
            for k, v in items:
                if k.lower().startswith("line-crossing-"):
                    n = _nums(v)
                    if len(n) in (4, 8):
                        raw_lines.append((k[len("line-crossing-"):], n))
    return (cw, ch), rois, raw_lines


def build_camera_spec(name, cfg, coord_wh):
    rois, lines, zones = [], [], []
    raw_lines = []

    analytics = cfg.get("analytics")
    if analytics:
        if os.path.isfile(analytics):
            (cw, ch), roi_defs, raw_lines = parse_analytics_file(analytics)
            sx, sy = MUX_W / cw, MUX_H / ch
            for rname, pts, inv in roi_defs:
                rois.append(Roi(rname, pts * np.array([sx, sy], dtype=np.float32), inv))
            raw_lines = [(ln, [v * (sx if i % 2 == 0 else sy) for i, v in enumerate(n)])
                         for ln, n in raw_lines]
        else:
            log(f"[{name}] analytics file not found: {analytics} (no ROI/lines from it)")

    jsx, jsy = MUX_W / float(coord_wh[0]), MUX_H / float(coord_wh[1])

    def jpt(p):
        return [float(p[0]) * jsx, float(p[1]) * jsy]

    # JSON "lines" override analytics lines
    if cfg.get("lines"):
        raw_lines = []
        for ld in cfg["lines"]:
            seg = ld["line"]
            pts = jpt(seg[0:2]) + jpt(seg[2:4])
            raw_lines.append((ld.get("name", "Door"), pts, ld.get("inside_point")))
    else:
        raw_lines = [(ln, n, cfg.get("inside_point")) for ln, n in raw_lines]

    has_entry_named = any("entry" in ln.lower() and len(n) == 8 for ln, n, _ in raw_lines)
    has_exit_named = any("exit" in ln.lower() and len(n) == 8 for ln, n, _ in raw_lines)

    for ln, n, inside_pt in raw_lines:
        if len(n) == 8:
            # nvdsanalytics format: direction (x1,y1)->(x2,y2), line (x3,y3)-(x4,y4)
            d1, d2, a, b = np.array(n[0:2]), np.array(n[2:4]), n[4:6], n[6:8]
            line = Line(ln, a, b, 1)
            mid = (np.array(a) + np.array(b)) / 2.0
            fwd = mid + (d2 - d1)
            fwd_sign = 1 if line.side_of(fwd[0], fwd[1]) >= 0 else -1
            is_exit = "exit" in ln.lower()
            inside_sign = -fwd_sign if is_exit else fwd_sign
            mode = "both"
            if has_entry_named and has_exit_named:
                mode = "exit_only" if is_exit else ("entry_only" if "entry" in ln.lower() else "both")
            lines.append(Line(ln, a, b, inside_sign, mode,
                              "direction vector" + (" (exit line)" if is_exit else "")))
        else:
            a, b = n[0:2], n[2:4]
            probe_line = Line(ln, a, b, 1)
            if inside_pt:
                p = jpt(inside_pt)
                desc = f"inside_point {tuple(int(v) for v in p)}"
            elif rois:
                p = rois[0].centroid()
                desc = f"ROI centroid {tuple(int(v) for v in p)}"
            else:
                mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                p = (mid[0], mid[1] + 100.0)
                desc = "below the line (default)"
            s = probe_line.side_of(p[0], p[1])
            lines.append(Line(ln, a, b, 1 if s >= 0 else -1, "both", desc))

    for zname, zpts in (cfg.get("zones") or {}).items():
        zones.append(Roi(zname, np.array([jpt(p) for p in zpts], dtype=np.float32)))
    if not zones:
        zones = list(rois)

    return CameraSpec(rois, lines, zones)


def _cfg_value(lines, key):
    for line in lines:
        s = line.strip()
        if s.startswith(key + "="):
            return s.split("=", 1)[1].strip()
    return None


def genderage_normalisation(onnx_path):
    """InsightFace rule: Sub+Mul in the first graph nodes -> raw pixels, else (x-127.5)/128."""
    try:
        import onnx
        nodes = onnx.load(onnx_path).graph.node[:8]
        has_sub = any(n.name.startswith(("Sub", "_minus")) for n in nodes)
        has_mul = any(n.name.startswith(("Mul", "_mul")) for n in nodes)
        if has_sub and has_mul:
            return 1.0, "0.0;0.0;0.0"
        return 1.0 / 128.0, "127.5;127.5;127.5"
    except Exception as e:
        log(f"[TGIE] could not inspect {onnx_path} ({e}); keeping config normalisation")
        return None


def setup_tgie():
    """Generate TGIE config from config_infer_tertiary_genderage.txt. Returns True if usable."""
    if not os.path.isfile(TGIE_BASE_CONFIG):
        log(f"[TGIE] {TGIE_BASE_CONFIG} not found -> age/gender DISABLED")
        return None
    with open(TGIE_BASE_CONFIG) as f:
        lines = f.read().splitlines()

    onnx_file = _cfg_value(lines, "onnx-file")
    engine_file = _cfg_value(lines, "model-engine-file")
    if not ((onnx_file and os.path.isfile(onnx_file)) or (engine_file and os.path.isfile(engine_file))):
        log(f"[TGIE] neither {onnx_file} nor {engine_file} exists -> age/gender DISABLED")
        return None

    overrides = {
        "gie-unique-id": str(TGIE_UID),
        "operate-on-gie-id": "1",
        "operate-on-class-ids": str(CLASS_FACE),
        "process-mode": "2",
        "network-type": "100",          # "other": no built-in postprocess, raw tensor only
        "output-tensor-meta": "1",
        "model-color-format": "0",      # RGB
        "maintain-aspect-ratio": "0",
        "classifier-async-mode": "0",
    }
    norm = genderage_normalisation(onnx_file) if onnx_file and os.path.isfile(onnx_file) else None
    if norm is not None:
        overrides["net-scale-factor"] = repr(norm[0])
        overrides["offsets"] = norm[1]

    out, section, in_prop = [], None, False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_prop:
                out += [f"{k}={v}" for k, v in overrides.items()]
            section = s[1:-1].strip().lower()
            in_prop = section == "property"
            out.append(line)
            continue
        if in_prop and "=" in s and not s.startswith("#") and s.split("=", 1)[0].strip() in overrides:
            continue
        out.append(line)
    if in_prop:
        out += [f"{k}={v}" for k, v in overrides.items()]

    with open(TGIE_RUNTIME_CONFIG, "w") as f:
        f.write("\n".join(out) + "\n")
    log(f"[TGIE] wrote {TGIE_RUNTIME_CONFIG} (engine={engine_file}, "
        f"net-scale-factor={overrides.get('net-scale-factor', 'from config')}, "
        f"offsets={overrides.get('offsets', 'from config')})")
    return True


_TENSOR_META_TYPE = getattr(pyds, "NVDSINFER_TENSOR_OUTPUT_META", None)


def read_genderage(obj):
    """Return (male_prob, age) from the TGIE raw tensor attached to a face object, or None."""
    l_user = obj.obj_user_meta_list
    while l_user is not None:
        try:
            um = pyds.NvDsUserMeta.cast(l_user.data)
        except StopIteration:
            break
        if um is not None and um.base_meta.meta_type == _TENSOR_META_TYPE:
            tm = pyds.NvDsInferTensorMeta.cast(um.user_meta_data)
            if int(tm.unique_id) == TGIE_UID and tm.num_output_layers > 0:
                layer = pyds.get_nvds_LayerInfo(tm, 0)
                ptr = ctypes.cast(pyds.get_ptr(layer.buffer), ctypes.POINTER(ctypes.c_float))
                v = np.ctypeslib.as_array(ptr, shape=(3,)).copy()
                g = v[:2] - np.max(v[:2])
                e = np.exp(g)
                return float(e[1] / e.sum()), float(v[2] * 100.0)
        try:
            l_user = l_user.next
        except StopIteration:
            break
    return None


def face_expand_probe(pad, info, _user_data):
    """Before the TGIE: grow each face box to the 1.5x square crop InsightFace was trained on."""
    buf = info.get_buffer()
    if buf is None:
        return Gst.PadProbeReturn.OK
    try:
        batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    except Exception:
        return Gst.PadProbeReturn.OK
    l_frame = batch.frame_meta_list
    while l_frame is not None:
        try:
            fm = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break
        l_obj = fm.obj_meta_list
        while l_obj is not None:
            try:
                obj = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break
            if obj.class_id == CLASS_FACE:
                r = obj.rect_params
                cx, cy = r.left + r.width / 2.0, r.top + r.height / 2.0
                side = max(r.width, r.height) * FACE_EXPAND
                x1, y1 = max(0.0, cx - side / 2.0), max(0.0, cy - side / 2.0)
                x2, y2 = min(float(MUX_W - 1), cx + side / 2.0), min(float(MUX_H - 1), cy + side / 2.0)
                if x2 > x1 and y2 > y1:
                    r.left, r.top, r.width, r.height = x1, y1, x2 - x1, y2 - y1
            try:
                l_obj = l_obj.next
            except StopIteration:
                break
        try:
            l_frame = l_frame.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


def match_face_to_person(face_box, persons):
    """persons: list of (oid, (x1,y1,x2,y2)). Face must sit inside the upper part of a person box."""
    fx1, fy1, fx2, fy2 = face_box
    fw, fh = max(1.0, fx2 - fx1), max(1.0, fy2 - fy1)
    fcx, fcy = (fx1 + fx2) / 2.0, (fy1 + fy2) / 2.0
    best, best_score = None, -1e9
    for oid, (px1, py1, px2, py2) in persons:
        pw, ph = px2 - px1, py2 - py1
        if pw <= 1 or ph <= 1:
            continue
        iw = max(0.0, min(fx2, px2) - max(fx1, px1))
        ih = max(0.0, min(fy2, py2) - max(fy1, py1))
        ioa = iw * ih / (fw * fh)
        if ioa < 0.6:
            continue
        rel_y = (fcy - py1) / ph
        if rel_y > 0.5 or fw > 1.2 * pw:
            continue
        rel_x = abs(fcx - (px1 + px2) / 2.0) / pw
        score = ioa - 0.8 * rel_x - 0.5 * max(0.0, rel_y - 0.15)
        if score > best_score:
            best, best_score = oid, score
    return best


# =============================================================================
# AGE / GENDER (InsightFace genderage.onnx via onnxruntime)
# =============================================================================

class AgeGenderModel:
    def __init__(self, path):
        import onnxruntime as ort
        providers = ["CPUExecutionProvider"]
        if AG_USE_CUDA and "CUDAExecutionProvider" in ort.get_available_providers():
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.sess = ort.InferenceSession(path, providers=providers)
        inp = self.sess.get_inputs()[0]
        self.input_name = inp.name
        self.size = inp.shape[2] if isinstance(inp.shape[2], int) else 96
        self.output_name = self.sess.get_outputs()[0].name
        # Same rule InsightFace uses to pick normalisation
        self.mean, self.std = 0.0, 1.0
        try:
            import onnx
            nodes = onnx.load(path).graph.node[:8]
            has_sub = any(n.name.startswith(("Sub", "_minus")) for n in nodes)
            has_mul = any(n.name.startswith(("Mul", "_mul")) for n in nodes)
            if not (has_sub and has_mul):
                self.mean, self.std = 127.5, 128.0
        except Exception:
            pass
        log(f"[AGE/GENDER] Loaded {path} ({providers[0]}, input {self.size}, "
            f"mean={self.mean}, std={self.std})")

    def predict(self, bgr, center, face_size):
        s = self.size / (face_size * 1.5)
        M = np.array([[s, 0, self.size / 2.0 - center[0] * s],
                      [0, s, self.size / 2.0 - center[1] * s]], dtype=np.float32)
        aimg = cv2.warpAffine(bgr, M, (self.size, self.size), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(aimg, 1.0 / self.std, (self.size, self.size),
                                     (self.mean, self.mean, self.mean), swapRB=True)
        pred = self.sess.run([self.output_name], {self.input_name: blob})[0][0]
        g = pred[:2] - np.max(pred[:2])
        e = np.exp(g)
        male_prob = float(e[1] / e.sum())
        age = float(pred[2] * 100.0)
        return male_prob, age


def load_age_gender_model():
    for p in GENDERAGE_MODEL_CANDIDATES:
        if p and os.path.isfile(p):
            try:
                return AgeGenderModel(p)
            except Exception as e:
                log(f"[AGE/GENDER] Failed to load {p}: {e}")
    log("[AGE/GENDER] genderage.onnx not found -> age/gender DISABLED "
        "(counts and heatmaps still run). See GENDERAGE_MODEL_CANDIDATES.")
    return None


def age_bucket(age):
    a = int(round(age))
    for key, lo, hi in AGE_BUCKETS:
        if lo <= a <= hi:
            return key
    return "50_plus"


# =============================================================================
# RUNTIME STATE
# =============================================================================

class Track:
    __slots__ = ("first_seen", "last_seen", "sides", "last_evt", "entered", "in_roi_ever",
                 "samples", "attempts", "next_face_t", "gender", "age", "demo_counted")

    def __init__(self, now):
        self.first_seen = now
        self.last_seen = now
        self.sides = {}
        self.last_evt = {}
        self.entered = False
        self.in_roi_ever = False
        self.samples = []
        self.attempts = 0
        self.next_face_t = 0.0
        self.gender = None
        self.age = None
        self.demo_counted = False


class CamState:
    def __init__(self, name):
        self.name = name
        self.cfg = {}
        self.cfg_sig = None
        self.spec = CameraSpec([], [], [])
        self.uri = ""
        self.slot = None
        self.epoch = 0
        self.bin = None
        self.started_t = 0.0
        self.last_frame_t = 0.0
        self.fps_frames = 0
        self.fps_t0 = time.monotonic()
        self.fps = 0.0
        self.tracks = {}
        self.last_cleanup = 0.0
        self.occupancy = 0
        self.restarts = 0
        self.need_bg = True
        self.bg = None
        self.heat = np.zeros((HEAT_GH, HEAT_GW), dtype=np.float32)
        self.zone_dwell = {}
        self.heat_key = None


STATE_LOCK = threading.RLock()
CAMS = {}                                # name -> CamState
SLOTS = [None] * MAX_SOURCES             # slot -> CamState
CUR_HOUR = datetime.now().hour
DAY = None                               # persisted daily counters

PIPELINE = MUX = TILER = LOOP = None
AG_MODEL = None
AG_QUEUE = queue.Queue(maxsize=256)
HTTP_QUEUE = queue.Queue(maxsize=1000)
HEAT_QUEUE = queue.Queue(maxsize=200)
CONFIG_MTIME = None
COORD_WH = (1920, 1080)
_last_err_t = 0.0


def new_counters():
    return {"entries": 0, "exits": 0, "male": 0, "female": 0,
            "ages": {k: 0 for k, _, _ in AGE_BUCKETS}}


def new_day(date_str):
    return {"date": date_str, "cams": {}, "hour_dwell": {}}


def day_cam(name):
    c = DAY["cams"].get(name)
    if c is None:
        c = DAY["cams"][name] = new_counters()
    if name not in DAY["hour_dwell"]:
        DAY["hour_dwell"][name] = [0.0] * 24
    return c


def load_state():
    global DAY
    today = datetime.now().strftime("%Y-%m-%d")
    DAY = new_day(today)
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            if data.get("date") == today:
                DAY = data
                DAY.setdefault("cams", {})
                DAY.setdefault("hour_dwell", {})
                log(f"[STATE] Resumed today's counters from {STATE_FILE}")
        except Exception as e:
            log(f"[STATE] Could not read {STATE_FILE}: {e}")


def save_state():
    with STATE_LOCK:
        data = json.dumps(DAY)
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"[STATE] Save failed: {e}")


def count_demographics(cam, tr):
    """Count a track's gender/age once. Line cameras: only people who entered.
    ROI-only cameras: every resolved person seen inside the ROI."""
    if tr.demo_counted or tr.gender is None:
        return
    if cam.spec.lines:
        if not tr.entered:
            return
    elif not tr.in_roi_ever:
        return
    c = day_cam(cam.name)
    c[tr.gender] += 1
    c["ages"][age_bucket(tr.age)] += 1
    tr.demo_counted = True


# =============================================================================
# PROBE
# =============================================================================

def process_frame(buf, batch, fm, now):
    slot = int(fm.pad_index)
    if not (0 <= slot < MAX_SOURCES):
        return
    with STATE_LOCK:
        cam = SLOTS[slot]
    if cam is None:
        return

    if not cam.last_frame_t:
        log(f"[{cam.name}] FIRST FRAME after {now - cam.started_t:.1f}s "
            f"(slot {slot}, {MUX_W}x{MUX_H})")
    dt = min(max(now - cam.last_frame_t, 0.0), 0.5) if cam.last_frame_t else 0.0
    cam.last_frame_t = now
    cam.fps_frames += 1
    if now - cam.fps_t0 >= 5.0:
        cam.fps = cam.fps_frames / (now - cam.fps_t0)
        cam.fps_frames, cam.fps_t0 = 0, now

    persons, faces = [], []
    l_obj = fm.obj_meta_list
    while l_obj is not None:
        try:
            obj = pyds.NvDsObjectMeta.cast(l_obj.data)
        except StopIteration:
            break
        r = obj.rect_params
        box = (float(r.left), float(r.top), float(r.left + r.width), float(r.top + r.height))
        if obj.class_id == CLASS_PERSON:
            persons.append((int(obj.object_id), box, obj))
        elif obj.class_id == CLASS_FACE:
            ag = read_genderage(obj) if AG_MODEL is not None else None
            fcx, fcy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
            fsz = max(box[2] - box[0], box[3] - box[1]) / FACE_EXPAND
            orig = (fcx - fsz / 2.0, fcy - fsz / 2.0, fcx + fsz / 2.0, fcy + fsz / 2.0)
            faces.append((orig, float(obj.confidence), ag))
            if DISPLAY:
                r.border_width = 1
                r.border_color.set(0.0, 0.6, 1.0, 1.0)
                obj.text_params.display_text = ""
        try:
            l_obj = l_obj.next
        except StopIteration:
            break

    spec = cam.spec
    crop_requests = []
    gx_scale, gy_scale = HEAT_GW / float(MUX_W), HEAT_GH / float(MUX_H)

    with STATE_LOCK:
        counters = day_cam(cam.name)
        occupancy = 0
        for oid, (x1, y1, x2, y2), obj in persons:
            tr = cam.tracks.get(oid)
            if tr is None:
                tr = cam.tracks[oid] = Track(now)
            tr.last_seen = now
            fx, fy = (x1 + x2) / 2.0, y2

            if spec.in_roi(fx, fy):
                occupancy += 1
                tr.in_roi_ever = True
                if dt > 0:
                    gx = min(HEAT_GW - 1, max(0, int(fx * gx_scale)))
                    gy = min(HEAT_GH - 1, max(0, int(fy * gy_scale)))
                    cam.heat[gy, gx] += dt
                    for z in spec.zones:
                        if z.contains(fx, fy):
                            cam.zone_dwell[z.name] = cam.zone_dwell.get(z.name, 0.0) + dt
                    if not spec.lines:
                        count_demographics(cam, tr)

            for line in spec.lines:
                d, t = line.signed_dist_and_t(fx, fy)
                if abs(d) < LINE_HYST_PX:
                    continue
                cur = 1 if d > 0 else -1
                prev = tr.sides.get(line.name)
                tr.sides[line.name] = cur
                if prev is None or prev == cur:
                    continue
                if not (-LINE_SEGMENT_MARGIN <= t <= 1.0 + LINE_SEGMENT_MARGIN):
                    continue
                if now - tr.last_evt.get(line.name, -1e9) < LINE_EVENT_COOLDOWN_SEC:
                    continue
                direction = "entry" if cur == line.inside_sign else "exit"
                if (line.mode == "entry_only" and direction != "entry") or \
                   (line.mode == "exit_only" and direction != "exit"):
                    continue
                tr.last_evt[line.name] = now
                if direction == "entry":
                    counters["entries"] += 1
                    tr.entered = True
                    count_demographics(cam, tr)
                else:
                    counters["exits"] += 1
                demo = f" {tr.gender}/{tr.age}" if tr.gender else ""
                log(f"[{cam.name}] {direction.upper()} id={oid} line={line.name}{demo} "
                    f"(in={counters['entries']} out={counters['exits']})")

            if DISPLAY:
                label = f"{oid}"
                if tr.gender:
                    label += f" {'M' if tr.gender == 'male' else 'F'}{tr.age}"
                obj.text_params.display_text = label

        cam.occupancy = occupancy
        if dt > 0 and occupancy:
            DAY["hour_dwell"][cam.name][CUR_HOUR] += occupancy * dt

        # face (TGIE result) -> person track -> vote
        if AG_MODEL is not None and faces and persons:
            needing = []
            for oid, box, _ in persons:
                tr = cam.tracks.get(oid)
                if tr is not None and tr.gender is None and tr.attempts < AG_MAX_ATTEMPTS \
                        and now >= tr.next_face_t:
                    needing.append((oid, box))
            if needing:
                best_face = {}
                for fbox, fconf, ag in faces:
                    if ag is None:
                        continue
                    fw, fh = fbox[2] - fbox[0], fbox[3] - fbox[1]
                    if fconf < FACE_MIN_CONF or min(fw, fh) < FACE_MIN_PX:
                        continue
                    oid = match_face_to_person(fbox, needing)
                    if oid is not None and (oid not in best_face or fconf > best_face[oid][0]):
                        best_face[oid] = (fconf, ag)
                for oid, (_, (male_prob, age)) in best_face.items():
                    tr = cam.tracks[oid]
                    tr.attempts += 1
                    tr.next_face_t = now + AG_SAMPLE_INTERVAL_SEC
                    tr.samples.append((male_prob, age))
                    if len(tr.samples) >= AG_MIN_SAMPLES:
                        mp = float(np.mean([s[0] for s in tr.samples]))
                        tr.gender = "male" if mp >= 0.5 else "female"
                        tr.age = int(round(float(np.median([s[1] for s in tr.samples]))))
                        count_demographics(cam, tr)

        if now - cam.last_cleanup > 2.0:
            cam.last_cleanup = now
            for oid in [k for k, v in cam.tracks.items() if now - v.last_seen > TRACK_TTL_SEC]:
                del cam.tracks[oid]

        need_bg = cam.need_bg
        epoch = cam.epoch

    # ---- pixel access only when needed ----
    if crop_requests or need_bg:
        try:
            surf = pyds.get_nvds_buf_surface(hash(buf), fm.batch_id)
            H, W = surf.shape[0], surf.shape[1]
            for oid, (x1, y1, x2, y2) in crop_requests:
                fsz = max(x2 - x1, y2 - y1)
                side = fsz * 1.5 * 1.15
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                cx1, cy1 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
                cx2, cy2 = int(min(W, cx + side / 2)), int(min(H, cy + side / 2))
                if cx2 - cx1 < 8 or cy2 - cy1 < 8:
                    continue
                crop = np.array(surf[cy1:cy2, cx1:cx2], copy=True, order="C")
                try:
                    AG_QUEUE.put_nowait((cam.name, epoch, oid, crop, (cx - cx1, cy - cy1), fsz))
                except queue.Full:
                    pass
            if need_bg:
                full = np.array(surf, copy=True, order="C")
                bg = cv2.resize(cv2.cvtColor(full, cv2.COLOR_RGBA2BGR), (HEAT_BG_W, HEAT_BG_H))
                with STATE_LOCK:
                    cam.bg = bg
                    cam.need_bg = False
        finally:
            if IS_JETSON:
                pyds.unmap_nvds_buf_surface(hash(buf), fm.batch_id)

    if DISPLAY:
        draw_overlay(batch, fm, cam)


def draw_overlay(batch, fm, cam):
    segs = []
    for r in cam.spec.rois:
        p = r.pts.astype(int)
        for i in range(len(p)):
            segs.append((p[i], p[(i + 1) % len(p)], (0.0, 1.0, 0.0)))
    for ln in cam.spec.lines:
        segs.append((ln.a.astype(int), ln.b.astype(int), (1.0, 1.0, 0.0)))

    c = DAY["cams"].get(cam.name, new_counters())
    first = True
    while segs or first:
        dm = pyds.nvds_acquire_display_meta_from_pool(batch)
        chunk, segs = segs[:16], segs[16:]
        dm.num_lines = len(chunk)
        for i, (a, b, col) in enumerate(chunk):
            lp = dm.line_params[i]
            lp.x1, lp.y1, lp.x2, lp.y2 = int(a[0]), int(a[1]), int(b[0]), int(b[1])
            lp.line_width = 3
            lp.line_color.set(col[0], col[1], col[2], 1.0)
        if first:
            dm.num_labels = 1
            tp = dm.text_params[0]
            tp.display_text = (f"{cam.name}  in:{c['entries']} out:{c['exits']} "
                               f"now:{cam.occupancy}  M:{c['male']} F:{c['female']}  "
                               f"{cam.fps:.1f}fps")
            tp.x_offset, tp.y_offset = 10, 10
            tp.font_params.font_name = "Sans"
            tp.font_params.font_size = 20
            tp.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
            tp.set_bg_clr = 1
            tp.text_bg_clr.set(0.0, 0.0, 0.0, 0.6)
            first = False
        pyds.nvds_add_display_meta_to_frame(fm, dm)


def frame_probe(pad, info, _user_data):
    global _last_err_t
    buf = info.get_buffer()
    if buf is None:
        return Gst.PadProbeReturn.OK
    try:
        batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    except Exception:
        return Gst.PadProbeReturn.OK
    if batch is None:
        return Gst.PadProbeReturn.OK

    now = time.monotonic()
    l_frame = batch.frame_meta_list
    while l_frame is not None:
        try:
            fm = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break
        try:
            process_frame(buf, batch, fm, now)
        except Exception:
            if now - _last_err_t > 10:
                _last_err_t = now
                log("[PROBE ERROR]\n" + traceback.format_exc())
        try:
            l_frame = l_frame.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


# =============================================================================
# WORKERS: age/gender, HTTP, heatmap
# =============================================================================

def ag_worker():
    while True:
        cam_name, epoch, oid, crop_rgba, center, fsz = AG_QUEUE.get()
        try:
            bgr = cv2.cvtColor(crop_rgba, cv2.COLOR_RGBA2BGR)
            male_prob, age = AG_MODEL.predict(bgr, center, fsz)
        except Exception as e:
            log(f"[AGE/GENDER] inference error: {e}")
            continue
        with STATE_LOCK:
            cam = CAMS.get(cam_name)
            if cam is None or cam.epoch != epoch:
                continue
            tr = cam.tracks.get(oid)
            if tr is None or tr.gender is not None:
                continue
            tr.samples.append((male_prob, age))
            if len(tr.samples) >= AG_MIN_SAMPLES:
                mp = float(np.mean([s[0] for s in tr.samples]))
                tr.gender = "male" if mp >= 0.5 else "female"
                tr.age = int(round(float(np.median([s[1] for s in tr.samples]))))
                count_demographics(cam, tr)


def http_worker():
    while True:
        desc, fn = HTTP_QUEUE.get()
        for attempt in range(3):
            try:
                fn()
                break
            except Exception as e:
                if attempt == 2:
                    log(f"[HTTP] {desc} failed: {e}")
                else:
                    time.sleep(2 + attempt * 3)


def http_enqueue(desc, fn):
    try:
        HTTP_QUEUE.put_nowait((desc, fn))
    except queue.Full:
        log(f"[HTTP] queue full, dropping {desc}")


# ---------------------------------------------------------------------------
# UPLOADER  (request format from cv_test_push_demo.py)
#   footfall : newest cumulative payload per camera per day, persisted to
#              footfall_pending.json until the backend accepts it
#   heatmaps : every heatmaps/<cam>/*.png without a .sent marker is uploaded,
#              oldest first (this also backfills PNGs saved while offline)
# ---------------------------------------------------------------------------
UPLOAD_USER_AGENT = "CV-Footfall-Pipeline/1.0"
FF_PENDING_FILE = os.environ.get("FOOTFALL_PENDING_FILE", "footfall_pending.json")
UPLOAD_RETRY_SEC = 30

_FF_PENDING = {}                 # "cam|YYYY-MM-DD" -> payload
_FF_LOCK = threading.Lock()
UPLOAD_WAKE = threading.Event()
BACKEND_ONLINE = [None]
_UPLOAD_LAST_ERR = [0.0]


class _Retry(Exception):
    """Network problem or 5xx: stop this round and retry later."""


def _hour_range(h):
    return f"{h % 24:02d}:00-{(h + 1) % 24:02d}:00"


def _http_post_json(url, payload, timeout=15):
    req = urllib.request.Request(
        url=url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UPLOAD_USER_AGENT},
        method="POST")
    return _http_send(req, timeout)


def _http_post_multipart(url, fields, filename, file_bytes, timeout=20):
    boundary = f"----FormBoundary{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        url=url, data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": UPLOAD_USER_AGENT},
        method="POST")
    return _http_send(req, timeout)


def _http_send(req, timeout):
    """Returns (ok, detail). ok=False means rejected (4xx) -> do not retry. Raises _Retry."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200] if e.fp else ""
        if e.code in (408, 429) or e.code >= 500:
            raise _Retry(f"HTTP {e.code}: {body}")
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        raise _Retry(str(e))


def _ff_save():
    with _FF_LOCK:
        data = json.dumps(_FF_PENDING)
    tmp = FF_PENDING_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, FF_PENDING_FILE)
    except Exception as e:
        log(f"[UPLOAD] could not save {FF_PENDING_FILE}: {e}")


def _ff_load():
    if os.path.isfile(FF_PENDING_FILE):
        try:
            with open(FF_PENDING_FILE) as f:
                data = json.load(f)
            with _FF_LOCK:
                for k, v in data.items():
                    _FF_PENDING.setdefault(k, v)
            if data:
                log(f"[UPLOAD] {len(data)} unsent footfall report(s) loaded from {FF_PENDING_FILE}")
        except Exception as e:
            log(f"[UPLOAD] could not read {FF_PENDING_FILE}: {e}")


def post_footfall(payload):
    key = f"{payload['cam_id']}|{str(payload['timestamp'])[:10]}"
    with _FF_LOCK:
        _FF_PENDING[key] = payload
    _ff_save()
    UPLOAD_WAKE.set()


def _upload_ok():
    if BACKEND_ONLINE[0] is not True:
        log(f"[UPLOAD] backend reachable: {BACKEND_URL}")
    BACKEND_ONLINE[0] = True


def _upload_down(what, err):
    BACKEND_ONLINE[0] = False
    if time.time() - _UPLOAD_LAST_ERR[0] > 60:
        _UPLOAD_LAST_ERR[0] = time.time()
        with _FF_LOCK:
            n_ff = len(_FF_PENDING)
        log(f"[UPLOAD] backend unreachable ({what} -> {BACKEND_URL}): {err} | "
            f"pending: {n_ff} footfall, {len(_unsent_heatmaps())} heatmap(s); retry every {UPLOAD_RETRY_SEC}s")


def flush_footfall():
    today = datetime.now().strftime("%Y-%m-%d")
    with _FF_LOCK:
        items = sorted(_FF_PENDING.items(), key=lambda kv: (kv[0].split("|")[1], kv[0]))
    for key, p in items:
        try:
            ok, detail = _http_post_json(FOOTFALL_URL, p)
        except _Retry as e:
            _upload_down("footfall", e)
            return False
        _upload_ok()
        with _FF_LOCK:
            if _FF_PENDING.get(key) is p:
                del _FF_PENDING[key]
        _ff_save()
        if not ok:
            log(f"[UPLOAD] footfall {key} REJECTED by backend, dropped: {detail}")
        elif not key.endswith(today):
            log(f"[UPLOAD] footfall {key} sent (backfill): in={p['entries']} out={p['exits']}")
    return True


def _unsent_heatmaps():
    out = []
    for path in glob.glob(os.path.join(HEATMAP_DIR, "*", "*.png")):
        if os.path.exists(path + ".sent") or os.path.exists(path + ".rejected"):
            continue
        if time.time() - os.path.getmtime(path) < 10:        # still being written
            continue
        out.append(path)
    return sorted(out, key=lambda p: (os.path.basename(p), p))


def _heatmap_fields(path):
    """Fields for an upload: from the .json sidecar, or rebuilt for PNGs saved before sidecars existed."""
    side = path[:-4] + ".json"
    if os.path.isfile(side):
        with open(side) as f:
            d = json.load(f)
        return d["cam_id"], {"cam_id": d["cam_id"], "peak_density": d["peak_density"],
                             "meta_info": json.dumps(d["meta_info"])}

    cam = os.path.basename(os.path.dirname(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    hour_start = datetime.strptime(stem, "%Y%m%d_%H%M")
    h = hour_start.hour
    peak_h, rel = h, 0.0
    with STATE_LOCK:
        hd = DAY["hour_dwell"].get(cam) if DAY["date"] == hour_start.strftime("%Y-%m-%d") else None
        c = CAMS.get(cam)
        zones = [z.name for z in c.spec.zones] if c is not None else []
    if hd:
        upto = hd[:h + 1]
        if max(upto) > 0:
            peak_h = int(np.argmax(upto))
            rel = float(hd[h] / max(upto))
    meta = {
        "peak_hour": _hour_range(peak_h),
        "top_zone": zones[0] if zones else "Full frame",
        "generated_at": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
        "hour": f"{hour_start:%Y-%m-%d %H}:00",
        "backfill": True,
        "peak_density_basis": "hour dwell relative to busiest hour so far (backfill)",
    }
    return cam, {"cam_id": cam, "peak_density": f"{rel:.3f}", "meta_info": json.dumps(meta)}


def flush_heatmaps():
    for path in _unsent_heatmaps():
        try:
            cam, fields = _heatmap_fields(path)
            with open(path, "rb") as f:
                png = f.read()
        except Exception as e:
            log(f"[UPLOAD] cannot prepare {path}: {e}")
            open(path + ".rejected", "w").write(str(e))
            continue
        try:
            ok, detail = _http_post_multipart(HEATMAP_URL, fields, f"{cam}_{os.path.basename(path)}", png)
        except _Retry as e:
            _upload_down("heatmap", e)
            return False
        _upload_ok()
        marker = ".sent" if ok else ".rejected"
        with open(path + marker, "w") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {detail}\n")
        log(f"[UPLOAD] heatmap {path} {'uploaded' if ok else 'REJECTED: ' + detail}")
    return True


def uploader_worker():
    _ff_load()
    while True:
        UPLOAD_WAKE.clear()
        try:
            if flush_footfall():
                flush_heatmaps()
        except Exception:
            log("[UPLOAD ERROR]\n" + traceback.format_exc())
        UPLOAD_WAKE.wait(UPLOAD_RETRY_SEC)


def fmt_hour(h):
    return datetime(2000, 1, 1, h).strftime("%I:%M %p").lstrip("0")


def heatmap_worker():
    while True:
        job = HEAT_QUEUE.get()
        try:
            render_and_upload_heatmap(**job)
        except Exception:
            log("[HEATMAP ERROR]\n" + traceback.format_exc())


def render_and_upload_heatmap(cam_name, hour_start, grid, zone_dwell, bg, rois, hour_dwell):
    total = float(grid.sum())
    if total <= 0 and not HEATMAP_UPLOAD_EMPTY:
        log(f"[HEATMAP] {cam_name} {hour_start:%Y-%m-%d %H}:00 no activity, skipped")
        return

    g = cv2.GaussianBlur(grid, (0, 0), HEAT_SIGMA)

    mask = np.zeros((HEAT_GH, HEAT_GW), dtype=np.uint8)
    for r in rois:
        pts = (r.pts * np.array([HEAT_GW / MUX_W, HEAT_GH / MUX_H])).astype(np.int32)
        cv2.fillPoly(mask, [pts], 1)
    vals = g[mask > 0] if mask.any() else g.ravel()
    vsum = float(vals.sum())
    if vsum > 0:
        k = max(1, int(len(vals) * HEAT_TOP_FRACTION))
        peak_density = float(np.sort(vals)[-k:].sum() / vsum)
    else:
        peak_density = 0.0

    base = bg.copy() if bg is not None else np.zeros((HEAT_BG_H, HEAT_BG_W, 3), np.uint8)
    H, W = base.shape[:2]
    norm = g / g.max() if g.max() > 0 else g
    heat = np.clip(cv2.resize(norm, (W, H), interpolation=cv2.INTER_CUBIC), 0, 1)
    colored = cv2.applyColorMap((heat * 255).astype(np.uint8), cv2.COLORMAP_JET)
    alpha = (np.sqrt(heat) * 0.65)[..., None]
    alpha[heat < 0.03] = 0
    out = (base * (1 - alpha) + colored * alpha).astype(np.uint8)

    for r in rois:
        pts = (r.pts * np.array([W / MUX_W, H / MUX_H])).astype(np.int32)
        cv2.polylines(out, [pts], True, (0, 255, 0), 2)
    title = (f"{cam_name}  {hour_start:%d-%m-%Y %H}:00-{(hour_start + timedelta(hours=1)):%H}:00  "
             f"{total / 60.0:.1f} person-min")
    cv2.rectangle(out, (0, 0), (W, 30), (0, 0, 0), -1)
    cv2.putText(out, title, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

    cam_dir = os.path.join(HEATMAP_DIR, cam_name)
    os.makedirs(cam_dir, exist_ok=True)
    path = os.path.join(cam_dir, f"{hour_start:%Y%m%d_%H}00.png")
    cv2.imwrite(path, out)

    top_zone = "Full frame"
    if zone_dwell and max(zone_dwell.values()) > 0:
        top_zone = max(zone_dwell, key=zone_dwell.get)
    peak_h = int(np.argmax(hour_dwell)) if sum(hour_dwell) > 0 else hour_start.hour

    meta_info = {
        "peak_hour": _hour_range(peak_h),
        "top_zone": top_zone,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hour": f"{hour_start:%Y-%m-%d %H}:00",
        "person_minutes": round(total / 60.0, 2),
    }
    with open(path[:-4] + ".json", "w") as f:
        json.dump({"cam_id": cam_name, "peak_density": f"{peak_density:.3f}", "meta_info": meta_info}, f)

    log(f"[HEATMAP] saved {path} peak_density={peak_density:.2f} top_zone={top_zone}")
    UPLOAD_WAKE.set()

def flush_heatmap(cam, next_key=None):
    """Swap the hour accumulator and queue render of the finished hour. Caller holds lock."""
    if cam.heat_key is not None:
        job = dict(
            cam_name=cam.name,
            hour_start=datetime.strptime(cam.heat_key, "%Y-%m-%d %H"),
            grid=cam.heat.copy(),
            zone_dwell=dict(cam.zone_dwell),
            bg=None if cam.bg is None else cam.bg.copy(),
            rois=list(cam.spec.rois),
            hour_dwell=list(DAY["hour_dwell"].get(cam.name, [0.0] * 24)),
        )
        try:
            HEAT_QUEUE.put_nowait(job)
        except queue.Full:
            log(f"[HEATMAP] queue full, dropping {cam.name}")
    cam.heat[:] = 0
    cam.zone_dwell = {}
    cam.heat_key = next_key
    cam.need_bg = True


# =============================================================================
# SOURCES (runtime add / remove)
# =============================================================================

def source_pad_added(_src, pad, source_bin):
    caps = pad.get_current_caps() or pad.query_caps(None)
    if not caps or caps.get_size() == 0 or not caps.get_structure(0).get_name().startswith("video/"):
        return
    ghost = source_bin.get_static_pad("src")
    if ghost is not None and ghost.get_target() is None:
        ghost.set_target(pad)


def create_source_bin(slot, epoch, uri):
    b = Gst.Bin.new(f"src-{slot:02d}-{epoch}")
    s = Gst.ElementFactory.make("nvurisrcbin", f"urisrc-{slot:02d}-{epoch}")
    if s is None:
        raise RuntimeError("nvurisrcbin not available")
    s.set_property("uri", uri)
    props = [("source-id", slot), ("gpu-id", GPU_ID), ("select-rtp-protocol", 4), ("latency", RTSP_LATENCY_MS),
             ("rtsp-reconnect-interval", RTSP_RECONNECT_SEC), ("disable-audio", True),
             ("drop-pipeline-eos", True)]
    if uri.startswith("file://"):
        props.append(("file-loop", True))
    for prop, val in props:
        if s.find_property(prop):
            try:
                s.set_property(prop, val)
            except Exception:
                pass
    if s.find_property("rtsp-reconnect-attempts"):
        for val in (-1, 1000000):
            try:
                s.set_property("rtsp-reconnect-attempts", val)
                break
            except Exception:
                continue
    b.add(s)
    b.add_pad(Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC))
    s.connect("pad-added", source_pad_added, b)
    return b


def update_tiler():
    if TILER is None:
        return
    used = [i for i, c in enumerate(SLOTS) if c is not None]
    n = (max(used) + 1) if used else 1
    rows = max(1, int(np.sqrt(n)))
    cols = int(np.ceil(n / rows))
    TILER.set_property("rows", rows)
    TILER.set_property("columns", cols)


def start_camera(name, cfg, sig):
    with STATE_LOCK:
        cam = CAMS.get(name)
        if cam is not None and cam.slot is not None:
            return
        free = [i for i, c in enumerate(SLOTS) if c is None]
    if not free:
        log(f"[{name}] no free slot (FOOTFALL_MAX_SOURCES={MAX_SOURCES})")
        return
    try:
        spec = build_camera_spec(name, cfg, COORD_WH)
    except Exception as e:
        log(f"[{name}] bad config: {e}")
        return

    slot = free[0]
    with STATE_LOCK:
        if cam is None:
            cam = CAMS[name] = CamState(name)
        cam.epoch += 1
        cam.cfg, cam.cfg_sig, cam.spec, cam.uri = cfg, sig, spec, cfg["uri"]
        epoch = cam.epoch

    try:
        src_bin = create_source_bin(slot, epoch, cfg["uri"])
        PIPELINE.add(src_bin)
        sinkpad = MUX.request_pad_simple(f"sink_{slot}")
        if sinkpad is None or src_bin.get_static_pad("src").link(sinkpad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("link to nvstreammux failed")
        with STATE_LOCK:
            cam.slot, cam.bin = slot, src_bin
            cam.tracks = {}
            cam.started_t = time.monotonic()
            cam.last_frame_t = 0.0
            cam.need_bg = True
            if cam.heat_key is None:
                cam.heat_key = datetime.now().strftime("%Y-%m-%d %H")
            SLOTS[slot] = cam
            day_cam(name)
        if src_bin.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("source failed to go PLAYING")
    except Exception as e:
        log(f"[{name}] start failed: {e}")
        stop_camera(name, flush=False)
        return

    update_tiler()
    log(f"[{name}] STARTED slot={slot} uri={cfg['uri']}  rois={len(spec.rois)} lines={len(spec.lines)}")
    for ln in spec.lines:
        log(f"[{name}]   line '{ln.name}' mode={ln.mode}, inside side = {ln.inside_desc}")


def stop_camera(name, flush=True):
    with STATE_LOCK:
        cam = CAMS.get(name)
        if cam is None or cam.bin is None:
            return
        slot, src_bin = cam.slot, cam.bin
        if slot is not None and SLOTS[slot] is cam:
            SLOTS[slot] = None
        cam.slot, cam.bin = None, None
        cam.tracks = {}
        cam.epoch += 1
        if flush:
            flush_heatmap(cam, None)

    try:
        src_bin.set_state(Gst.State.NULL)
    except Exception:
        pass
    if slot is not None:
        sinkpad = MUX.get_static_pad(f"sink_{slot}")
        if sinkpad is not None:
            try:
                sinkpad.send_event(Gst.Event.new_flush_stop(False))
            except Exception:
                pass
            MUX.release_request_pad(sinkpad)
    try:
        PIPELINE.remove(src_bin)
    except Exception:
        pass
    update_tiler()
    log(f"[{name}] STOPPED (slot {slot})")


def restart_camera(name, reason):
    with STATE_LOCK:
        cam = CAMS.get(name)
        if cam is None or cam.bin is None:
            return False
        cfg, sig = cam.cfg, cam.cfg_sig
        cam.restarts += 1
    log(f"[{name}] RESTART ({reason})")
    stop_camera(name, flush=False)
    start_camera(name, cfg, sig)
    return False


# =============================================================================
# CAMERA CONFIG (JSON) + RECONCILE
# =============================================================================

def ensure_cameras_json():
    if not os.path.isfile(CAMERAS_JSON):
        with open(CAMERAS_JSON, "w") as f:
            json.dump(DEFAULT_CAMERAS, f, indent=2)
        log(f"[CONFIG] Created {CAMERAS_JSON}")


def read_cameras_json():
    with open(CAMERAS_JSON) as f:
        return json.load(f)


def write_cameras_json(data):
    tmp = CAMERAS_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CAMERAS_JSON)


def cam_signature(cfg):
    a = cfg.get("analytics")
    mt = os.path.getmtime(a) if a and os.path.isfile(a) else None
    return json.dumps(cfg, sort_keys=True) + f"|{mt}"


def reconcile(force=False):
    global CONFIG_MTIME, COORD_WH
    try:
        mt = os.path.getmtime(CAMERAS_JSON)
        analytic_mts = []
        data = read_cameras_json()
    except Exception as e:
        log(f"[CONFIG] cannot read {CAMERAS_JSON}: {e}")
        return True

    cams_cfg = data.get("cameras", {})
    for cfg in cams_cfg.values():
        a = cfg.get("analytics")
        if a and os.path.isfile(a):
            analytic_mts.append(os.path.getmtime(a))
    stamp = (mt, tuple(analytic_mts))
    if not force and stamp == CONFIG_MTIME:
        return True
    CONFIG_MTIME = stamp
    COORD_WH = (data.get("coord_width", 1920), data.get("coord_height", 1080))

    desired = {n: c for n, c in cams_cfg.items() if c.get("enabled", True) and c.get("uri")}

    with STATE_LOCK:
        running = {n: c for n, c in CAMS.items() if c.bin is not None}

    for name in list(running):
        if name not in desired:
            stop_camera(name, flush=True)

    for name, cfg in desired.items():
        sig = cam_signature(cfg)
        cam = running.get(name)
        if cam is None:
            start_camera(name, cfg, sig)
        elif cam.cfg_sig != sig:
            if cfg["uri"] != cam.uri:
                stop_camera(name, flush=False)
                start_camera(name, cfg, sig)
            else:
                try:
                    spec = build_camera_spec(name, cfg, COORD_WH)
                    with STATE_LOCK:
                        cam.spec, cam.cfg, cam.cfg_sig = spec, cfg, sig
                        for tr in cam.tracks.values():
                            tr.sides.clear()
                    log(f"[{name}] ROI/lines reloaded (rois={len(spec.rois)} lines={len(spec.lines)})")
                    for ln in spec.lines:
                        log(f"[{name}]   line '{ln.name}' mode={ln.mode}, inside side = {ln.inside_desc}")
                except Exception as e:
                    log(f"[{name}] reload failed: {e}")
    return True


# =============================================================================
# TIMERS
# =============================================================================

def watchdog_tick():
    now = time.monotonic()
    with STATE_LOCK:
        stalled = [c.name for c in CAMS.values()
                   if c.bin is not None and now - (c.last_frame_t or c.started_t) > STALL_RESTART_SEC]
    for name in stalled:
        restart_camera(name, f"no frames for {STALL_RESTART_SEC}s")
    return True


def clock_tick():
    """Hour boundary -> heatmaps. Day boundary -> final report + reset counters."""
    global CUR_HOUR, DAY
    now = datetime.now()
    key = now.strftime("%Y-%m-%d %H")
    with STATE_LOCK:
        CUR_HOUR = now.hour
        for cam in CAMS.values():
            if cam.bin is not None and cam.heat_key != key:
                flush_heatmap(cam, key)
        today = now.strftime("%Y-%m-%d")
        rollover = DAY["date"] != today
    if rollover:
        send_footfall_reports(final_for_date=True)
        with STATE_LOCK:
            log(f"[STATE] Day rollover {DAY['date']} -> {today}")
            DAY = new_day(today)
            for cam in CAMS.values():
                if cam.bin is not None:
                    day_cam(cam.name)
        save_state()
    return True


def send_footfall_reports(final_for_date=False):
    with STATE_LOCK:
        date = DAY["date"]
        ts = (f"{date} 23:59:59" if final_for_date
              else datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        items = []
        for cam in CAMS.values():
            if cam.bin is None and not final_for_date:
                continue
            c = DAY["cams"].get(cam.name)
            if c is None:
                continue
            has_lines = bool(cam.spec.lines)
            net = (c["entries"] - c["exits"]) if has_lines else cam.occupancy
            items.append({
                "cam_id": cam.name,
                "entries": c["entries"],
                "exits": c["exits"],
                "net_count": max(0, net),
                "male_count": c["male"],
                "female_count": c["female"],
                "age_breakdown": dict(c["ages"]),
                "timestamp": ts,
            })
    for p in items:
        post_footfall(p)
    return True


def report_tick():
    send_footfall_reports()
    save_state()
    return True


def status_tick():
    with STATE_LOCK:
        lines = []
        for cam in sorted(CAMS.values(), key=lambda c: (c.slot is None, c.slot or 0)):
            if cam.bin is None:
                continue
            c = DAY["cams"].get(cam.name, new_counters())
            lines.append(f"  slot {cam.slot:>2} {cam.name:<6} {cam.fps:5.1f} fps  now={cam.occupancy:<3} "
                         f"in={c['entries']:<4} out={c['exits']:<4} M={c['male']:<4} F={c['female']:<4} "
                         f"tracks={len(cam.tracks):<3} restarts={cam.restarts}")
    log("[STATUS]\n" + ("\n".join(lines) if lines else "  no cameras running") +
        f"\n  queues: age/gender={AG_QUEUE.qsize()} heatmap_render={HEAT_QUEUE.qsize()} backend={'up' if BACKEND_ONLINE[0] else ('down' if BACKEND_ONLINE[0] is False else '?')} unsent_footfall={len(_FF_PENDING)}")
    return True


# =============================================================================
# COMMANDS
# =============================================================================

def handle_command(line):
    parts = line.strip().split()
    if not parts:
        return False
    op = parts[0].lower()
    try:
        if op in ("quit", "exit", "q"):
            LOOP.quit()
        elif op in ("status", "list"):
            status_tick()
        elif op == "reload":
            reconcile(force=True)
        elif op == "add" and len(parts) >= 2:
            data = read_cameras_json()
            cams = data.setdefault("cameras", {})
            cfg = cams.setdefault(parts[1], {})
            if len(parts) >= 3:
                cfg["uri"] = parts[2]
            if not cfg.get("uri"):
                log(f"{parts[1]} has no uri: use  add {parts[1]} rtsp://...")
                return False
            cfg["enabled"] = True
            cfg.setdefault("analytics", f"config_nvdsanalytics_{parts[1]}.txt")
            write_cameras_json(data)
            reconcile(force=True)
        elif op in ("del", "rm", "remove") and len(parts) == 2:
            data = read_cameras_json()
            if parts[1] in data.get("cameras", {}):
                data["cameras"][parts[1]]["enabled"] = False
                write_cameras_json(data)
            reconcile(force=True)
        else:
            log("commands: status | add <cam> [uri] | del <cam> | reload | quit")
    except Exception as e:
        log(f"command error: {e}")
    return False


def stdin_worker():
    log("commands: status | add <cam> [uri] | del <cam> | reload | quit")
    while True:
        try:
            line = input()
        except (EOFError, Exception):
            return
        GLib.idle_add(handle_command, line)


# =============================================================================
# PIPELINE
# =============================================================================

def write_pgie_config(enable_faces):
    batch = MAX_SOURCES
    out, section = [], None
    seen_batch = face_done = False
    with open(PGIE_BASE_CONFIG) as f:
        lines = f.read().splitlines()
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if section == "property" and not seen_batch:
                out.append(f"batch-size={batch}")
                seen_batch = True
            section = s[1:-1].strip().lower()
            out.append(line)
            continue
        key = s.split("=", 1)[0].strip().lower() if ("=" in s and not s.startswith("#")) else None
        if section == "property" and key == "batch-size":
            out.append(f"batch-size={batch}")
            seen_batch = True
            continue
        if enable_faces and section == "class-attrs-2" and key == "pre-cluster-threshold":
            out.append(f"pre-cluster-threshold={FACE_PGIE_THRESHOLD}")
            face_done = True
            continue
        out.append(line)
    if section == "property" and not seen_batch:
        out.append(f"batch-size={batch}")
    if enable_faces and not face_done:
        out += ["", "[class-attrs-2]", f"pre-cluster-threshold={FACE_PGIE_THRESHOLD}"]
    with open(PGIE_RUNTIME_CONFIG, "w") as f:
        f.write("\n".join(out) + "\n")
    log(f"[PGIE] wrote {PGIE_RUNTIME_CONFIG} (batch-size={batch}, faces={'on' if enable_faces else 'off'})")


def make(factory, name):
    e = Gst.ElementFactory.make(factory, name)
    if e is None:
        raise RuntimeError(f"Could not create {factory}")
    return e


def build_pipeline():
    global PIPELINE, MUX, TILER
    PIPELINE = Gst.Pipeline.new("footfall-pipeline")

    MUX = make("nvstreammux", "streammux")
    MUX.set_property("width", MUX_W)
    MUX.set_property("height", MUX_H)
    MUX.set_property("batch-size", MAX_SOURCES)
    MUX.set_property("batched-push-timeout", MUX_TIMEOUT_USEC)
    MUX.set_property("live-source", 1)
    MUX.set_property("gpu-id", GPU_ID)
    if not IS_JETSON:
        MUX.set_property("nvbuf-memory-type", 3)

    pgie = make("nvinfer", "pgie-peoplenet")
    pgie.set_property("config-file-path", PGIE_RUNTIME_CONFIG)

    tracker = make("nvtracker", "tracker")
    tcfg = configparser.ConfigParser()
    tcfg.read(TRACKER_CONFIG_FILE)
    t = tcfg["tracker"] if "tracker" in tcfg else {}
    tracker.set_property("tracker-width", int(t.get("tracker-width", 640)))
    tracker.set_property("tracker-height", int(t.get("tracker-height", 384)))
    tracker.set_property("gpu-id", GPU_ID)
    tracker.set_property("ll-lib-file", t.get(
        "ll-lib-file", "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so"))
    tracker.set_property("ll-config-file", t.get("ll-config-file", "config_tracker_NvDCF_perf.yml"))

    conv = make("nvvideoconvert", "to-rgba")
    if not IS_JETSON:
        conv.set_property("nvbuf-memory-type", 3)
    caps = make("capsfilter", "rgba-caps")
    caps.set_property("caps", Gst.Caps.from_string("video/x-raw(memory:NVMM), format=RGBA"))

    chain = [MUX, pgie, tracker]
    if AG_MODEL is not None:
        tgie = make("nvinfer", "tgie-genderage")
        tgie.set_property("config-file-path", TGIE_RUNTIME_CONFIG)
        tracker.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, face_expand_probe, None)
        chain.append(tgie)
    chain += [conv, caps]
    if DISPLAY:
        TILER = make("nvmultistreamtiler", "tiler")
        TILER.set_property("width", 1280)
        TILER.set_property("height", 720)
        conv2 = make("nvvideoconvert", "osd-conv")
        osd = make("nvdsosd", "osd")
        sink = make("nv3dsink" if IS_JETSON else "nveglglessink", "sink")
        chain += [TILER, conv2, osd, sink]
    else:
        sink = make("fakesink", "sink")
        chain += [sink]
    sink.set_property("sync", False)
    sink.set_property("async", False)   # reach PLAYING without preroll (RTSP-only start)
    try:
        sink.set_property("qos", False)
    except Exception:
        pass

    for e in chain:
        PIPELINE.add(e)
    for a, b in zip(chain, chain[1:]):
        if not a.link(b):
            raise RuntimeError(f"link failed: {a.get_name()} -> {b.get_name()}")

    caps.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, frame_probe, None)


def camera_for_element(el):
    while el is not None:
        name = el.get_name() or ""
        m = re.match(r"(?:src|urisrc)-(\d+)-(\d+)", name)
        if m:
            slot = int(m.group(1))
            with STATE_LOCK:
                cam = SLOTS[slot] if 0 <= slot < MAX_SOURCES else None
            return cam.name if cam else None
        el = el.get_parent()
    return None


def bus_call(_bus, msg, loop):
    t = msg.type
    if t == Gst.MessageType.ERROR:
        err, dbg = msg.parse_error()
        cam = camera_for_element(msg.src)
        if cam:
            log(f"[{cam}] source error: {err}")
            GLib.timeout_add_seconds(5, lambda n=cam: restart_camera(n, "source error"))
            return True
        log(f"[GST ERROR] {msg.src.get_name() if msg.src else '?'}: {err} {dbg or ''}")
        loop.quit()
    elif t == Gst.MessageType.WARNING:
        err, _ = msg.parse_warning()
        cam = camera_for_element(msg.src)
        log(f"[GST WARNING] {cam or (msg.src.get_name() if msg.src else '?')}: {err}")
    elif t == Gst.MessageType.ELEMENT:
        st = msg.get_structure()
        if st is not None and st.has_name("stream-eos"):
            ok, sid = st.get_uint("stream-id")
            if ok and 0 <= sid < MAX_SOURCES:
                with STATE_LOCK:
                    cam = SLOTS[sid]
                if cam is not None:
                    log(f"[{cam.name}] stream EOS")
                    GLib.timeout_add_seconds(5, lambda n=cam.name: restart_camera(n, "EOS"))
    elif t == Gst.MessageType.EOS:
        log("[PIPELINE] EOS")
        loop.quit()
    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    global LOOP, AG_MODEL
    os.chdir(SCRIPT_DIR)
    Gst.init(None)

    log("=" * 70)
    log("Footfall runtime: PeopleNet + NvDCF + entry/exit + age/gender + hourly heatmap")
    log(f"Backend: {BACKEND_URL}   max sources: {MAX_SOURCES}   display: {DISPLAY}")
    log("=" * 70)

    ensure_cameras_json()
    load_state()
    AG_MODEL = setup_tgie()
    write_pgie_config(enable_faces=AG_MODEL is not None)
    build_pipeline()

    for target in [http_worker, heatmap_worker, uploader_worker]:
        threading.Thread(target=target, daemon=True).start()

    LOOP = GLib.MainLoop()
    bus = PIPELINE.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, LOOP)

    def on_signal(*_):
        GLib.idle_add(LOOP.quit)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    PIPELINE.set_state(Gst.State.PLAYING)
    reconcile(force=True)

    GLib.timeout_add_seconds(2, reconcile)
    GLib.timeout_add_seconds(10, watchdog_tick)
    GLib.timeout_add_seconds(15, clock_tick)
    GLib.timeout_add_seconds(FOOTFALL_REPORT_SEC, report_tick)
    GLib.timeout_add_seconds(STATUS_PRINT_SEC, status_tick)

    if sys.stdin is not None and sys.stdin.isatty():
        threading.Thread(target=stdin_worker, daemon=True).start()

    try:
        LOOP.run()
    finally:
        log("Stopping...")
        _killer = threading.Timer(8.0, lambda: (log("Forced exit (source teardown hung)"), os._exit(0)))
        _killer.daemon = True
        _killer.start()
        send_footfall_reports()
        save_state()
        with STATE_LOCK:
            for c in CAMS.values():
                if c.slot is not None:
                    SLOTS[c.slot] = None
        PIPELINE.set_state(Gst.State.NULL)
        deadline = time.time() + 5
        while not HTTP_QUEUE.empty() and time.time() < deadline:
            time.sleep(0.2)
        log("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
